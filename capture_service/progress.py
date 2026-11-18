"""记录门户范围内已确认的采集收据与页级采集进度。"""
import hashlib
import json
from .ledger import entities
from .domain import assess

PAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS portal_pages (
  collection TEXT NOT NULL, scope TEXT NOT NULL, page_no INTEGER NOT NULL,
  page_count INTEGER NOT NULL, page_token TEXT,
  body_sha256 TEXT NOT NULL, source_url TEXT NOT NULL,
  envelope_json TEXT NOT NULL,
  recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(collection,scope,page_no));
CREATE TABLE IF NOT EXISTS portal_page_cards (
  collection TEXT NOT NULL, scope TEXT NOT NULL, page_no INTEGER NOT NULL,
  entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, entity_version TEXT NOT NULL,
  receipt_sha256 TEXT NOT NULL,
  PRIMARY KEY(collection,scope,page_no,entity_type,entity_id,entity_version),
  FOREIGN KEY(collection,scope,page_no)
    REFERENCES portal_pages(collection,scope,page_no));
"""


def initialize(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS portal_sources (
      collection TEXT NOT NULL, scope TEXT NOT NULL, card_kind TEXT NOT NULL,
      required INTEGER NOT NULL, PRIMARY KEY(collection,scope,card_kind))""")
    connection.execute("""CREATE TABLE IF NOT EXISTS portal_progress (
      collection TEXT NOT NULL, scope TEXT NOT NULL, body_sha256 TEXT NOT NULL,
      source_url TEXT NOT NULL, recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY(collection,scope,body_sha256))""")
    connection.executescript(PAGE_SCHEMA)
    connection.commit()

def register(connection, collection, expected):
    """登记待采的页面范围与卡片来源类别。"""
    initialize(connection)
    with connection:
        for item in expected:
            connection.execute(
                'INSERT INTO portal_sources(collection,scope,card_kind,required) VALUES(?,?,?,?) '
                'ON CONFLICT(collection,scope,card_kind) DO UPDATE SET required=excluded.required',
                (collection,item['scope'],item['kind'],int(item.get('required',True))))

def record(connection, collection, scope, digest, url):
    initialize(connection)
    with connection:
        connection.execute(
            'INSERT OR IGNORE INTO portal_progress(collection,scope,body_sha256,source_url) VALUES(?,?,?,?)',
            (collection,scope,digest,url))


def canonical_envelope(state):
    """冻结一个稳定页面状态的原文字节与身份哈希。"""
    envelope = {
        'scope': state['scope'],
        'page': state['page'],
        'page_count': state['page_count'],
        'page_token': state.get('page_token'),
        'cards': state['cards'],
    }
    raw = json.dumps(envelope, ensure_ascii=False, sort_keys=True).encode('utf-8')
    return raw, hashlib.sha256(raw).hexdigest()


def saved_page(connection, collection, scope, page_no):
    """返回已保存页面的摘要；未保存返回 None。"""
    initialize(connection)
    row = connection.execute(
        'SELECT body_sha256,page_count,page_token,envelope_json FROM portal_pages '
        'WHERE collection=? AND scope=? AND page_no=?',
        (collection, scope, page_no)).fetchone()
    if row is None:
        return None
    return dict(body_sha256=row[0], page_count=row[1], page_token=row[2],
                envelope=json.loads(row[3]))


def save_page(connection, collection, state, card_rows, source_url):
    """原子保存一个稳定页面及其卡片的来源映射。

    card_rows 为该页卡片入帐后返回的 (type,id,version,receipt_sha256) 列表。
    同一页面重复接收且字节一致时为空操作；同页原文变化时抛错，避免覆盖来源依据。
    """
    initialize(connection)
    scope, page_no = state['scope'], state['page']
    raw, digest = canonical_envelope(state)
    prior = saved_page(connection, collection, scope, page_no)
    if prior is not None:
        if prior['body_sha256'] != digest:
            raise ValueError(f'{scope} 第{page_no}页原文发生变化，拒绝覆盖已保存来源')
        return digest, False
    with connection:
        connection.execute(
            'INSERT INTO portal_pages(collection,scope,page_no,page_count,page_token,'
            'body_sha256,source_url,envelope_json) VALUES(?,?,?,?,?,?,?,?)',
            (collection, scope, page_no, state['page_count'], state.get('page_token'),
             digest, source_url, raw.decode('utf-8')))
        for entity_type, entity_id, version, receipt_sha256 in card_rows:
            connection.execute(
                'INSERT OR IGNORE INTO portal_page_cards(collection,scope,page_no,'
                'entity_type,entity_id,entity_version,receipt_sha256) VALUES(?,?,?,?,?,?,?)',
                (collection, scope, page_no, entity_type, entity_id, version, receipt_sha256))
    return digest, True


def page_rows(connection, collection):
    initialize(connection)
    return [dict(scope=row[0], page_no=row[1], page_count=row[2], page_token=row[3],
                 body_sha256=row[4], source_url=row[5])
            for row in connection.execute(
                'SELECT scope,page_no,page_count,page_token,body_sha256,source_url '
                'FROM portal_pages WHERE collection=? ORDER BY scope,page_no',
                (collection,))]


def card_pages(connection, collection):
    """卡片实体版本 -> 来源页映射。"""
    initialize(connection)
    return [dict(scope=row[0], page_no=row[1], entity_type=row[2], entity_id=row[3],
                 entity_version=row[4], receipt_sha256=row[5])
            for row in connection.execute(
                'SELECT scope,page_no,entity_type,entity_id,entity_version,receipt_sha256 '
                'FROM portal_page_cards WHERE collection=? '
                'ORDER BY scope,page_no,entity_id,entity_version',
                (collection,))]


def receipts(connection, collection):
    initialize(connection)
    return [dict(scope=row[0], body_sha256=row[1], source_url=row[2])
            for row in connection.execute(
                'SELECT scope,body_sha256,source_url FROM portal_progress WHERE collection=? ORDER BY scope',
                (collection,))]

def coverage(connection, collection):
    """区分门户收据与已核实的业务资料来源。"""
    initialize(connection)
    rows=connection.execute(
        'SELECT s.scope,s.card_kind,s.required,COUNT(p.body_sha256) '
        'FROM portal_sources s LEFT JOIN portal_progress p '
        'ON p.collection=s.collection AND p.scope=s.scope '
        'WHERE s.collection=? GROUP BY s.scope,s.card_kind,s.required ORDER BY s.scope,s.card_kind',
        (collection,)).fetchall()
    view=assess(entities(connection,collection))
    verified={source for pair in view['matched_pairs']
              for source in (pair['left_source'],pair['right_source'])}
    sources=[]
    for scope,kind,required,received in rows:
        source_hashes={r[0] for r in connection.execute(
            'SELECT p.body_sha256 FROM portal_progress p JOIN entities e '
            'ON e.collection=p.collection AND e.receipt_sha256=p.body_sha256 '
            'AND e.entity_type=? WHERE p.collection=? AND p.scope=?',
            (kind,collection,scope))}
        sources.append(dict(scope=scope,kind=kind,required=bool(required),
                            received_versions=received,verified=bool(source_hashes & verified)))
    return {'expected':len(rows),'received':sum(bool(row[3]) for row in rows),
            'missing_required':[dict(scope=row[0],kind=row[1]) for row in rows if row[2] and not row[3]],
            'unverified_required':[dict(scope=item['scope'],kind=item['kind']) for item in sources
                                   if item['required'] and not item['verified']],
            'sources':sources}
