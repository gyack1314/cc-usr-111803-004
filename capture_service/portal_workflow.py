"""将门户稳定范围接入现有来源账本，支持多门店分页与中断接续。"""
import hashlib
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from .ledger import receive
from .progress import (record, receipts, register, coverage,
                       saved_page, save_page, canonical_envelope)
from .view import overview
from .catalog import catalog

_STABLE_JS = ("(s => s.phase === 'loaded' && s.scope === s.card_scope)"
              "(JSON.parse(document.querySelector('#state').textContent))")


def _wait_stable(page, expected_scope=None):
    """等待门店范围与卡片范围一致的稳定状态，过渡卡片绝不入帐。"""
    page.wait_for_function(_STABLE_JS)
    state = json.loads(page.locator('#state').inner_text())
    if expected_scope is not None and state['scope'] != expected_scope:
        raise ValueError(f'页面范围停留在 {state["scope"]}，预期 {expected_scope}')
    return state


def _validate_state(state):
    """稳定态仍需逐卡核对来源声明的门店归属。"""
    if state['phase'] != 'loaded' or state['scope'] != state['card_scope']:
        raise ValueError('页面卡片与当前范围不一致')
    if not isinstance(state.get('cards'), list) or not state['cards']:
        raise ValueError(f'{state["scope"]} 第{state.get("page")}页缺少卡片')
    for card in state['cards']:
        if card.get('kind') != 'product_card':
            raise ValueError('门户目录只接收 product_card 卡片')
        if card.get('store_id') != state['scope']:
            raise ValueError('来源卡片与页面范围不一致，疑似过渡卡片')


def _ingest_stable_page(connection, collection, state, source_url):
    """把一页稳定卡片原子写入账本与页级进度，返回 (digest, stored)。"""
    _validate_state(state)
    _, digest = canonical_envelope(state)
    prior = saved_page(connection, collection, state['scope'], state['page'])
    if prior is not None:
        if prior['body_sha256'] != digest:
            raise ValueError(
                f'{state["scope"]} 第{state["page"]}页原文发生变化，拒绝覆盖已保存来源')
        return prior['body_sha256'], False
    card_rows = []
    for card in state['cards']:
        raw = json.dumps(card, ensure_ascii=False, sort_keys=True).encode('utf-8')
        receipt = {'status': 200, 'url': source_url,
                   'body_sha256': hashlib.sha256(raw).hexdigest()}
        card_digest = receive(connection, collection, raw, receipt)
        card_rows.append((card['kind'], card['id'], card['revision'], card_digest))
        record(connection, collection, state['scope'], card_digest, source_url)
    page_digest, stored = save_page(connection, collection, state, card_rows, source_url)
    return page_digest, stored


def collect_initial(connection, collection, page_path):
    """只保存初始范围；新选择的范围仍需另行核验。"""
    expectation = json.loads((Path(page_path).parent / 'portal-sources.json').read_text(encoding='utf-8'))
    register(connection,collection,expectation['sources'])
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(Path(page_path).resolve().as_uri())
            state = json.loads(page.locator('#state').inner_text())
            if state['phase'] != 'loaded' or state['scope'] != state['card_scope']:
                raise ValueError('页面卡片与当前范围不一致')
            declared = state['card'].get('page_scope', state['card'].get('card_scope',
                       state['card'].get('session', state['card'].get('configuration',
                       state['card'].get('store_id')))))
            if declared != state['scope']:
                raise ValueError('来源卡片与页面范围不一致')
            raw = json.dumps(state['card'], ensure_ascii=False, sort_keys=True).encode('utf-8')
            receipt = {'status': 200, 'url': page.url, 'body_sha256': hashlib.sha256(raw).hexdigest()}
            digest = receive(connection, collection, raw, receipt)
            record(connection, collection, state['scope'], digest, page.url)
        finally:
            browser.close()
    result = overview(connection, collection)
    result['portal_progress'] = receipts(connection, collection)
    result['portal_coverage'] = coverage(connection, collection)
    return result


def collect_catalog(connection, collection, page_path, max_pages=None):
    """遍历演练页所有门店分页，已保存页面跳过，支持中断后接续。

    max_pages 限制本次运行处理的稳定页数量（含跳过的已存页），用于演练中断；
    重新调用时会从首个缺失页继续，重复页面不重复累加。
    """
    expectation = json.loads((Path(page_path).parent / 'portal-sources.json').read_text(encoding='utf-8'))
    register(connection, collection, expectation['sources'])
    url = Path(page_path).resolve().as_uri()
    south_scope = expectation['sources'][1]['scope']
    visited = 0

    def budget():
        """本次运行允许处理的稳定页数；已存页也计入，以模拟中断点。"""
        nonlocal visited
        if max_pages is not None and visited >= max_pages:
            return False
        visited += 1
        return True

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url)

            # 默认门店第一页（演练页初始即为稳定态，仍统一走稳定校验）
            state = _wait_stable(page)
            if not budget():
                return _catalog_result(connection, collection)
            _ingest_stable_page(connection, collection, state, page.url)

            # 切换门店：等待 scope 与 card_scope 一致，过渡卡片绝不入帐
            page.get_by_role('button', name='切换门店').click()
            state = _wait_stable(page, expected_scope=south_scope)

            while budget():
                _ingest_stable_page(connection, collection, state, page.url)
                if state['page'] >= state['page_count']:
                    break
                page.get_by_role('button', name='下一页').click()
                state = _wait_stable(page, expected_scope=state['scope'])
        finally:
            browser.close()

    return _catalog_result(connection, collection)


def _catalog_result(connection, collection):
    result = overview(connection, collection)
    result['portal_progress'] = receipts(connection, collection)
    result['portal_coverage'] = coverage(connection, collection)
    result['catalog'] = catalog(connection, collection)
    return result
