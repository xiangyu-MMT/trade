# P03 · 美股扩展 I6 · Codex原始实现自检

- 实现提交：`9506952358ec8908e6b987e1a4fe27047aac1636`；应用版本：0.2.0。
- 记录时间：2026-09-26 12:07:49（Asia/Shanghai）；责任人：Codex。
- 上游：REQ-005 R2、A6、TASK-010～015 T1、六份D1。
- 翔宇授权原话：“通过 A6 和 TASK-010～015 T1，开始技术设计，技术设计后直接编码。”六份设计先完成并提交于8143d5f，再实现。本记录不代签实现或正式测试。

## 1. 实现范围

| 任务 | 已落地内容 | 主要实现入口 |
|---|---|---|
| TASK-010 | 市场归属、兼容旧资料、档案范围、配对版本与迁移3 | markets/config/store/knowledge/plans |
| TASK-011 | 三指数、七个美国行业代理、纽约金、NYSE＋NASDAQ聚合与历史积累、美国日历 | us_market/us_time/us_collector |
| TASK-012 | FRED及官方后备、同周三流动性、利率信用美元、GDP同比、信用盈利补充资料校验 | us_macro/us_observations/xlsx |
| TASK-013 | 同20个境内完整交易日金额筛选、固定配对/显式调整、境内ETF图与已公布净值偏离 | etf_pairing/store/server |
| TASK-014 | 美股独立MA/OBV/量价、已确认档案过滤、AI约束与引用、计划回填/复盘归属 | us_facts/engine/presentation/plans/prompts |
| TASK-015 | 双市场页面、独立日周/显示均线、历史/HTML、周期范围与本地运行 | web/app.js、web/us.js、us_report、runner、server、trade.py |

具体技术路线偏差：标准库实现时区与XLSX，不增加应用运行依赖；指数/美国ETF增加新浪后备，境内ETF增加同花顺原始成交金额后备。FRED批量带浏览器请求头失败后，核实默认urllib请求头可读取单序列，已使用该方式。Nasdaq100没有用未经核实的Stooq其他纳指代码替代。

## 2. 环境与实际命令

- macOS Big Sur / Darwin arm64；Python 3.8.9；Node v22.22.2；本机Google Chrome。
- Python运行仅标准库。浏览器主路径自检用Playwright，安装位置工作区`.scratch/p03-us-browser-I6/`，命令：`npm install --prefix .scratch/p03-us-browser-I6 --registry=https://registry.npmmirror.com --ignore-scripts playwright`；不构成应用依赖。
- 语法：`node --check projects/P03-trade/src/trade_assistant/web/app.js`、同命令检查us.js；Python内联脚本对src全部.py调用`ast.parse`。结果：正常结束。
- `git diff --check`：无输出、成功结束。
- 真实取数：`PYTHONPATH=projects/P03-trade/src python3 -u -`内联脚本调用`Engine(Settings('.scratch/p03-us-I6')).run(progress, no_ai=True, market='US')`，保存first-run.json/second-run.json。发现并修复了H.15参数、标普名称匹配与ETF成交金额后备问题。
- 隔离服务：`python3 projects/P03-trade/src/trade.py --home .scratch/p03-us-I6 serve --port 8876 --no-browser`；已停止。
- 实际服务：核实旧8765进程为本项目且active=null、auto_refresh=false后用SIGINT退出；执行`python3 projects/P03-trade/src/trade.py serve`，最终按已提交源码以`serve --no-browser`重启。当前8765提供0.2.0，定时关闭、无取数/AI任务。
- 页面真实触发：带本机会话令牌POST `/api/run`，正文`{"market":"US"}`。令牌未写入提交。
- 报告导出：`python3 projects/P03-trade/src/trade.py report --run-id 790733929b3144539565e2c054b39472 --output projects/P03-trade/outputs/codex-美股结果-I6.html`，已用Google Chrome打开。

## 3. 实际结果与证据位置

### 真实数据与AI

正式目录轮次：`790733929b3144539565e2c054b39472`；状态partial（数据缺口保留），AI error=null，Codex覆盖10/10，missing=[]。结果保存在`.local/trade.sqlite3`，源请求记录在该轮snapshot.source_attempts；AI输入/输出及trace在`.local/ai/`，均不进Git。可通过页面历史或JSON资料导出取得。

- 原指数与七行业均取得360条日线；纽约金取得真实近月序列。
- FRED：WALCL195、WDTGAL195、RRPONTSYD932、SOFR931、DGS10/DFII10各933、T10Y2Y934、HY OAS787、实际GDP34个季度点；DXY360点。同周三交集生成192个流动性参考点，GDP同比30点。
- 三指数原行情日2026-09-25；境内ETF最近交易日2026-09-24，已公布净值日2026-09-23，页面分开表达。
- 固定ETF：道琼斯sh513400；纳斯达克100 sz159941；标普500 sh513500。统一比较窗口2026-08-28～2026-09-24，共20个完整境内交易日；对识别出的候选核实跟踪目标后比较金额。筛选原始目录、逐日金额、排除原因与配对版本保存在pairing对象中。
- AI输入仅10个关注对象、7个行业摘要、全市场聚合及本市场已确认知识；未传全美个股目录或A股全部行业。

### 页面主路径

使用Playwright启动本机Google Chrome的独立临时浏览器（不读取个人浏览器资料），读取页面、切换视图、点击图表周期并截图；没有编写正式测试用例或断言。

- 隔离页面：3组指数/境内ETF；候选页13张卡（3指数＋3ETF＋7行业），软件卡切换weekly；配置页包含周期范围、固定配对、补充资料与AI入口。
- 档案切换：US显示2条已确认框架＋3条待确认模式；CN仍显示16条原有已确认档案。
- 最终提交启动后页面读回：version=0.2.0、market=US、上述正式轮次、AI coverage10/10、MA显示默认[20]、autoRefresh=false、active=null；pageerror=[]。
- A股页面仍读回轮次`97fdd97eeba74873beae7e0c834600fe`，候选22项、定时关闭。
- 原始截图：工作区`.scratch/p03-us-I6/overview.png`、`final-overview.png`，不作为正式测试证据或用户数据迁入。

### 计划、回收站与迁移主路径

在隔离目录调用Plans.manual/confirm/execution(note)，然后对说明记录移入回收站并恢复；没有实际交易。创建的计划归属US、执行场所CN、引用pair-us-NDX@1。导出archive_version=3并导入另一隔离目录，结果新增27个对象版本、3轮分析、1组AI记录、1个生命周期记录，三份配对完整，恢复后is_deleted=false。

真实Codex拟定隔离计划：`e949e9f029c544e79350474ff09dc4e5`，依据隔离轮次c2e85228112f49e182238e6757a70b13；返回draft，analysis_market=US、execution_market=CN、execution_asset_id=sz159941、pairing_ref=pair-us-NDX@1。个人风险与入场规则不足保留missing，未自动确认。该旧输入轮次尚缺OAS，因此草稿保留该轮事实的缺口；正式最新轮次已取得OAS。

A股兼容自检使用原数据库只读查询取旧快照，在内存调用compute/render/analysis_input：22候选、分析MA[5,20]、报告401356字节、前三3项、16条A股知识、analysis_market=CN。

## 4. 已知数据边界和未验证范围

1. NYSE＋NASDAQ免费目录存在证券类型未识别及无有效前收差值；当前广度日期为9月24日，未冒充9月25日完整广度。启动前完整历史未补齐，之后按真实快照积累，单点不补为连续曲线。
2. 未取得带可靠源时点的IOPV，当前展示相对已公布人民币单位净值偏离；不能当作实时公平价值溢价。固定ETF目录仍可能受名称发现覆盖限制，逐项源证据保留。
3. S&P公开盈利表、评级资料请求403，未取得稳定免费实际违约/标普500实际EPS/净利润率序列。已实现有来源的结构化补充入口及实际/预测、单位、样本、日期区分；缺口仍未自动补齐。
4. 美国行业为明确标注的美国本土ETF代理，非全部行业公司总成交量；指数OBV/量能是美国ETF自己的数据。COMEX近月连续包含提供方换月影响，具体调整规则未独立核实。
5. Windows未实机运行；未配置DeepSeek密钥，真实DeepSeek调用未执行；长时间周期运行、跨休眠、全部异常分支及正式回归交小步。没有把这些事项写成通过。

## 5. 交付状态

源码已提交，六卡进入review。按项目AGENTS.md，翔宇签收上述实现提交后，小步再进入正式用例、测试执行和独立验收。本轮没有修改tests/、05-测试用例/或小步产物。

