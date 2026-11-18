# 零售门店与商品页面来源约定

`portal.html` 是离线门店目录演练页。每个页面状态含 `scope`、`card_scope`、`phase`、`page`、`page_count`、`page_token` 和本页 `cards`；切换期间 `scope` 会先更新，上一门店的卡片仍留在页面，直到状态变为 `loaded` 且两种门店范围一致。南方门店第二页会再次列出 `offer-s-1`，其版本与价格已更新，不能把它计作另一项商品或丢掉较新的报价。`normal.json` 和 `conflict.json` 仍用于账本身份冲突的基线测试。kind、id 和 revision 是来源声明，不能单独证明跨来源业务归属。
