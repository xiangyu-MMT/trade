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
## D3 · I8：历史曲线、实际违约与长期跨度

- 本轮依据：翔宇“NYSE＋NASDAQ 涨跌家数 不是曲线啊；中期 · 利率、美元与信用这种默认别折叠，我每次看还要手动打开；美国企业债实际违约没数据；长期 · 盈利与经济增长这种长期数据，起码要看5年以上的吧。”
- 已确认取舍：“先用无需登录的数据”。沿用本轮连续设计/实现授权处理反馈；不代签实现或测试。

### 数据与口径

1. 新增MarketParquet匿名近7天全美股票日线源，已核实2026-09-21～25文件可读取，每日约6500行。通过Nasdaq Trader当前NYSE/NASDAQ证券目录校验普通股/ADR，用相邻完整交易日收盘价比较逐日计算涨/跌/平/缺值；仅程序聚合，AI不接收全股明细。首个文件没有窗口内前收，因此目前合计曲线是9月22～25的4个点；后续自动积累。历史按当前目录重建，明确目录时点和可能的存续偏差，不冒称历史时点完整证券目录，不与原Nasdaq快照口径拼接。401表示超出匿名范围，正常停止该日期，不绕过登录。
2. Nasdaq官方年度统计CSV可作为补充资料/质量核对；不能以Nasdaq独自冒充两市场合计。
3. Fitch公开网站使用只读GraphQL getResearchItem；从LSTA合作栏目发现美国企业违约评论，读取公开Non-Rating Action Commentary，检查非Premium。字段仅title/发布日期/正文段落/访问类别；不请求账号、联系人或付费全文。只抽取明确HY/High Yield债券TTM实际率，贷款、私募信用、CLO和预测区间不代替。当前已核实2026-07实际2.8%、前月2.7%，其余月份按可解析来源补充。保留观测月、发布日期、样本与修订；标题明确美国高收益企业债。
4. 净利润率采集从5份季度末周报扩至约25份，兼容旧文中的record-high等措辞。目标取得至少5年以上真实历史；EPS及GDP本已有更长跨度，图表统一显示实际起止时间与覆盖年数，缺季度断线，不插值。完整资料保存在快照，AI只收最近摘要及跨度，避免把全文/重复历史版本塞入输入。

### 依赖与实现

Parquet使用Node22的纯JS hyparquet1.31.1及hyparquet-compressors1.1.2，安装到.local/parquet-runtime/，由受限本地worker解码（限制文件/行数/列），不依赖外部CDN。试用的PyArrow在本机Big Sur无法加载，DuckDB本地编译已停止，二者不进入生产依赖。Fitch需要现代TLS，使用curl_cffi0.7.4；证书验证保持开启，延续网络超时/预算与缓存。启动/setup补齐依赖，Windows仍需实机验证。

新增providers/us_breadth.py、providers/us_credit.py、parquet_worker.mjs及runtime包清单；调整依赖加载、HTTP客户端、US收集/事实、曲线和页面。中期/长期details默认open；年份跨度来自实际有效观测，不虚填日期。来源失败保留最后可用缓存及真实日期，旧轮次不改写。

### 交付边界与自检

Codex做真实文件/公开接口/页面主路径自检并保存证据，正式测试仍交小步。匿名广度不能承诺一年历史；用户已选择无需登录路径。信用指标是高收益企业债样本，不能称所有美国企业债；发布日期滞后明确展示。

来源：Nasdaq目录与年度统计 https://nasdaqtrader.com/Trader.aspx?id=DailyMarketFiles ；MarketParquet免费范围 https://marketparquet.com/guides/free-historical-stock-data ；LSTA/Fitch公开评论入口 https://www.lsta.org/content/fitch-ratings-commentary-page/ 。
