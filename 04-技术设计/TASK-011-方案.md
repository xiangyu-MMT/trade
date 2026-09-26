# TASK-011 · 美股行情行业与全市场广度 · 技术设计 D1

- 项目：P03-trade；依据：REQ-005 R2、分析A6、TASK-011 T1。
- 档位：独立完整方案；作者：Codex；形成时间：2026-09-26 11:11:47（Asia/Shanghai）。
- 授权：翔宇明确回复“通过 A6 和 TASK-010～015 T1，开始技术设计，技术设计后直接编码。”本轮按此连续完成设计与实现；该回复为阶段推进授权，不伪记为对随后形成D1内容的事前审阅签字。
- 边界：人工交易、免费行情、七个美国行业、三指数境内ETF配对；正式测试与验收由小步负责。

## 1. 目标与取舍

实现当前任务卡全部范围，复用本地Python/SQLite/原生HTML栈；共用基础协议先确定，再顺序接入数据、事实、AI及页面。不接券商下单接口。

## 2. 详细方案

### 数据源与身份
新增 providers/us_market.py、us_time.py、us_collector.py。三指数固定身份 us:DJI→^DJI、us:NDX→^NDX、us:SPX→^GSPC。Yahoo chart 主源，另一chart域名及Stooq日线作为可识别的后备；失败保留真实缓存和来源，不拼接复权体系。
七行业选美国本土ETF观察代理 XLF/XLV/XLP/XLY/SOXX/XSW/XLI，注明其跟踪范围（部分覆盖大型股或含美国上市海外企业）；软件XSW涵盖软件与IT服务而非整个科技板块。默认仅这七项。官方身份链接随配置保存。
指数原始成交量定义不明时不用于OBV；DIA/QQQ/SPY分别作为美国量能参考。代理用自己的价格/量计算量价与OBV，不用境内ETF，也不伪造指数原生成交量。图表量柱注明代理。
纽约金GC=F保留Yahoo近月连续观察身份、期货币种及换月影响；不称现货、不保证已后复权连续合约。未核实换月算法明确写入限制。
### 广度
Nasdaq公开screener按nyse、nasdaq分别完整抓取，逐条仅在程序中聚合，引用目录与前收差值字段；普通股/ADR、基金/优先股/权证边界通过Nasdaq证券目录和名称分类校验。无法严格识别则保留源实际范围及未识别数量，完整股票范围不作虚假保证。WSJ公开Market Diary为后备，NYSE与Nasdaq单独取数，保留包含的其他证券说明。不同scope_id不拼接为一条同口径线。
历史优先尝试公开日记历史；没有完整免费历史则从真实快照按交易日期积累，盘中点标形成中；单点显示点，不补零或捏造历史。支持有出处的历史导入。
### 时间与格式
美国东部时间按DST处理；内置2026–2028官方休市/13点早收日，其他年度标未核实；日线日期取交易所本地日期，source_asof/fetched_at分开。周线按美国交易周聚合，未完成周标记；COMEX按提供方会话日期、形成状态保守处理，不套用A股15点。
history={bars,source,sources,asof,currency,timezone,volume_unit,adjustment,identity,cache_stale}；breadth={scope_id,asof,rows,coverage,definition}。单源限时、总预算、并发4，取消和错误保留。

## 3. 溯源与风险

官方资料：NYSE日历 https://www.nyse.com/trade/hours-calendars ；Nasdaq证券目录说明 https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs ；软件代理定义 https://www.ssga.com/us/en/institutional/etfs/state-street-spdr-sp-software-services-etf-xsw ；FRED序列定义 https://fred.stlouisfed.org/series/WALCL 、https://fred.stlouisfed.org/series/WDTGAL 、https://fred.stlouisfed.org/series/RRPONTSYD 。

本轮已实际读取Yahoo纳指100历史、Nasdaq全市场目录和境内基金目录；FRED下载超时、S&P盈利表403。来源会变化，适配器须验证数据结构、时点与身份，成功/失败留coverage，不以网页存在推定API稳定。

## 4. 实现与验证责任

实现按本方案接口分步落地，保持旧资料可读。Codex做语法加载、启动、真实取数和主路径调用自检，记录实际命令/结果/限制；不编写或执行正式测试。小步在实现获签后依据任务卡设计正式覆盖。

## 5. 变更与交付

影响现有文件与新增模块按上文记录；不删除旧文件/历史数据，无新云服务或订阅。设计与实现存在偏差时在任务卡完成说明登记，旧方案保留。实现单独提交后再记录提交哈希。


## 6. I6实现落实记录

2026-09-26 12:14:22（Asia/Shanghai）：本方案落实于9506952358ec8908e6b987e1a4fe27047aac1636。三指数、七美国行业代理、纽约金、全市场广度及美国时区日周。限制：广度有未识别/缺报价，启动前完整历史未取得；纽约金换月规则未独立核实。事实见[原始自检](../records/codex-实现自检-I6.md)。实现签收与正式测试尚待后续阶段，不代签。
