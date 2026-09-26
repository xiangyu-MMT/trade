# TASK-014 · 美股档案量价事实与AI推导 · 技术设计 D1

- 项目：P03-trade；依据：REQ-005 R2、分析A6、TASK-014 T1。
- 档位：独立完整方案；作者：Codex；形成时间：2026-09-26 11:11:47（Asia/Shanghai）。
- 授权：翔宇明确回复“通过 A6 和 TASK-010～015 T1，开始技术设计，技术设计后直接编码。”本轮按此连续完成设计与实现；该回复为阶段推进授权，不伪记为对随后形成D1内容的事前审阅签字。
- 边界：人工交易、免费行情、七个美国行业、三指数境内ETF配对；正式测试与验收由小步负责。

## 1. 目标与取舍

实现当前任务卡全部范围，复用本地Python/SQLite/原生HTML栈；共用基础协议先确定，再顺序接入数据、事实、AI及页面。不接券商下单接口。

## 2. 详细方案

### 知识与参数
新增默认美股知识文件；仅用户已表达的短中长期基本面框架和MA/OBV/量价偏好存为已确认原话（注明来源），具体AI硬件、软件久期、防御等模式定义先为draft，不自动设置胜率。所有新建议携market_scope=[US]；确认版本后才进入推导。
美股技术独立模块 us_facts.py：默认MA20/60（日线窗口，用作描述不是交易阈值），OBV首值0、以自身收盘变化加减自身量，5/20完整交易日均量及同品种回报/回撤；参数可配。展示MA5/20/60/120默认20与分析分离。周线美国日历辅助，指数价格结构和美国ETF量能代理分别保存证据。
### AI输入输出
沿用AIRouter/schema，analysis_market及市场专用requirements进入输入。US分支不发送A股行业/融资/涨停/期货基差，不发送股票全目录；只三指数七行业、聚合广度、宏观摘要、配对溢价和本市场已确认档案。
通用提示词分市场约束；不把A股成交量主导解释套到美股，信用/盈利数据不足时明确冲突。排序只在有效候选集合，前三是相对强弱而非交易许可。无AI时改称技术参考排序，基于US自己的价格/OBV事实而非复用A股量能优先排序键。
继续校验对象/事实/知识引用、全集排序、重复/越界/缺逻辑的candidate。未确认模式只能文字假设或草稿提议，不能mode_refs引用。
### 计划与复盘
计划按原轮次analysis_market和pairing_ref，执行场所另记CN/US；默认观察，风险规则不足不编仓位。手工计划支持明确市场；回填与复盘继承原计划、版本和品种，跨市场不匹配拒绝/清楚标偏差。AI失败保留事实及尝试记录，Codex/DeepSeek后备不变。

## 3. 溯源与风险

官方资料：NYSE日历 https://www.nyse.com/trade/hours-calendars ；Nasdaq证券目录说明 https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs ；软件代理定义 https://www.ssga.com/us/en/institutional/etfs/state-street-spdr-sp-software-services-etf-xsw ；FRED序列定义 https://fred.stlouisfed.org/series/WALCL 、https://fred.stlouisfed.org/series/WDTGAL 、https://fred.stlouisfed.org/series/RRPONTSYD 。

本轮已实际读取Yahoo纳指100历史、Nasdaq全市场目录和境内基金目录；FRED下载超时、S&P盈利表403。来源会变化，适配器须验证数据结构、时点与身份，成功/失败留coverage，不以网页存在推定API稳定。

## 4. 实现与验证责任

实现按本方案接口分步落地，保持旧资料可读。Codex做语法加载、启动、真实取数和主路径调用自检，记录实际命令/结果/限制；不编写或执行正式测试。小步在实现获签后依据任务卡设计正式覆盖。

## 5. 变更与交付

影响现有文件与新增模块按上文记录；不删除旧文件/历史数据，无新云服务或订阅。设计与实现存在偏差时在任务卡完成说明登记，旧方案保留。实现单独提交后再记录提交哈希。

