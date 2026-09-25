# TASK-007 · 完整技术设计 D1

- **依据**：REQ-002 R1已签、全池分析A2、TASK-007 T1；首期实现c072c4b。
- **完成登记**：2026-09-25 18:17:03（Asia/Shanghai）。本D1在实现代码之前形成。
- **授权**：翔宇本轮原话“通过 P03 REQ-002 R1，开始需求分析。这个是迭代，直接需求分析，设计，开发搞完。”。按该连续授权实施，不补造逐份事前审阅签字。

## 1. 总体方案与影响

沿用Python3.8+标准库、SQLite、本地HTTP、原生网页及自包含报告。新增统一AI路由、DeepSeek请求适配、量价事实、排序选择、回收站状态和通用SVG图表。AI仍只读资料，实际交易由用户操作。TASK-001～006原模块被TASK-007按下表扩展；历史签字和原始运行记录保留。

| 模块 | 实现位置 | 覆盖 |
|---|---|---|
| AI配置及本机密钥 | config.py、credentials.py、server.py | AC01/02 |
| Codex/DeepSeek路由 | codex_bridge.py、ai_router.py、deepseek_worker.py | AC01/02 |
| 量价与市场历史 | volume_price.py、collector.py、facts.py、providers/market_volume.py | AC04 |
| 综合排序与可见范围 | engine.py、presentation.py、analysis schema/提示 | AC05 |
| 回收站及迁移 | store.py、plans.py、server.py | AC06 |
| 周期、图表和报告 | runner.py、charts.py、web/、report.py | AC03/07/08 |

## 2. AI与配置协议

保留ai.enabled/command/timeout旧字段，补充可选model和provider（codex/deepseek）；deepseek包含enabled/base_url/model/timeout。旧配置读取时补默认值：provider=codex，deepseek.enabled=false，官方地址https://api.deepseek.com，模型名称可编辑，初始使用查阅官方文档列出的deepseek-flash。密钥保存在本机独立凭据文件或DEEPSEEK_API_KEY环境，不进入config快照、Git或迁移。凭据文件保存时限制本机权限；GET只返回配置状态，不回显密钥。

Codex取消auth_kind==ChatGPT门槛、不剔除用户原API认证环境、不忽略用户提供方配置；本次只覆盖禁用工具、只读、结构化输出等分析调用参数。可选model为空时沿用CLI配置；CLI没有返回型号时标为沿用配置/未报告型号，不能捏造实际模型。新/旧计划都不自动下单。

新增GET /api/ai、PUT /api/ai（配置与独立key字段分开），现有/api/codex兼容状态读取。先Codex，调用失败且已配置启用后备时用DeepSeek；也允许在配置中直接选DeepSeek以便用户使用。分析/计划/复盘走同一路由；每一尝试保存provider/model/purpose/时间/输入哈希/失败代码。显式取消使路由终止，不降级。

DeepSeek使用/chat/completions，messages含资料与JSON Schema约束，response_format=json_object；程序进行相同结构与引用校验。请求在专用子进程中，密钥经stdin传递，不放命令行、日志或原始输入文件；限时并可取消。禁止带密钥跨域重定向。HTTP错误仅输出状态，不回显可能含敏感信息的响应正文。API上限及实际用户权限以运行结果为准。

## 3. 量价事实

每个候选及观察指数保留真实OHLCV。以最近完整日线计算：1/5/20日价格变动、最新量相对前日/前5/前20日均量、涨日和跌日的平均量、20日区间位置、20日突破与回撤、MA方向。数值使用同一对象内部比率，不把不同证券原始量直接互比；不称成交量为净流入。

形成中的日/周线仍绘图，但不把其总量与完整日/周比较；当前盘中量单列，比较基于最近完整日线并注明日期。比较窗口不足、无效OHLC、单位/日期冲突返回缺口，不能填0或编造放量。每周量能只有完成周才作整周比较，短周天数差异保留。

全市场保留严格沪深非ST快照统计，并从已有真实完整收盘轮次积累同范围日成交额序列。另尝试交易所公开沪深A股每日成交额历史，含ST的原口径只能作为单列参考，不替代严格统计；两类数据不可拼接。若外部原口径无法取得或历史不够，展示实际可用序列和缺口。全市场盘中累计量不与完整前日相除；快照日与生成日分开。

行业量价优先已有同花顺日线，宽基使用各自提供方序列。用于模型的volume_price事实包含窗口、截至日期、完成状态、单位/来源与简短程序观察；完整原始数据仍保留。

## 4. 综合排序和输出协议

analysis输出新增market.commentary/structure/mode_summary，候选新增volume_price_reading/strength_reason，以及ranked_asset_ids。模型必须按逻辑熟悉程度、模式适配及量价强弱给出全体可排序候选的有序列表，量价为主要技术证据；按事实而非随意打分。程序校验列表唯一、范围合法且覆盖全部可排序对象。可排序资格要求非excluded、足够价格和量能历史、截至时间可比。

程序备选排序只在没有有效AI综合排序时使用，明确label为“量价参考，缺AI综合判断”。按方向性量价配合、均线结构、20日相对涨幅、回撤风险等透明比较键稳定排序，不冒充概率或AI结论；参数及比较键记录在事实中。

presentation统一产生overall_top3、industry_top3、visible_groups与排序来源，页面和报告共用。宽基全部优先，其后固定行业、动态行业综合前三、配置个股；同对象去重保留多来源标签。完整前十及全部候选仍存原始轮次并送AI。旧轮次缺新字段时明确提示旧版资料，允许按新程序生成显示所需量价事实，不改写旧AI输出。

## 5. 回收站与迁移

SQLite增加object_lifecycle(object_id,is_deleted,updated_at,actor)，删除只标记对象，历史objects各版本、确认记录、plans/executions/reviews引用不变。正常list排除deleted；get_ref允许历史读取并附删除状态。新增POST /api/objects/:id/trash、/restore，GET /api/trash。仅plan/execution允许操作，要求expected_revision与明确确认。

删除计划不删除执行/复盘；新回填不能关联已删除计划。删除执行后新复盘list不取该记录，旧复盘展示被引用项删除状态。禁止修订/确认已删除对象；恢复原对象，不复制版本。删除/恢复与AI任务通过运行锁互斥，避免生成途中更换有效事实。

迁移archive_version=2携带lifecycle，兼容读取v1。导入先验证对象引用、种类、状态及冲突，再事务合并；同对象生命周期冲突明确拒绝，不静默复活已删除记录。密钥不进入迁移；导入时周期强制关闭。

## 6. 周期和界面

App启动时强制auto_refresh=false，移入会话运行状态；本机配置保存并不触发分析。/api/config中的显式用户操作可开关本次周期；每小时、重叠合并、休眠恢复规则保留。迁移后关闭，浏览器重载读当前服务状态。

绘图统一生成真实蜡烛、较淡可区分MA5/20/60/120、底部同时间轴成交量。日/周切换，辅助指标折叠。可在Python生成SVG并在run_view中返回展示片段，与静态报告共享，避免两套K线口径。SVG中的所有标签转义，图不加载外链；列表图支持查看OHLC日期信息。

首页三段市场解读，市场量能趋势和广度图、量价前三卡；候选页先宽基，列表项直接带图。默认每项一句量价理解、一句综合理由和关键反证；完整依据/原始数值按需展开。计划页增加删除、回收站、恢复及引用删除提示。配置页提供模型选择、命令、DeepSeek地址/模型、掩码密钥入口及保存状态，正常用户流程不展示实现内部细节。

## 7. 自检及交付

实现自检使用真实已保存快照及可用免费数据、当前Codex调用、隔离目录中的计划说明记录及迁移；只做启动/主路径调用，不写tests或正式断言用例。DeepSeek没有可用密钥时如实标记未真实联网验证，不能把格式检查当API通过。Windows未实机验证继续明确。

源代码先提交，再登记最终哈希、自检命令、实际结果和遗留；TASK-007进入review，交付可运行页面、自包含HTML及使用说明。按本轮连续授权不再请求中间阶段许可，最终实现仍供翔宇签收。

## 依据

- Codex命令：https://learn.chatgpt.com/docs/developer-commands
- DeepSeek接口：https://api-docs.deepseek.com/api/create-chat-completion/
- 交易所统计字段核实线索：AKShare官方stock_summary.py对应公开接口及交易所实际返回；不引入其依赖包。

## I2 实现落实

本设计已完成代码实现，最终提交ad09f607d2ad35ebbd2b3cbe4f1bfd7f0ee1db93，见TASK-007及原始自检I2。新增report_v2.py承载报告布局，report.py保持公开入口；共享图表与候选选择规则。免费交易所历史实际补齐25日，含ST口径始终与严格统计分开；上交所TRADE_AMT单位已从其官方search_stockData_2021.js的“成交金额(亿元)”字段映射核实。DeepSeek未取得用户密钥，真实API调用未验证，不记为已通过。
