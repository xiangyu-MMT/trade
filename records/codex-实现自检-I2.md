# P03 · TASK-007 实现自检 I2

- **记录人**：Codex；日期2026-09-25，时间均为Asia/Shanghai。
- **实现基线**：`ad09f607d2ad35ebbd2b3cbe4f1bfd7f0ee1db93`。源代码先提交，本记录随后形成。
- **授权**：翔宇明确通过REQ-002 R1，并要求“这个是迭代，直接需求分析，设计，开发搞完”。已依序完成A2、TASK-007 T1、D1后实现；没有代签尚未形成的逐份方案或最终实现。
- **性质**：启动与真实主路径自检；不是正式用例、正式测试执行或独立验收。tests/及05-测试用例/未改动。

## 1. 实际交付

| 需求 | 实现 |
|---|---|
| Codex可用即可，API后备 | 取消ChatGPT认证类别门槛，继承当前Codex服务配置；统一AI路由覆盖分析、计划、复盘；DeepSeek地址/模型/超时/独立密钥入口；取消停止整轮 |
| 默认关闭定时 | 新配置默认关闭、每次服务启动关闭、导入强制关闭；浏览器重载维持本次用户选择 |
| 综合前三 | 22项均送AI，根据逻辑、模式及量价返回完整有序候选列表并校验；无AI时标明仅程序量价参考 |
| 可恢复删除 | 计划与执行回收站、恢复原版本及状态；保留关联，删除执行不进入新复盘，旧复盘显示引用删除状态；迁移版本2保存生命周期 |
| 宽基和图表优先 | 先8项宽基，保留4固定行业，动态前十全分析而展示最强3项；列表直接显示蜡烛、淡色MA5/20/60/120、量柱；日/周可切换 |
| 量价与市场理解 | 每对象完整日量价事实；全市场严格统计及交易所含ST历史分开；市场点评、结构、模式短解读；静态报告与页面共用图表与选择范围 |

实现文件集中于src/trade_assistant/。新增ai_router.py、credentials.py、deepseek_worker.py、volume_price.py、presentation.py、charts.py、providers/market_volume.py、report_v2.py；扩展原配置、计算、业务、存储、HTTP及网页。report.py保留公共入口并调用新报告实现。

## 2. 环境与真实数据

macOS11.7.11 / Apple Silicon，Python3.8.9、Node22.22.2、CodexCLI0.156.0、Google Chrome。沿用Python标准库与SQLite，无新增第三方包；没有改个人Codex配置、网络或其他项目。

实际取得：90同花顺行业行情，22候选（动态行业前10、固定4、指数8去重），23份候选/观察历史；沪深非ST统计5020项。另从交易所公开接口取得2026-08-21至09-24共25个交易日成交额参考。

- 上交所取主板A股/科创板，排除B股和回购。TRADE_AMT单位“亿元”已从交易所页面脚本核实：[官方脚本](https://www.sse.com.cn/xhtml/home/2021public/querySearch/search_stockData_2021.js)，统一转元。
- 深交所取主板A股/创业板A股，文件表头为“成交金额(元)”，排除B股/基金/债券。日期由官方查询参数指定，下载表未单列日期，已保留此限制。
- 交易所参考历史含ST；严格沪深非ST历史由本地完整收盘快照积累，本轮只有一个有效日期。两类序列不拼接，不以盘中累计量对比完整日总额。
- 当日2026-09-25为中秋休市；A股最近交易日09-24，未显示成09-25实时行情。

## 3. 完整量价与AI主路径

使用I1真实快照，补取25日交易所参考，保留原源日期与获取时间，保存`.scratch/p03-i2-selfcheck/snapshot.json`。

```sh
caffeinate -i python3 projects/P03-trade/src/trade.py --home .scratch/p03-i2-selfcheck run --snapshot .scratch/p03-i2-selfcheck/snapshot.json
```

- 隔离轮次：`5697652c0e5c44c78dd60a7e7749f253`。
- 真实Codex退出0，240.76秒，22/22覆盖，完整综合排序校验成功。
- 输入哈希：`1510a1e3ece2efac063318d46e1883b14a5c472c9a09d3a3733ab5800a956829`。
- 输出哈希：`554529ae913241ce6f9e639c068d5dbaf1959dce6a9b82c6293dfa01ddcb88c5`。
- AI原始记录：`.scratch/p03-i2-selfcheck/ai/6ba1f982e2d84c8d8600fca5ab8f5605/`。
- provider=codex、fallback_used=false，认证在本机实际仍为ChatGPT，但应用已移除会员限制。模型沿用CLI配置；CLI未报告具体型号，记录中未编造型号。
- 状态partial是已有数据缺口，非该次AI失败。首页前三与行业前三来自同一综合排序，本轮为半导体、光学光电子、元件，均保留观察/等待语义，不因此宣称适合交易。

另执行从头联网的主使用目录轮次：

```sh
caffeinate -i python3 projects/P03-trade/src/trade.py run
```

轮次`73ff9f5b6e5c4df19f70619162d3626b`，18:40:36开始，18:41:57取数完成，约81秒；22候选、23历史、25日市场量能参考均取得。18:45:47完成，真实Codex退出0、229.51秒，22/22覆盖，error=null，input_mode=live。整体partial仍源于显式数据缺口。

- 实时轮次输入哈希：`aa23db40b16b10d134e2fa5a21237f8474e0825a1244727cb5f0a17c1a924261`。
- 实时轮次输出哈希：`15ff4ddd3ecac006f86889003b8936392f9e9a790076d1c25e5e47bec578d9c2`。
- 实时AI记录：`.local/ai/d3aeab937d084e7290cdf7d2a4fed735/`。本轮综合前三为银行、通信设备、半导体；AI判断可能随数据与生成轮次变化，每轮保留其原输入、解释和排序，不改写旧轮次。
- 主应用使用最终代码重新启动，返回ready=true，监听127.0.0.1:8765。状态为auto_refresh=false、next_refresh=null；主目录16项知识、2项既有用户计划、0执行、0回收站项，原有用户计划未被删除，隔离记录未复制过来。

## 4. 页面与业务主路径

```sh
python3 projects/P03-trade/src/trade.py --home .scratch/p03-i2-selfcheck serve --port 57157 --no-browser
```

实际HTTP响应与Chrome操作：

- 初始`auto_refresh=false`；16项用户原话知识（新增量价优先原则来自已签REQ-002）。
- 候选页面分组8项宽基、4固定行业、3动态行业，合计15张K线量价图；源数据仍分析22项和完整动态前10。
- 配置页面有Codex/DeepSeek选择与password类型的密钥字段，未回显密钥。当前DeepSeek key_configured=false，enabled=false，未发起真实DeepSeek调用。
- 计划界面显示“移入回收站”及“恢复”入口。Chrome运行期间未收集到未捕获脚本异常。
- 截图已实际查看：`.scratch/p03-i2-selfcheck/overview.png`、`candidates.png`；配置截图为`settings.png`。

隔离目录使用人工主路径API创建观察计划及一条action=note说明，记录人/确认人均为“Codex隔离自检”，注明没有买卖。原计划`ce0bb5a6987b4642858a0bf4b2cde357@1`移入回收站后，执行记录保留；恢复后仍为相同ref及confirmed状态。随后将隔离说明记录移入回收站。

导出archive_version=2，向`.scratch/p03-i2-migration`导入成功：18个对象版本、1个轮次、1份AI原始记录、2条生命周期状态。证据为`.scratch/p03-i2-selfcheck/migration.json`、`lifecycle-evidence.json`。这些隔离计划、确认、回填未复制到主使用目录。

## 5. 语法与交付检查

```sh
python3 -m compileall -q projects/P03-trade/src
node --check projects/P03-trade/src/trade_assistant/web/app.js
git diff --check
python3 projects/P03-trade/src/trade.py --home .scratch/p03-i2-selfcheck report --run-id 5697652c0e5c44c78dd60a7e7749f253 --output projects/P03-trade/outputs/codex-量价报告-I2.html
```

上述命令已执行，语法/差异检查没有错误，报告成功生成且已在Google Chrome打开。报告包含实际蜡烛、均线、量柱、市场量能与同一候选展示范围，无CDN。临时caffeinate只在这次主路径运行期间防空闲休眠，没有改系统电源设置。

收尾再次从正式目录最新实时轮次导出同名I2报告（`report --run-id 73ff9f5b6e5c4df19f70619162d3626b --output projects/P03-trade/outputs/codex-量价报告-I2.html`），并在Google Chrome打开；最终报告对应实时轮次。[I2交付页](../outputs/codex-迭代交付-I2.html)也已在Chrome打开。

## 6. 明确限制

- DeepSeek配置、请求适配、统一后备及取消处理已经实现；没有用户密钥，真实DeepSeek调用和非ChatGPT的Codex认证未在本机实际验证。不能把静态检查或Codex成功当作DeepSeek通过。
- Windows未实机运行；没有等待完整一小时验证周期触发，正式异常覆盖及独立验收留给小步。
- 同花顺成份未全部核齐，行业成交额排名保留原发布口径；行业资金/涨幅表仍可能不可得；深圳ETF份额的源日期缺口继续保留。
- 中证金融与微盘股具体代码仍待用户配置；个人风险规则和实际交易品种仍由用户决定。
- 回收站没有永久清空；用户资料与本机凭据均未删除。仓库已有小步HTML未修改或纳入提交。

## 7. 阶段

A2与TASK-007 D1已按本轮统一授权完成；代码交付进入review。待翔宇查看本实现提交与I2原始交付，之后小步才进入正式用例阶段。本记录不是用户通过签字。
