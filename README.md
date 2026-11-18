# 零售猪肉页面改版后的在售价格采集

现有项目保存零售门店与商品页面的冻结来源响应。transport 核对请求和原文字节，domain 提取来源声明的资料身份，ledger 原子保存版本，view 展示已收资料及待核状态。portal_workflow 会把门户默认门店的稳定卡片写入账本，并在 portal_progress 中保存可重进的采集收据，portal-sources.json 登记待采门店与卡片类别；切换后的门店仍需业务采集逻辑接续。合成样例不访问外部站点，跨来源业务归属尚未形成。来源字段见 docs/source-contract.md。

在项目根目录运行：

    python -m unittest discover -s tests -v
    python -m compileall -q capture_service tests
    python -m capture_service.cli inspect data/normal.json

本地页面演练：python -m capture_service.browser_capture data/portal.html。

容器运行：docker build -t pork-collection-004 .；docker run --rm pork-collection-004。

