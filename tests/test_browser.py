"""本地页面状态转换可重复，不依赖外站。"""
import json
import unittest
from pathlib import Path
from capture_service.browser_capture import inspect

class BrowserFixture(unittest.TestCase):
    def test_transition(self):
        states = inspect(Path(__file__).resolve().parents[1] / 'data' / 'portal.html')
        self.assertEqual([row['phase'] for row in states], ['loaded', 'pending', 'loaded'])
        self.assertNotEqual(states[0]['scope'], states[-1]['scope'])
        self.assertEqual(states[0]['card_scope'], states[1]['card_scope'])
        self.assertEqual(states[-1]['scope'], states[-1]['card_scope'])

    def test_store_pages_keep_their_scope_and_expose_a_revision(self):
        from playwright.sync_api import sync_playwright

        path = Path(__file__).resolve().parents[1] / 'data' / 'portal.html'
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(path.resolve().as_uri())
            page.get_by_role('button', name='切换门店').click()
            page.wait_for_function("JSON.parse(document.querySelector('#state').textContent).phase === 'loaded'")
            first = json.loads(page.locator('#state').inner_text())
            page.get_by_role('button', name='下一页').click()
            page.wait_for_function("JSON.parse(document.querySelector('#state').textContent).phase === 'loaded'")
            second = json.loads(page.locator('#state').inner_text())
            browser.close()

        self.assertEqual(first['page_token'], 'south:2')
        self.assertEqual(first['cards'][0]['revision'], 'v1')
        self.assertEqual(second['scope'], '南方门店')
        self.assertEqual(second['card_scope'], '南方门店')
        self.assertEqual(second['cards'][0]['revision'], 'v2')
        self.assertEqual(second['cards'][0]['price_cny'], 14.9)
