# TASK-010 · 多市场归属与配置存档基础 · 技术设计 D1

- 项目：P03-trade；依据：REQ-005 R2、分析A6、TASK-010 T1。
- 档位：独立完整方案；作者：Codex；形成时间：2026-09-26 11:11:47（Asia/Shanghai）。
- 授权：翔宇明确回复“通过 A6 和 TASK-010～015 T1，开始技术设计，技术设计后直接编码。”本轮按此连续完成设计与实现；该回复为阶段推进授权，不伪记为对随后形成D1内容的事前审阅签字。
- 边界：人工交易、免费行情、七个美国行业、三指数境内ETF配对；正式测试与验收由小步负责。

## 1. 目标与取舍

实现当前任务卡全部范围，复用本地Python/SQLite/原生HTML栈；共用基础协议先确定，再顺序接入数据、事实、AI及页面。不接券商下单接口。

## 2. 详细方案

### 结构与接口
增加 markets.py，唯一市场值为 CN、US；旧资料没有字段时解释为 CN，不重写历史对象。配置仍兼容 schema_version=1，增加 active_market、scheduled_markets、us。手动运行显式传 market，定时按 scheduled_markets 顺序运行，操作锁共用。
运行 metadata/snapshot/facts 各携带 analysis_market；新计划、执行、复盘 payload 带 analysis_market、execution_market。档案 payload.market_scope 为非空市场列表；缺省旧档案仅 CN。列表接受市场过滤，非法值拒绝。
SQLite 不改旧表和旧对象编号，固定配对作为 pairing 版本对象保存；新增版本不覆盖已有记录。导出 archive_version=3，导入兼容1/2/3，检查市场、对象引用、配对引用、运行归属冲突，失败事务回滚。
### 配置与迁移
us 独立含 indices/sectors、technical（MA20/60、OBV、5/20量能窗口）、补充观察资料入口；图表 MA 配置与此无关。新增默认配置合并不覆盖现有A股字段；AI配置全市场共用。配对存档不通过修改普通配置JSON静默改码。
### 文件与影响
markets.py、config.py、store.py、knowledge.py、plans.py、engine.py、server.py及默认配置；A股旧快照和档案继续按原算法读取。
### 错误与恢复
未知市场/跨市场引用/配对不存在返回具体400/409；选择市场仅切换视图，不改变历史。迁移保留回收站和AI原始记录，凭据继续独立保存。

## 3. 溯源与风险

官方资料：NYSE日历 https://www.nyse.com/trade/hours-calendars ；Nasdaq证券目录说明 https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs ；软件代理定义 https://www.ssga.com/us/en/institutional/etfs/state-street-spdr-sp-software-services-etf-xsw ；FRED序列定义 https://fred.stlouisfed.org/series/WALCL 、https://fred.stlouisfed.org/series/WDTGAL 、https://fred.stlouisfed.org/series/RRPONTSYD 。

本轮已实际读取Yahoo纳指100历史、Nasdaq全市场目录和境内基金目录；FRED下载超时、S&P盈利表403。来源会变化，适配器须验证数据结构、时点与身份，成功/失败留coverage，不以网页存在推定API稳定。

## 4. 实现与验证责任

实现按本方案接口分步落地，保持旧资料可读。Codex做语法加载、启动、真实取数和主路径调用自检，记录实际命令/结果/限制；不编写或执行正式测试。小步在实现获签后依据任务卡设计正式覆盖。

## 5. 变更与交付

影响现有文件与新增模块按上文记录；不删除旧文件/历史数据，无新云服务或订阅。设计与实现存在偏差时在任务卡完成说明登记，旧方案保留。实现单独提交后再记录提交哈希。

