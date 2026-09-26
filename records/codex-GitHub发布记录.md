# P03 · GitHub 发布记录

## 2026-09-26 · 首次上传

- 记录人：Codex；时间：2026-09-26 13:43:46（Asia/Shanghai）。
- 翔宇原话：“我在浏览器上登陆了github，现在把项目P03上传到github上。需要我做什么呢？”
- 仓库名称与可见性确认：“项目名称叫做trade，公开的”。
- 浏览器授权确认：“已授权”；CLI实际识别账号`xiangyu-MMT`。
- 仓库：[xiangyu-MMT/trade](https://github.com/xiangyu-MMT/trade)，已核实`visibility=public`、`private=false`，默认分支`main`。

## 上传内容与版本

- 从`projects/P03-trade`提取独立提交历史；首次上传154个已提交文件、39次项目提交。代码、需求、设计、已有测试与交付资料保持原内容。
- 原工作区准备提交：`2d65f44c34ba23fa93100bd91c7ddd7113740d6c`；首次远端提交：`0c42c092a5fac04ebffaada23d098cffb6186d89`。
- 此发布记录与仓库链接在首次成功上传后补入，并以随后一次文档提交同步。
- 应用源码仍为I7实现`ab3044d`；上传不代替实现签收、正式测试或独立验收。
- 四份尚未提交的小步验收/解读文件留在原工作区，本次以已提交版本为上传范围。

## 整理与核对

- 增加项目根README及独立`.gitignore`，克隆后的启动命令为`python3 src/trade.py setup`和`python3 src/trade.py serve`。
- 提取后的所有历史树仅含P03，没有P01、P02和工作区根资料。
- `.local/`运行数据、数据库、缓存、凭据及下载依赖不在上传树中。
- 扫描350个历史文件版本，未发现匹配的密钥/私钥；带用户名密码的URL命中仅为原测试中的校验示例。
- 通过GitHub API核对公开状态、默认分支、远端提交和154文件清单，均与首次上传副本一致。

## 后续维护

继续在原P03目录开发。原工作区同时包含多个项目，后续同步仍通过P03子目录提取；独立上传副本位于工作区`.scratch/p03-github-trade/`，其`origin`指向上述仓库，`workspace-source`指向原工作区提取分支`p03-github-export`。

本机GitHub CLI位于`.scratch/p03-github-tools/gh`，授权配置目录为`.scratch/p03-github-auth/`，均不进入提交。后续在其他设备可以使用标准GitHub CLI登录和Git克隆流程，不需要复制本机凭据。
