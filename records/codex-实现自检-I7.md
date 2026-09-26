# P03 · I7 · 市场按钮与盈利数据修复

- 实现提交：`ab3044db60e34fc7436cdc560a784427b61ab2ca`；应用版本0.2.1。
- 登记时间：2026-09-26 12:42:24（Asia/Shanghai）；Codex。
- 用户反馈原话：“分析市场的切换做成按钮；EPS和净利润率怎么没有数据？”本次按已有设计后直接编码授权处理实现反馈，未代签实现与正式验收。
- 影响：TASK-012、TASK-014、TASK-015；012/015设计补充D2，其他已实现功能继续保留。

## 根因与修复

I6盈利链路只有S&P文件下载尝试和手工补充入口；请求403后，没有自动解析可用的其他来源，所以EPS与净利润率一直缺失。此次实现真正的数据解析、来源日期和版本处理。

| 项目 | 实现 |
|---|---|
| 市场切换 | A股/美股双按钮，选中高亮、aria-pressed；点击更新URL和浏览器偏好，只读取该市场资料 |
| EPS | 从Shiller当前站发现公开xls，读取名义E列；用Date Fraction恢复月份并与Date核对，仅取季度末TTM，排除月内插值及Real Earnings |
| 净利润率 | 解析FactSet公开Earnings Insight PDF中明确的历史季度比较值；保留报告日期、页码、修订版本，当前季度预测单列 |
| 同比 | EPS同口径同比；同时修正EPS/GDP同比摘要value误继承原始水平值的问题，摘要与曲线末值一致 |
| 展示与AI | 盈利卡展示期间及简明观测表，AI接收真实EPS、同比、净利润率证据，提示词限定TTM/季度与来源差异 |
| 依赖 | xlrd2.0.2、pypdf5.9.0及兼容typing_extensions，固定于src/requirements.txt；setup或首次启动安装到.local/python-packages，不改系统Python |

主要文件：`src/trade_assistant/providers/us_earnings.py`、`providers/us_macro.py`、`dependencies.py`、`web/index.html`、`web/app.js`、`web/style.css`、`web/us.js`、`prompts/analysis.txt`、`src/trade.py`、`src/requirements.txt`和使用说明。

## 实际来源核实

- [Shiller当前站及数据定义](https://shillerdata.com/)：当前xls已有2026Q2名义EPS。旧Yale HTTP镜像实际只到2023，未采用其作为当前数据。
- [FactSet公开报告入口](https://insight.factset.com/topic/earnings/page/1)：2026-09-25报告正文区分当季预测与前季/上年同期净利润率；历史报告同样逐项校核日期与数字，失败不补零。原文PDF缓存留本地，不把完整报告送给AI。
- Multpl的EPS是通胀调整值，不直接作为名义EPS；未混用其价格基础。

## 实际自检命令与结果

1. `python3 projects/P03-trade/src/trade.py setup`：解析依赖安装完成，返回parsers=[xlrd,pypdf]、ready=true。
2. `PYTHONPATH=projects/P03-trade/src python3 -u -`内联脚本调用`USEarnings(HttpClient('.scratch/p03-earnings-I7',10,180)).collect()`：EPS42点、净利润率8点，均截至2026-06-30；原始结果为`.scratch/p03-earnings-I7/earnings.json`。
3. 同入口调用`USMacro(...).collect([])`：EPS295.3881、TTM EPS同比32.74079899339415%、净利润率17.0%；GDP同比2.097671547016011%，各项摘要value与rows末值相同。完整结果在`.scratch/p03-earnings-I7/macro.json`。
4. `node --check`检查app.js/us.js；Python AST加载src模块；均正常结束。`git diff --check`修正文档末尾空行后无异常。
5. Chrome主路径：点击A股和美股按钮，两次aria-pressed=true与state.analysis_market对应，URL同步CN/US，pageerror=[]。浏览器使用隔离临时资料，不读取个人浏览器数据。
6. 旧服务确认active=null、auto_refresh=false后SIGINT退出，以`python3 projects/P03-trade/src/trade.py serve --no-browser`启动新版，再真实POST `/api/run`、market=US。
7. 新轮次`409044ff9ba4449c8d3c9e3b843bf0e9`：Codex实际覆盖10/10、missing=[]、error=null；市场解读引用了`macro:SP500_EPS`、`macro:SP500_EPS_YOY`、`macro:SP500_NET_MARGIN`。
8. 最终Chrome页面显示0.2.1，长期观察区4张真实曲线（EPS、EPS同比、净利润率、GDP同比），EPS295.39、同比32.74%、净利润率17%，日期和口径单列，pageerror=[]。截图`.scratch/p03-earnings-I7/final-earnings.png`已检查。

应用数据证据留在该轮`.local/trade.sqlite3`和`.local/ai/`，可通过页面历史与资料导出查看。旧I6轮次保留原缺口，不覆盖成新结果。

## 边界与交接

- EPS为名义TTM，净利润率为FactSet单季度发布口径，不能直接用二者反推收入。
- FactSet三季度2026预估15%留在forecasts，未并入已发布历史曲线；提供方后续修订保留vintages。
- Shiller不逐季提供发布日期，保留null；抓取时间不会充当发布日期。
- 实际违约、可靠IOPV、广度覆盖/历史的原有限制仍保留，所以完整轮次仍为partial。
- 本轮是实现自检，未修改或执行正式tests/、测试用例或小步验收。Windows未实机运行。
- 新提交进入review，待翔宇签收后按项目AGENTS.md交小步正式测试。
