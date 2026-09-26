# TASK-015 · 美股概览图表与双市场运行整合 · 技术设计 D1

- 项目：P03-trade；依据：REQ-005 R2、分析A6、TASK-015 T1。
- 当前修订：D2（下方保留D1与I6历史，本轮修订见末节）。
- 档位：独立完整方案；作者：Codex；形成时间：2026-09-26 11:11:47（Asia/Shanghai）。
- 授权：翔宇明确回复“通过 A6 和 TASK-010～015 T1，开始技术设计，技术设计后直接编码。”本轮按此连续完成设计与实现；该回复为阶段推进授权，不伪记为对随后形成D1内容的事前审阅签字。
- 边界：人工交易、免费行情、七个美国行业、三指数境内ETF配对；正式测试与验收由小步负责。

## 1. 目标与取舍

实现当前任务卡全部范围，复用本地Python/SQLite/原生HTML栈；共用基础协议先确定，再顺序接入数据、事实、AI及页面。不接券商下单接口。

## 2. 详细方案

### 页面
侧边栏增加A股/美股选择，视图市场独立于定时市场配置。US概览：三句点评/结构/模式；三指数K线（每个下方对应境内ETF图、代码、溢价基准日期）；涨跌曲线与纽约金；短期流动性、中期利率信用、长期盈利增长折叠图表；候选七个美国行业保持范围与代理标签。只综合前三突出展示，全关注清单可展开。无数据不伪造图线。
复用现有SVG K线与日周切换，显示均线默认20，选择不会调模型或改分析参数；US指数量柱若用美国ETF代理必须清楚标注，ETF卡与指数分开。
图表与说明配套少量文字，来源/局限折叠；错误信息不遮住此前可用结果。档案、计划、回收站、历史按所选市场过滤，旧引用仍能定位。
### API/运行
/api/state?market=CN|US、/api/runs?market=；POST /api/run带market。状态显示正在处理哪个市场；scheduled_markets默认[CN]且auto_refresh每次启动false，可明确选择CN/US/两者。单操作锁顺序执行，睡眠醒来仅补一轮，不开无限后台数据进程。
CLI collect/run增加 --market；compute按快照市场分发。导出报告根据facts市场使用report_us.py，自包含浅色无CDN，保存当时配对/事实/来源，不跟随当前配置改变。
### 运行及交付
保持标准库优先，Python3.8可运行，时区提供兼容实现；现有Mac和Windows薄入口继续使用。交付只描述实际启动/接口/真实取数/模型调用/报告/迁移主路径自检；正式测试交小步，Windows无实机不报通过。
自检专用本地目录与真实用户.local隔离，避免改用户档案与计划；如需重启已有服务先核实进程，不能终止未知后台进程。

## 3. 溯源与风险

官方资料：NYSE日历 https://www.nyse.com/trade/hours-calendars ；Nasdaq证券目录说明 https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs ；软件代理定义 https://www.ssga.com/us/en/institutional/etfs/state-street-spdr-sp-software-services-etf-xsw ；FRED序列定义 https://fred.stlouisfed.org/series/WALCL 、https://fred.stlouisfed.org/series/WDTGAL 、https://fred.stlouisfed.org/series/RRPONTSYD 。

本轮已实际读取Yahoo纳指100历史、Nasdaq全市场目录和境内基金目录；FRED下载超时、S&P盈利表403。来源会变化，适配器须验证数据结构、时点与身份，成功/失败留coverage，不以网页存在推定API稳定。

## 4. 实现与验证责任

实现按本方案接口分步落地，保持旧资料可读。Codex做语法加载、启动、真实取数和主路径调用自检，记录实际命令/结果/限制；不编写或执行正式测试。小步在实现获签后依据任务卡设计正式覆盖。

## 5. 变更与交付

影响现有文件与新增模块按上文记录；不删除旧文件/历史数据，无新云服务或订阅。设计与实现存在偏差时在任务卡完成说明登记，旧方案保留。实现单独提交后再记录提交哈希。


## 6. I6实现落实记录

2026-09-26 12:14:22（Asia/Shanghai）：本方案落实于9506952358ec8908e6b987e1a4fe27047aac1636。双市场页面、配对K线、宏观与广度、独立图层、周期范围及离线报告。限制：Windows、长时间周期/休眠和正式回归未执行，交小步。事实见[原始自检](../records/codex-实现自检-I6.md)。实现签收与正式测试尚待后续阶段，不代签。


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
