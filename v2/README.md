# 天才交易员 V2

当前实现：**前两阶段已完成本机运行验证；第三阶段已写入研究报告、长期记忆后端与 dsh 原生工具，正在联调。**

换电脑继续请先读 [开发接续与换机](docs/07_开发接续与换机.md)，其中记录了当前进度、dsh 源码版本、启动步骤和下一项待完成验证。

目前提供两条路径：股票代码 → 获取日线 → 计算趋势规则 → 保存与回查；资料正文 → 切块 → 本地 Embedding → pgvector 检索原文与来源。入口是本地 API、Swagger `/docs` 和 CLI。

使用 PostgreSQL + pgvector 单库，当前代码要求数据库 schema 为 **4**。业务资料、切块、向量、检索评测、研究报告和长期记忆都入库，不生成业务 JSON 文件。第三阶段的真实模型端到端流程尚未验收，交易属于更后面的阶段。已有环境需执行 `python -m trader_v2.cli init-db` 并重启服务。

## 首次启动

需要 Python **3.11 或以上**，并让 **Docker Desktop 保持运行**。首次准备还需联网安装 Python 依赖和数据库镜像。

在 PowerShell 中进入本目录：

```powershell
Set-Location D:\dongkw\v2
.\scripts\setup.ps1
```

`setup.ps1` 创建本项目独立的 `.venv`，不复用根目录旧 `venv`；安装 CPU 版 PyTorch 和锁定的业务/检索依赖，生成 `.env`，启动数据库并初始化表和 pgvector。已有环境可重新运行，升级依赖与 schema。

如果默认 Python 不可用，明确指定本机已有的 Python 可执行文件。例如下面路径仅为示例，替换成实际安装位置：

```powershell
.\scripts\setup.ps1 -PythonPath 'C:\Python312\python.exe'
```

需要暂时只安装 Python 环境时可用 `-SkipDatabase`。之后先运行 `.\scripts\database.ps1 -Action Start`，再运行 `.\.venv\Scripts\python.exe -m trader_v2.cli init-db` 初始化数据库。

## 准备本地 Embedding 模型

第二阶段固定使用 `BAAI/bge-small-zh-v1.5`，输出 **512 维**向量，模型修订为 `7999e1d3359715c523056ef9478215996d62a620`。文本和问题使用同一个模型修订；文档不加查询指令，短问题按模型约定添加检索指令。

模型下载是单独、显式执行的操作，不要求数据库连接：

```powershell
.\.venv\Scripts\python.exe -m trader_v2.cli prepare-model
```

默认使用官方 Hugging Face 端点。若当前网络不可达，可以显式选择第三方镜像；程序不会自动更换下载来源：

```powershell
.\.venv\Scripts\python.exe -m trader_v2.cli prepare-model --endpoint https://hf-mirror.com
```

权重和 tokenizer 等模型技术文件默认保存在 `.runtime/models/bge-small-zh-v1.5`；其中的模型 JSON 配置不是业务资料。CPU 推理在本机完成。普通检索请求只加载本地固定版本，不自动联网下载。

## 运行向量检索演示

先完成环境和模型准备，再执行：

```powershell
.\scripts\vector-demo.ps1
```

脚本依次初始化数据库、导入合成资料、执行真实模型检索评测。它不会每次重新下载模型，任何一步失败都会停止。资料均标记为 `mode="fixture"`，使用股票代码仅为演示公司过滤，不代表这些公司实际发布过相应内容。

也可逐步运行，观察每个环节：

```powershell
.\.venv\Scripts\python.exe -m trader_v2.cli init-db
.\.venv\Scripts\python.exe -m trader_v2.cli knowledge-demo
.\.venv\Scripts\python.exe -m trader_v2.cli search '这家公司是不是账面赚了钱，却没有收回货款？' --symbol 601138 --mode fixture --as-of '2026-10-20T23:59:00+08:00' --top-k 5 --min-score 0.55
.\.venv\Scripts\python.exe -m trader_v2.cli evaluate-retrieval --top-k 5 --min-score 0.55
```

检索返回片段正文、来源键、资料版本、原文字符位置和相似度，可继续通过片段 ID 查原文。`as_of` 按资料公开可用时间过滤；同一来源按当时可见的版本查询。删除资料时会删除整份来源及其全部版本的正常检索资格。

`0.55` 是基于合成学习语料标定的演示检索阈值，可以通过 `vector-demo.ps1 -MinScore` 或 CLI 参数调整。实测相关资料得分约为 0.583～0.719，无关问题最高约 0.409；原先的 0.65 会漏掉一些相关资料。**相似度不是事实可信度或盈利概率**，这些问题同时用于标定，不能当成独立测试集或推广到全部公告。评测报告保存到数据库；若存在未通过项，CLI 仍输出报告并返回非零码。

## 导入自己的 UTF-8 笔记

`ingest` 接受本地 UTF-8 文本或 Markdown。以下直接导入仓库中已有的设计文档，作为学习笔记：

```powershell
.\.venv\Scripts\python.exe -m trader_v2.cli ingest --file '.\docs\05_向量检索与长期记忆.md' --title '项目向量检索学习笔记' --source-key 'local.learning.vector-plan' --kind note --source-name '本地项目文档' --available-at '2026-10-26T00:00:00+08:00'
.\.venv\Scripts\python.exe -m trader_v2.cli search '模型为什么需要把文章切成小段？' --kind note --mode imported
```

股票笔记可额外指定 `--symbol 601138`，多个本地用途可通过 `--scope-id` 分开。`--available-at` 必须包含时区；`--source-url` 只保存来源地址，不会抓取该网页。同一资料用稳定 `source-key`，正文或元数据改变后保存新版本。

`mode="imported"` 表示用户导入，不代表程序已经核实内容或公开日期。导入公告时需要提供准确的公司、来源与公开时间；历史研究观点也应与原始公告区分。

## 运行一次分析

先运行可重复的合成样例，不依赖行情网络：

```powershell
.\scripts\demo.ps1 -Symbol 601138
```

默认 `Mode=fixture`，会生成合成工作日日线、计算规则并保存到数据库。输出包含 `mode`、来源、日期、指标、规则和研究记录 ID。**这些样例不是历史真实行情，不能用于宣称回测表现或盈利。**

访问腾讯真实日线需要明确切换：

```powershell
.\scripts\demo.ps1 -Symbol 601138 -Mode live
```

也可以直接使用 CLI：

```powershell
.\.venv\Scripts\python.exe -m trader_v2.cli analyze 601138 --mode live --limit 120
.\.venv\Scripts\python.exe -m trader_v2.cli analyze 601138 --mode fixture --limit 120
.\.venv\Scripts\python.exe -m trader_v2.cli health
```

真实模式依赖数据源和本机网络；请求失败会明确报错，不会自动换成样例。当前支持普通沪深主板六位股票代码，日线请求数量为 20～640，完整趋势规则至少需要 61 根。腾讯日线量转换为股，未提供的成交额保留为空；未收盘当日日线不会用于计算。

规则包括 MA20/MA60、均线方向、20 日涨幅与 ATR14，输出 `PASS`、`WATCH` 或 `BLOCKED` 及对应原因。这是技术趋势结果，不是完整公司研究或交易指令。

## 启动本地接口

```powershell
.\scripts\start.ps1
```

默认地址：[http://127.0.0.1:8012/docs](http://127.0.0.1:8012/docs)。访问根地址也会转到 Swagger。需要临时换端口可运行 `.\scripts\start.ps1 -Port 8013`。

| 接口 | 用途 |
| --- | --- |
| `GET /health` | 查看数据库、pgvector 和当前阶段状态 |
| `GET /api/watchlist` | 查询自选股 |
| `POST /api/stocks/{symbol}/analyze` | 取数据、算规则并入库，请求体必须指定 `mode` |
| `GET /api/analyses` | 查询已保存记录，可按股票和 `fixture/live` 模式过滤 |
| `GET /api/analyses/{run_id}` | 回查一次分析的数据来源、日期范围、指标和规则 |

API 的 `mode="fixture"` 使用合成样例，`mode="live"` 才请求真实来源。HTTP/CLI 显示的 JSON 只是传输和终端输出，业务记录保存在数据库。

知识库接口也在同一 Swagger 页面：

| 接口 | 用途 |
| --- | --- |
| `GET /api/knowledge/status` | 查看固定模型、文件就绪及加载状态，不触发下载 |
| `POST /api/knowledge/documents` | 导入正文、切块、向量化并入库 |
| `GET /api/knowledge/documents` | 按范围、股票和模式列出资料 |
| `GET /api/knowledge/documents/{document_id}` | 读取资料正文和来源 |
| `DELETE /api/knowledge/documents/{document_id}` | 删除整份来源及其全部版本的正常检索资格 |
| `GET /api/knowledge/chunks/{chunk_id}` | 回查原文片段及字符位置 |
| `POST /api/knowledge/search` | 问题向量化，结合公司、类型和截止时间检索 |
| `POST /api/knowledge/demo` | 导入明确标识为合成的学习资料，可重复执行 |

知识资料使用 `fixture/imported` 两种模式；行情使用 `fixture/live`，二者含义不同。知识库目前只返回检索证据，不调用生成模型组织回答。

## 数据库与配置

配置保存在本目录 `.env`，由 `setup.ps1` 首次生成，数据库密码随机创建；不要将其提交到版本库。

| 配置 | 默认用途 |
| --- | --- |
| `V2_DATABASE_URL` | Python 连接 PostgreSQL 的地址 |
| `V2_DB_PORT` | Docker 数据库本机端口，默认 `55432` |
| `V2_DB_PASSWORD` | Docker 中数据库用户的密码，与连接地址保持相同 |
| `V2_API_PORT` | 本地接口端口，默认 `8012` |
| `V2_MODEL_PATH` | 本地模型目录，默认 `.runtime/models/bge-small-zh-v1.5` |
| `V2_EMBEDDING_THREADS` | CPU 推理线程数，默认 `4` |
| `V2_RETRIEVAL_MIN_SCORE` | 未在请求中指定时使用的检索阈值，默认 `0.55` |

数据库只映射到 `127.0.0.1:55432`。改数据库端口时，同时修改 `.env` 中的 `V2_DB_PORT` 与 `V2_DATABASE_URL`。

```powershell
.\scripts\database.ps1 -Action Status
.\scripts\database.ps1 -Action Start
.\scripts\database.ps1 -Action Stop
```

停止数据库不删除 Docker 数据卷。API 运行窗口按 `Ctrl+C` 停止服务；下次运行先启动数据库，再运行 `start.ps1`。

本机 Docker Desktop 已重装到 `D:\Docker`，WSL 数据盘位于 `D:\DockerData\wsl`。数据库脚本从安装注册信息解析 CLI，支持这一安装位置。重装前的 Docker 专用 WSL 数据导出备份位于 `.runtime/docker-backup-20261026-d-drive/`。

## 验证与评测

2026-10-26：完整 **147 项测试通过**，包括真实本地 BGE 模型与 PostgreSQL 的联调。覆盖切块、超长输入、模型版本、公司/时间/范围过滤、原文位置、重复导入、来源更新与删除，以及第一阶段业务回归。

10 篇明确标识为合成的资料生成 20 个向量片段；12 个学习检索用例在 0.55 阈值下通过。0.65 阈值的先前结果为 7/12，两次报告均保存于 `retrieval_evaluations`。这些问题参与了阈值标定，不是独立评测集，也不代表真实金融资料上的准确率。

腾讯 `601138` 的 120 根真实日线已成功获取并保存，数据截止 2026-10-23；本机服务 `/health`、`/docs`、提交分析和历史回查均验证成功。测试库在测试结束后移除，演示记录保存在项目业务库。

运行测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -m 'not integration' -q
$env:V2_RUN_DB_TESTS='1'
$env:V2_RUN_EMBEDDING_TESTS='1'
.\.venv\Scripts\python.exe -m pytest -q
```

完整测试会在本地 PostgreSQL 创建并移除带随机名称的独立测试库，不清空项目业务库；真实模型测试需先准备本地权重。详见 [第二阶段验收记录](docs/06_第二阶段验收记录.md)。

## 后续开发与设计

下一阶段通过 dsh 工具使用检索证据并接入长期记忆，再增加计划风控、虚拟盘、自动运行和收益实验。桌面/网页兼容与插件发布后置。

- [04：分阶段实现方案](docs/04_分阶段实现方案.md)：当前开发顺序与逐段验收。
- [05：向量检索与长期记忆](docs/05_向量检索与长期记忆.md)：切块、Embedding、语义检索、RAG 和记忆读写。
- [01：Agent 开发八件事与项目对应](docs/01_Agent开发八件事与项目对应.md)：宿主、插件、模型和业务程序的职责。
- [02：总体重构方案](docs/02_总体重构方案.md)：总体方向与旧能力取舍。
- [03：dsh 插件功能清单](docs/03_dsh插件功能清单.md)：完整功能目录，分阶段实现。
