# 零售猪肉页面改版后的在售价格采集

现有项目保存零售门店与商品页面的冻结来源响应。transport 核对请求和原文字节，domain 提取来源声明的资料身份，ledger 原子保存版本，view 展示已收资料及待核状态。portal_workflow 会把门户默认门店的稳定卡片写入账本，并在 portal_progress 中保存可重进的采集收据，portal-sources.json 登记待采门店与卡片类别；`collect_catalog` 接续完成切换后各门店的全部分页采集：只在 `phase=loaded` 且 `scope=card_scope` 的稳定态入帐（过渡卡片被丢弃），逐卡核对 `store_id` 与页面范围一致；`portal_pages`/`portal_page_cards` 保存页级进度与卡片→来源页映射，中断重开后从首个缺失页接续，同一页面重复接收幂等不重复累加，同页原文变化则拒绝覆盖以保留来源依据。catalog 视图按门店输出当前报价（同 offer 多版本取自然序最新版）、被替代价格的历史依据，以及每项价格的门店、商品规格（sku）、促销版本、来源页与收据哈希；必需门店目录未收齐时 `catalog_complete=false`，archive 发布闸门拒绝发布。合成样例不访问外部站点，双来源初版资料已可按当前字段核对并判断发布；后续更正、撤回与范围变化尚待接续。来源字段见 docs/source-contract.md。

在项目根目录运行：

    python -m unittest discover -s tests -v
    python -m compileall -q capture_service tests
    python -m capture_service.cli inspect data/normal.json

本地页面演练：python -m capture_service.browser_capture data/portal.html。

全量门店分页采集（SQLite 持久化，可中断接续；`--max-pages N` 模拟采集中断）：

    python -m capture_service.cli collect-catalog data/portal.html --db state.sqlite3
    python -m capture_service.cli catalog-view --db state.sqlite3

容器运行：docker build -t pork-collection-004 .；docker run --rm pork-collection-004。

