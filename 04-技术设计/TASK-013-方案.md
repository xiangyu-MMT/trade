# TASK-013 · 境内美股指数ETF固定配对与溢价 · 技术设计 D1

- 项目：P03-trade；依据：REQ-005 R2、分析A6、TASK-013 T1。
- 档位：独立完整方案；作者：Codex；形成时间：2026-09-26 11:11:47（Asia/Shanghai）。
- 授权：翔宇明确回复“通过 A6 和 TASK-010～015 T1，开始技术设计，技术设计后直接编码。”本轮按此连续完成设计与实现；该回复为阶段推进授权，不伪记为对随后形成D1内容的事前审阅签字。
- 边界：人工交易、免费行情、七个美国行业、三指数境内ETF配对；正式测试与验收由小步负责。

## 1. 目标与取舍

实现当前任务卡全部范围，复用本地Python/SQLite/原生HTML栈；共用基础协议先确定，再顺序接入数据、事实、AI及页面。不接券商下单接口。

## 2. 详细方案

### 选择与存档
新增 etf_pairing.py；全基金目录筛出境内场内ETF（剔除联接/LOF/非对应目标），结合基金概况“跟踪标的”校验三指数身份。名称模糊匹配只用于发现，不足以完成绑定。
首次对每指数全部已发现且已核实的合格品种，用同一最近20个完整境内交易日的日成交金额计算均值。取数使用东方财富原始成交金额或同口径免费后备；不以volume×close估计成交额。缺历史/停牌/未核实身份的品种保留排除理由；若可能影响最大者判断则不自动宣称全范围最大。
成功后作为pairing版本对象记录：index_id、ETF code/name、analysis_market US、execution_market CN、20日窗口、逐品种金额与覆盖、选定时间与source、policy。日常只读取绑定；只有显式API“重新选择/指定确认”才产生新版本。旧轮次和计划保存pairing_ref。
### 行情与溢价
ETF日线/报价用现有境内适配器，行情日期按CN。净值优先可核实IOPV及其源时间；否则已公布单位净值（人民币），明确“相对已公布净值偏离”并显示净值日、报价日及跨市场时差。premium_pct=(CNYprice/CNYbasis−1)*100。无基准/非正数/币种不一致/未知时点返回null与原因，不填0。
不把美元指数点位与人民币基金净值直接相除；不以涨跌幅粗算实时公平价值。该轮ETF量价、溢价事实与指数技术分开，AI能说明方向强但工具溢价不利。阈值只由已确认知识给出，初期不自设止买线。
### API与界面
GET /api/us/pairings读取当前及历史；POST /api/us/pairings/preview取得可审阅筛选证据；POST /api/us/pairings/bind带预览/目标版本明确确认后绑定。首轮自动择优只在空绑定且筛选完整时执行。使用共同操作锁；JSON迁移保留版本和引用。七行业不进入该接口。

## 3. 溯源与风险

官方资料：NYSE日历 https://www.nyse.com/trade/hours-calendars ；Nasdaq证券目录说明 https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs ；软件代理定义 https://www.ssga.com/us/en/institutional/etfs/state-street-spdr-sp-software-services-etf-xsw ；FRED序列定义 https://fred.stlouisfed.org/series/WALCL 、https://fred.stlouisfed.org/series/WDTGAL 、https://fred.stlouisfed.org/series/RRPONTSYD 。

本轮已实际读取Yahoo纳指100历史、Nasdaq全市场目录和境内基金目录；FRED下载超时、S&P盈利表403。来源会变化，适配器须验证数据结构、时点与身份，成功/失败留coverage，不以网页存在推定API稳定。

## 4. 实现与验证责任

实现按本方案接口分步落地，保持旧资料可读。Codex做语法加载、启动、真实取数和主路径调用自检，记录实际命令/结果/限制；不编写或执行正式测试。小步在实现获签后依据任务卡设计正式覆盖。

## 5. 变更与交付

影响现有文件与新增模块按上文记录；不删除旧文件/历史数据，无新云服务或订阅。设计与实现存在偏差时在任务卡完成说明登记，旧方案保留。实现单独提交后再记录提交哈希。


## 6. I6实现落实记录

2026-09-26 12:14:22（Asia/Shanghai）：本方案落实于9506952358ec8908e6b987e1a4fe27047aac1636。20日成交金额筛选、固定配对、显式换码、净值偏离及跨市场日期。限制：IOPV可靠时点未取得，当前是相对已公布净值偏离；目录发现覆盖限制保留。事实见[原始自检](../records/codex-实现自检-I6.md)。实现签收与正式测试尚待后续阶段，不代签。
