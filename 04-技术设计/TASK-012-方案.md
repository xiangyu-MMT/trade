# TASK-012 · 美国宏观信用与盈利增长观察 · 技术设计 D1

- 项目：P03-trade；依据：REQ-005 R2、分析A6、TASK-012 T1。
- 当前修订：D2（下方保留D1与I6历史，本轮修订见末节）。
- 档位：独立完整方案；作者：Codex；形成时间：2026-09-26 11:11:47（Asia/Shanghai）。
- 授权：翔宇明确回复“通过 A6 和 TASK-010～015 T1，开始技术设计，技术设计后直接编码。”本轮按此连续完成设计与实现；该回复为阶段推进授权，不伪记为对随后形成D1内容的事前审阅签字。
- 边界：人工交易、免费行情、七个美国行业、三指数境内ETF配对；正式测试与验收由小步负责。

## 1. 目标与取舍

实现当前任务卡全部范围，复用本地Python/SQLite/原生HTML栈；共用基础协议先确定，再顺序接入数据、事实、AI及页面。不接券商下单接口。

## 2. 详细方案

### 接口与数据源
新增 providers/us_macro.py，结果统一series={symbol,name,unit,frequency,rows,date/asof,source,fetched_at,published_at,revision_note,definition,status}。FRED公共CSV优先；可用官方文本/网页近期发布、纽约联储SOFR/ON RRP、联储H.15/H.4.1及财政部实际/名义收益率作为可核对后备。数据源实际失败和替代范围写coverage。
WALCL、WDTGAL均百万美元；RRPONTSYD十亿美元。只取三者共同的周三，转十亿美元后计算 WALCL/1000 − WDTGAL/1000 − RRPONTSYD，不前填不同日期。保留分量和单位，称流动性参考，不称可投资现金。
SOFR、T10Y2Y、DFII10、DGS10及DXY各自成序列；DXY来自美元指数报价，不用广义贸易加权美元替换。HY OAS百分数及基点说明，独立于实际违约。
### 盈利与违约
尝试S&P官方盈利表及公开评级资料。解析须能识别已实际/预测、样本和期间；不能稳定解析不从新闻片段猜数。补充资料入口支持带来源、发布日期、观测日、地区、样本、实际/预测、版本说明的结构化观察；按日期和发布版本保存，不覆盖历史快照。开放式URL只接收公开HTTPS、无凭据的数据。
EPS以标普500已报告EPS为起点，可复算同比（季度同比或明确TTM同比）；利润率保持净利润率/经营利润率区分，不更名。实际违约必须注明发行人/债券/贷款、地区及期间；信用利差、预测、全球范围不能冒称美国企业债实际违约。
GDPC1为实际GDP季度水平；同季度上年同比=(本期/上年同期−1)*100，缺任一季度不计算。FRED当前版本不是历史实时可得版本，标修订事实，不承诺无前视回测。
### 缺口行为
无法免费取得的目标保留缺口、尝试源、补充入口和对AI判断限制；未知发布日期为null，禁止以抓取日冒充发布日。图表不补零、不把低频值称实时。AI只收最近摘要和有限历史。

## 3. 溯源与风险

官方资料：NYSE日历 https://www.nyse.com/trade/hours-calendars ；Nasdaq证券目录说明 https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs ；软件代理定义 https://www.ssga.com/us/en/institutional/etfs/state-street-spdr-sp-software-services-etf-xsw ；FRED序列定义 https://fred.stlouisfed.org/series/WALCL 、https://fred.stlouisfed.org/series/WDTGAL 、https://fred.stlouisfed.org/series/RRPONTSYD 。

本轮已实际读取Yahoo纳指100历史、Nasdaq全市场目录和境内基金目录；FRED下载超时、S&P盈利表403。来源会变化，适配器须验证数据结构、时点与身份，成功/失败留coverage，不以网页存在推定API稳定。

## 4. 实现与验证责任

实现按本方案接口分步落地，保持旧资料可读。Codex做语法加载、启动、真实取数和主路径调用自检，记录实际命令/结果/限制；不编写或执行正式测试。小步在实现获签后依据任务卡设计正式覆盖。

## 5. 变更与交付

影响现有文件与新增模块按上文记录；不删除旧文件/历史数据，无新云服务或订阅。设计与实现存在偏差时在任务卡完成说明登记，旧方案保留。实现单独提交后再记录提交哈希。


## 6. I6实现落实记录

2026-09-26 12:14:22（Asia/Shanghai）：本方案落实于9506952358ec8908e6b987e1a4fe27047aac1636。宏观官方源及后备、同周三流动性、GDP/EPS同比、信用盈利补充入口。限制：实际违约、标普500实际EPS及净利润率自动序列仍缺，已列公开源403与有出处补充入口。事实见[原始自检](../records/codex-实现自检-I6.md)。实现签收与正式测试尚待后续阶段，不代签。


## D2 · I7修订：自动盈利数据与按钮切换

- 登记时间：2026-09-26 12:29:32（Asia/Shanghai）；依据：翔宇“分析市场的切换做成按钮；EPS和净利润率怎么没有数据？”以及本轮既有设计后直接编码授权。本次处理I6交付反馈，未代签新实现。
- 影响：TASK-012、TASK-015及其共同数据展示；原需求范围不扩大。正式测试仍交小步。
- 已核实根因：I6盈利链路只尝试下载后声明缺失，未解析有效源。S&P工作簿403；旧Yale镜像停在2023年；Shiller当前站动态下载的xls已含2026Q2的名义TTM EPS；FactSet免费Earnings Insight PDF正文包含季度净利润率及历史季度比较值。

### 数据与算法

新增providers/us_earnings.py。EPS从https://shillerdata.com/发现其当前ie_data.xls下载链接，用xlrd读取Data表的E列；保留季度末月份，跳过月内插值。日期由Date Fraction恢复年月，与Date核对；明确TTM（四季度合计）、名义美元/指数份额，不能用Real Earnings、CAPE或预测EPS替换。保留来源链接、抓取日，来源未给出的发布日期留空。

净利润率从FactSet公开周报PDF解析正文中明确的S&P 500季度及previous quarter/year-ago quarter净利润率；这些历史回顾值进入历史曲线。当前季度estimated/blended值单独保存，不与历史值拼线。只匹配net profit margin，不取operating margin、行业值或图像猜值。按同季度不同报告发布日期保留vintages，图表用最新发布版本。

首次取最近报告及4个历史季度末报告，周五/节日未发布时尝试前两周；缓存原文件并对解析结果做版本缓存。每份报告校核封面日期与日期字段、数值有限性/合理范围；解析失败保留来源与缺口，不填0。同口径EPS同比沿用既有公式。历史保留与AI输入增加真实盈利证据，报告新建轮次，不修改旧轮次。

### 依赖与运行

固定xlrd2.0.2、pypdf5.9.0（兼容Python3.8），写src/requirements.txt。依赖安装到项目忽略目录.local/python-packages，可用setup命令安装；serve/实时US命令首次启动时补齐。保留原Mac/Windows薄入口，不改变系统Python。pypdf只抽取有限页和有限大小内容流，保留网络总预算。

### 页面与接口

A股/美股为两个相邻按钮，aria-pressed显示当前项；点击只按原市场切换流程读取存档，同时同步URL和浏览器偏好，不触发AI或定时。

盈利卡保留精简曲线与来源，注明TTM EPS和季度净利润率的不同口径；抓取日、报告发布日期与观测季度分开。EPS与净利润率均为提供方统计，不能据不同提供方口径直接反推经营指标。

### 自检与交付

Codex使用真实公开文件核实解析结果，做页面按钮和数据展示主路径自检，检查AI输入已有盈利证据；正式用例/测试执行不由Codex编写。新实现提交后在任务卡记录实际哈希与剩余边界。

来源：Shiller数据定义 https://shillerdata.com/ ；FactSet公开报告 https://insight.factset.com/topic/earnings/page/1 ；PDF解析库 https://pypdf.readthedocs.io/en/5.9.0/user/extract-text.html 。
