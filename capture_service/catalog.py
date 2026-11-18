"""按门店目录组织采集结果：当前报价、历史版本与来源页。"""
import re
from .ledger import entities
from .progress import initialize, page_rows, card_pages


def _version_key(version):
    """自然排序版本号：v2 晚于 v1，v10 晚于 v9。"""
    parts = re.split(r'(\d+)', str(version))
    return tuple(int(part) if part.isdigit() else part for part in parts)


def _store_status(connection, collection):
    """按已保存页面判断每个门店目录是否收齐，未收齐绝不显示为已完成。"""
    initialize(connection)
    expected = connection.execute(
        'SELECT scope,card_kind,required FROM portal_sources WHERE collection=? ORDER BY scope',
        (collection,)).fetchall()
    pages = page_rows(connection, collection)
    by_scope = {}
    for row in pages:
        by_scope.setdefault(row['scope'], []).append(row)
    stores = []
    for scope, kind, required in expected:
        scope_pages = sorted(by_scope.get(scope, []), key=lambda r: r['page_no'])
        saved_nos = [row['page_no'] for row in scope_pages]
        page_count = scope_pages[-1]['page_count'] if scope_pages else None
        complete = (
            bool(scope_pages)
            and page_count is not None
            and len(saved_nos) == page_count
            and saved_nos == list(range(1, page_count + 1))
        )
        stores.append({
            'scope': scope,
            'card_kind': kind,
            'required': bool(required),
            'saved_pages': saved_nos,
            'page_count': page_count,
            'complete': complete,
            'missing_pages': ([] if complete else
                             [n for n in range(1, (page_count or 0) + 1) if n not in saved_nos]),
        })
    return stores


def catalog(connection, collection):
    """生成带门店、规格、促销版本、来源页与历史依据的报价目录。"""
    initialize(connection)
    provenance = {(row['entity_type'], row['entity_id'], row['entity_version']): row
                  for row in card_pages(connection, collection)}
    page_index = {(row['scope'], row['page_no']): row for row in page_rows(connection, collection)}

    offers = {}
    for entity in entities(connection, collection):
        if entity['type'] != 'product_card':
            continue
        payload = entity['payload']
        store_id = payload['store_id']
        key = (store_id, entity['id'])
        origin = provenance.get((entity['type'], entity['id'], entity['version']))
        if origin is None:
            source_page = None
        else:
            page = page_index.get((origin['scope'], origin['page_no']), {})
            source_page = {
                'scope': origin['scope'],
                'page_no': origin['page_no'],
                'page_token': page.get('page_token'),
                'source_url': page.get('source_url'),
                'receipt_sha256': origin['receipt_sha256'],
            }
        entry = {
            'offer_id': entity['id'],
            'store_id': store_id,
            'sku': payload['sku'],
            'version': entity['version'],
            'price_cny': payload['price_cny'],
            'valid_from': payload.get('valid_from'),
            'valid_to': payload.get('valid_to'),
            'source_page': source_page,
        }
        offers.setdefault(key, []).append(entry)

    items = []
    for (store_id, offer_id), versions in offers.items():
        versions.sort(key=lambda e: (_version_key(e['version']), e.get('valid_from') or ''))
        current = versions[-1]
        items.append({
            'offer_id': offer_id,
            'store_id': store_id,
            'sku': current['sku'],
            'current_version': current['version'],
            'current_price_cny': current['price_cny'],
            'current_valid_from': current['valid_from'],
            'current_valid_to': current['valid_to'],
            'current_source_page': current['source_page'],
            'history': versions,
        })
    items.sort(key=lambda item: (item['store_id'], item['offer_id']))

    stores = _store_status(connection, collection)
    incomplete_required = [s['scope'] for s in stores
                           if s['required'] and not s['complete']]
    return {
        'collection': collection,
        'stores': stores,
        'catalog_complete': not incomplete_required,
        'incomplete_required_scopes': incomplete_required,
        'current_quotes': [
            {k: item[k] for k in ('offer_id', 'store_id', 'sku',
                                  'current_version', 'current_price_cny',
                                  'current_valid_from', 'current_valid_to',
                                  'current_source_page')}
            for item in items
        ],
        'offers': items,
    }
