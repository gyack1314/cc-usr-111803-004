"""冻结已核实门户资料的发布视图。"""
import json
from .view import overview
from .progress import coverage
from .catalog import catalog

def initialize(connection):
    connection.execute('CREATE TABLE IF NOT EXISTS released_views(\n      collection TEXT NOT NULL,revision INTEGER NOT NULL,view_json TEXT NOT NULL,\n      PRIMARY KEY(collection,revision))')
    connection.commit()

def release_verified(connection,collection):
    """门户资料已核实、待采范围闭合且各门店目录收齐时才发布。"""
    initialize(connection)
    current=overview(connection,collection)
    frontier=coverage(connection,collection)
    catalog_view=catalog(connection,collection)
    if not current['publishable'] or not frontier['expected'] or frontier['missing_required'] or frontier['unverified_required']:
        raise ValueError('门户资料仍有待核来源')
    if not catalog_view['catalog_complete']:
        raise ValueError(
            '门店目录尚未收齐：' + '、'.join(catalog_view['incomplete_required_scopes']))
    revision=connection.execute('SELECT COALESCE(MAX(revision),0)+1 FROM released_views WHERE collection=?',(collection,)).fetchone()[0]
    with connection:
        connection.execute('INSERT INTO released_views VALUES(?,?,?)',(collection,revision,json.dumps(current,ensure_ascii=False,sort_keys=True)))
    return revision

def get(connection,collection,revision):
    initialize(connection)
    row=connection.execute('SELECT view_json FROM released_views WHERE collection=? AND revision=?',(collection,revision)).fetchone()
    if row is None:raise KeyError((collection,revision))
    return json.loads(row[0])
