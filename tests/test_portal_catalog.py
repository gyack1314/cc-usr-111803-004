"""多门店分页采集：稳定过滤、跨页修订、中断接续与去重。"""
import json
import tempfile
import unittest
from pathlib import Path
from capture_service.ledger import connect
from capture_service.portal_workflow import collect_catalog
from capture_service.catalog import catalog
from capture_service.archive import release_verified

ROOT = Path(__file__).resolve().parents[1]
PORTAL = ROOT / 'data' / 'portal.html'
COLLECTION = 'pork-004'


class PortalCatalog(unittest.TestCase):
    def test_full_run_covers_both_stores_with_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / 'capture.sqlite3')
            result = collect_catalog(db, COLLECTION, PORTAL)

            # 北方 1 页 + 南方 2 页，共 3 个稳定页面
            self.assertEqual([(s['scope'], s['saved_pages']) for s in result['catalog']['stores']],
                             [('北方门店', [1]), ('南方门店', [1, 2])])
            self.assertTrue(result['catalog']['catalog_complete'])
            self.assertEqual(result['catalog']['incomplete_required_scopes'], [])

            # 5 张卡片，其中 offer-s-1 有两个版本，但只对应一项促销商品
            entities = result['records']
            self.assertEqual(len(entities), 5)
            self.assertEqual(sum(1 for r in entities if r['id'] == 'offer-s-1'), 2)

            quote_by_offer = {q['offer_id']: q for q in result['catalog']['current_quotes']}
            self.assertEqual(len(quote_by_offer), 4)

            south_pork = quote_by_offer[('offer-s-1')]
            self.assertEqual(south_pork['store_id'], '南方门店')
            self.assertEqual(south_pork['sku'], 'pork-500g')
            self.assertEqual(south_pork['current_version'], 'v2')
            self.assertEqual(south_pork['current_price_cny'], 14.9)
            # 当前报价可追溯到第二页来源
            self.assertEqual(south_pork['current_source_page']['scope'], '南方门店')
            self.assertEqual(south_pork['current_source_page']['page_no'], 2)
            self.assertTrue(south_pork['current_source_page']['receipt_sha256'])
            db.close()

    def test_cross_page_revision_keeps_history_and_uses_latest_quote(self):
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / 'capture.sqlite3')
            collect_catalog(db, COLLECTION, PORTAL)
            view = catalog(db, COLLECTION)

            offer = next(item for item in view['offers'] if item['offer_id'] == 'offer-s-1')
            self.assertEqual(len(offer['history']), 2)
            self.assertEqual([h['version'] for h in offer['history']], ['v1', 'v2'])
            self.assertEqual([h['price_cny'] for h in offer['history']], [15.1, 14.9])
            self.assertEqual(offer['current_version'], 'v2')
            self.assertEqual(offer['current_price_cny'], 14.9)
            # 被替代价格的历史依据仍保留在第一页来源上
            self.assertEqual(offer['history'][0]['source_page']['page_no'], 1)
            self.assertEqual(offer['history'][1]['source_page']['page_no'], 2)
            # 每条历史都指向账本中存在的收据
            hashes = {row[0] for row in
                      db.execute('SELECT receipt_sha256 FROM entities')}
            for h in offer['history']:
                self.assertIn(h['source_page']['receipt_sha256'], hashes)
            db.close()

    def test_interrupted_catalog_is_not_shown_complete_and_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'capture.sqlite3'
            db = connect(path)
            partial = collect_catalog(db, COLLECTION, PORTAL, max_pages=2)
            # 只处理了北方第 1 页与南方第 1 页
            self.assertFalse(partial['catalog']['catalog_complete'])
            self.assertEqual(partial['catalog']['incomplete_required_scopes'], ['南方门店'])
            south = next(s for s in partial['catalog']['stores'] if s['scope'] == '南方门店')
            self.assertEqual(south['saved_pages'], [1])
            self.assertEqual(south['missing_pages'], [2])
            self.assertEqual(len(partial['records']), 3)  # 北方1卡 + 南方2卡
            db.close()

            # 重开数据库接续：从南方第 2 页补齐，已有页面不重复累加
            db = connect(path)
            resumed = collect_catalog(db, COLLECTION, PORTAL)
            self.assertTrue(resumed['catalog']['catalog_complete'])
            self.assertEqual(len(resumed['records']), 5)
            self.assertEqual([(s['scope'], s['saved_pages'])
                              for s in resumed['catalog']['stores']],
                             [('北方门店', [1]), ('南方门店', [1, 2])])
            db.close()

    def test_rerun_same_pages_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / 'capture.sqlite3')
            first = collect_catalog(db, COLLECTION, PORTAL)
            second = collect_catalog(db, COLLECTION, PORTAL)
            self.assertEqual(len(first['records']), len(second['records']))
            self.assertEqual(first['portal_progress'], second['portal_progress'])
            # 页级映射也不重复
            mapping_count = db.execute(
                'SELECT COUNT(*) FROM portal_page_cards WHERE collection=?',
                (COLLECTION,)).fetchone()[0]
            self.assertEqual(mapping_count, 5)
            page_count = db.execute(
                'SELECT COUNT(*) FROM portal_pages WHERE collection=?',
                (COLLECTION,)).fetchone()[0]
            self.assertEqual(page_count, 3)
            db.close()

    def test_release_blocked_until_catalog_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / 'capture.sqlite3')
            collect_catalog(db, COLLECTION, PORTAL, max_pages=1)
            with self.assertRaises(ValueError):
                release_verified(db, COLLECTION)
            collect_catalog(db, COLLECTION, PORTAL)
            # 目录收齐但仍缺 store_page 双来源核实，发布继续被拦
            with self.assertRaises(ValueError):
                release_verified(db, COLLECTION)
            db.close()

    def test_no_transition_cards_are_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / 'capture.sqlite3')
            collect_catalog(db, COLLECTION, PORTAL)
            # 全部已保存卡片的门店归属与来源页门店一致
            rows = db.execute(
                'SELECT pc.scope, e.payload_json FROM portal_page_cards pc '
                'JOIN entities e ON e.collection=pc.collection '
                'AND e.entity_type=pc.entity_type AND e.entity_id=pc.entity_id '
                'AND e.version=pc.entity_version WHERE pc.collection=?',
                (COLLECTION,)).fetchall()
            self.assertEqual(len(rows), 5)
            for scope, payload_json in rows:
                payload = json.loads(payload_json)
                self.assertEqual(payload['store_id'], scope)
            db.close()


if __name__ == '__main__':
    unittest.main()
