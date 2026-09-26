# P03 · I8 · 广度历史、实际违约和长期跨度

- 实现提交：`696506bcfbfa11fd94f30ecdf718040147b231d4`；应用版本0.2.2。
- 登记：2026-09-26 18:27:59（Asia/Shanghai），Codex。
- 用户原话：“NYSE＋NASDAQ 涨跌家数 不是曲线啊；中期 · 利率、美元与信用这种默认别折叠，我每次看还要手动打开；美国企业债实际违约没数据；长期 · 盈利与经济增长这种长期数据，起码要看5年以上的吧。”
- 历史数据渠道确认：“先用无需登录的数据”。本轮按已有连续设计/实现授权处理反馈；未代签实现和正式测试。

## 根因与实现

1. 原广度只有同一天的快照；多跑几次仍是一个日期，无法形成日度曲线。现在读取匿名近7天的全美股票日线，并与当前NYSE/NASDAQ普通股/ADR目录匹配，按相邻交易日收盘比较，生成真实涨/跌/平/缺值历史。只把聚合结果交给AI。
2. 中期、长期details默认open，用户进入页面无需逐项展开。
3. 原实际违约仍是缺口提示。现在从LSTA合作栏目发现Fitch评论，调用网站同源公开只读GraphQL，验证访问类别Anonymous及美国企业信用范围，解析明确的高收益债实际TTM率；保留前月回顾及发布版本。贷款、私募信用、CLO和预测值均不替代。
4. 原净利润率只采集5份季度周报，实际只有8个季度。现在扩展至约25份，兼容旧表述，取得26个真实季度。全部长期图表显示起止时间、跨度和观测数；缺季度断线。

主要实现：`providers/us_breadth.py`、`parquet_worker.mjs`、`src/parquet-package.json`、`providers/us_credit.py`、`http_client.py`、`dependencies.py`、`providers/us_earnings.py`、`providers/us_macro.py`、`us_collector.py`、`us_facts.py`、`us_report.py`、`web/us.js`和AI提示词。

## 数据来源与范围

- [MarketParquet匿名范围说明](https://marketparquet.com/guides/free-historical-stock-data)：本次无需账户取得2026-09-21～25的5个日线文件；每个文件约6500条股票记录，原文件只留本地缓存。窗口内首日没有前收，因此当前合计曲线4个交易日。更旧日期返回401，没有绕过登录。
- [Nasdaq Trader证券目录](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs)：用于当前NYSE/NASDAQ普通股/ADR归属核对；当前目录用于历史重建，可能有分类与存续偏差，不能称历史时点完整目录。另核实官方年度文件有Nasdaq单市场家数，未拿它冒充两市场合计。
- [LSTA/Fitch公开评论入口](https://www.lsta.org/content/fitch-ratings-commentary-page/)：实际取得2026年7月17日、8月17日公开评论；信用指标明确限定Fitch美国高收益企业债市场。API只读，不使用账户或付费内容，证书验证开启。
- FactSet历史周报原文件及解析缓存：已取得连续2020Q1～2026Q2净利润率，26点，6.25年。部分目标周报缺失，但其历史季度可由其他已取得报告的回顾值核实，未填造数据。

## 环境、依赖与尝试

macOS11 / Apple Silicon、Python3.8.9、Node22.22.2、Chrome。Parquet使用纯JS hyparquet1.31.1、hyparquet-compressors1.1.2；Fitch使用curl_cffi0.7.4及cffi1.17.1提供现代TLS，Python旧LibreSSL无法访问该来源。依赖装入项目.local目录，未进入Git。

隔离尝试中，DuckDB在本机触发不合适的本地编译，已停止其安装进程树；PyArrow无法在该系统正确加载。二者没有成为生产依赖。Unicorn历史停止于2020年，Barchart拒绝请求，WSJ页面未返回有效家数，均未用作当前曲线。

## 实际自检记录

- `python3 src/trade.py setup`：Python及Node解析组件已安装。原Mac薄入口继续可用；Windows未实机验证。
- `PYTHONPATH=projects/P03-trade/src python3 -u -`内联脚本调用`USBreadth(HttpClient(...)).collect()`：取得下表；原结果在工作区`.scratch/p03-I8-run/breadth.json`。

| 美国交易日 | 上涨 | 下跌 | 目录中缺可比价格 |
|---|---:|---:|---:|
| 2026-09-22 | 2741 | 2214 | 306 |
| 2026-09-23 | 1170 | 3848 | 287 |
| 2026-09-24 | 2023 | 2941 | 282 |
| 2026-09-25 | 2610 | 2336 | 288 |

- 参与归属核对的普通股/ADR目录5425项，另有417项类型未识别；不把缺值当平盘或零家数。scope_id为`marketparquet-current-roster-common-v1`，与旧Nasdaq快照口径隔离。
- 同入口调用`USCredit(...).collect()`：2026年5/6/7月末分别2.9%、2.7%、2.8%；最新观测日7月31日、发布日期8月17日。原结果`.scratch/p03-I8-run/credit.json`，没有将文中贷款率或2.5%～3.0%预测区间当实际值。
- 调用`USEarnings(...).factset()`：26个季度，2020-03-31～2026-06-30，跨度6.2479年。结果`.scratch/p03-I8-run/margin.json`。
- `node --check`检查us.js/parquet_worker.mjs；Python AST读取src全部.py，均正常。`git diff --check`已清除文档末尾空行问题。
- 确认8765服务待命、定时关闭后SIGINT重启新版，真实POST `/api/run`、market=US。
- 新轮次`47be743a813643b4b2b1412078f2e954`：error=null，Codex覆盖10/10，missing=[]；市场解读实际引用`macro:US_DEFAULT_RATE`。完整源尝试、快照、事实与AI原记录保存在.local数据库及ai目录。
- Chrome主路径：应用0.2.2；两个面板open=true；广度1张SVG、2条曲线、8个观测点标记（4日×涨跌）；长期跨度如下；pageerror=[]。

| 长期指标 | 有效观测数 | 实际跨度 |
|---|---:|---:|
| 名义TTM EPS | 42 | 10.25年 |
| TTM EPS同比 | 38 | 9.25年 |
| 季度净利润率 | 26 | 6.25年 |
| 实际GDP同比 | 30 | 7.25年 |

截图`.scratch/p03-I8-run/breadth.png`、`longterm.png`已查看。原始数据只供本地程序计算，未进入公开仓库。

## 交付状态

源码已提交，相关任务卡进入review，正式测试仍由小步在实现获签后完成。本轮没有修改或执行正式tests/、测试用例或小步验收记录。

广度当前匿名窗口只有4个可比日，随后通过本地快照累积；实际违约仅为Fitch高收益企业债样本、当前到7月；实时IOPV等原有限制保持可见。旧轮次不改写为新结果。
