# P03 · trade 测试代码（小步）

本目录是 P03 的正式测试代码，归小步（测试方）维护。**不修改 `src/`**。

## 怎么跑

```sh
cd projects/P03-trade
python3 -m unittest discover -s tests -p "test_*.py" -v
```

或用系统 Python（3.8 亦可）：

```sh
/usr/bin/python3 -m unittest discover -s tests -p "test_*.py"
```

跑单个文件：

```sh
python3 -m unittest tests.test_config -v      # 需在项目根执行
```

## 文件

| 文件 | 覆盖 |
|---|---|
| `support.py` | 公用夹具：临时数据目录、交易日生成、K 线构造、错误断言。不是测试用例，不会被 discover 执行 |
| `test_config.py` | A 组 · 配置与校验 |
| `test_store.py` | B 组 · 档案版本与确认；C 组 · 回收站与生命周期 |
| `test_indicators.py` | E 组 · 指标计算 |
| `test_volume_price.py` | F 组（量价）· 完整交易日量价事实 |
| `test_facts.py` | F 组（事实）· 全市场盘面与补充数据口径 |
| `test_presentation.py` | G 组 · 呈现与排序 |
| `test_charts.py` | J 组（图表）· K线、均线显示、仪表盘曲线 |
| `test_ai_router.py` | H 组（接入）· 模型路由、降级链、凭据隔离 |
| `test_engine_validate.py` | H 组（校验）· AI 输入收敛与引用校验 |
| `test_plans.py` | I 组 · 计划、回填、复盘 |
| `test_server_api.py` | J/K 组 · 本机 HTTP 接口、报告、运行调度、命令行 |

用例编号与 `../05-测试用例/P03-测试用例-T1.md` 对应；测试方法名里的 `test_a01_...` / `test_b01_...`
对应用例编号（如 `test_c04_restore_keeps_everything` = 用例 C-04）。

## 隔离要求

- 每个测试用 `tempfile.mkdtemp()` 建独立数据目录，结束后删除。
- **不读写项目 `.local/`**（真实运行数据），不触碰 `.scratch/`。
- 起本机服务用 `--port 0`（系统分配随机端口），避免与 8765 上的真实服务冲突。
- 不联网：取数与 AI 调用全部用桩或离线夹具替代（真实链路抽测见执行记录）。

## 不覆盖

- Windows 实机、完整 1 小时周期、真实 DeepSeek 调用、浏览器交互动画：见用例文档第 15 节。
