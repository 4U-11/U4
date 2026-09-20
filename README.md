# 课程材料学习助手

一个用于帮助学习 PDF 和 DOCX 课程材料的本地开发项目。计划逐步支持文件上传、内容解析、翻译、代码提取与解释、作业步骤生成，以及学习记录管理。


## 技术栈

- 前端：Next.js、React、TypeScript、Tailwind CSS
- 后端：Python、FastAPI、Uvicorn
- 开发期文件存储：本地 `storage/` 目录

## 项目目录

```text
.
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI 应用入口，注册接口和错误处理
│   │   ├── schemas.py       # 请求/响应中使用的数据格式
│   │   ├── errors.py        # 统一错误响应
│   │   ├── parser.py        # Docling PDF / DOCX 解析与导出
│   │   ├── content.py       # Docling 元素到应用内容模型的映射
│   │   ├── content_models.py # 内容块、翻译、代码和 Workbench 数据模型
│   │   ├── translation.py   # 本地翻译、术语表和行内占位符保护
│   │   ├── ai.py            # OpenAI-compatible 结构化 AI 调用
│   │   ├── processing.py    # 翻译与 AI 处理接口及后台任务
│   │   ├── task_store.py    # 本地任务状态持久化与重启恢复
│   │   └── documents.py     # 资料接口和本地文件记录
│   ├── .venv/               # Python 虚拟环境，不提交到 Git
│   └── requirements.txt     # Python 后端依赖及版本
├── docs/                    # 项目文档
├── frontend/                # Next.js 前端
├── storage/
│   ├── uploads/             # 原始上传文件
│   └── parsed/              # 解析结果
├── .env.example             # 环境变量示例，不含真实密钥
├── .gitignore
├── README.md
└── step.md                  # 开发步骤与进度
```

## 环境要求

- Windows 和 PowerShell
- Node.js（包含 npm）
- Python 3.10+

## 首次安装

以下命令默认在项目根目录执行。若已完成依赖安装，可以跳过本节。

### 安装前端依赖

```powershell
Set-Location .\frontend
npm install
Set-Location ..
```

如果 PowerShell 报错说禁止运行 `npm.ps1`，可以把 `npm install` 改为：

```powershell
npm.cmd install
```

### 创建后端虚拟环境并安装依赖

```powershell
Set-Location .\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Set-Location ..
```

虚拟环境将依赖安装在项目的 `backend/.venv/` 中，避免与电脑上的其他 Python 项目互相影响。`requirements.txt` 记录了后端依赖及其版本，便于在新环境中安装。

## 启动开发服务

前后端需要分别在两个 PowerShell 终端中运行。两个终端的当前目录都应是项目根目录。

### 终端一：启动 FastAPI 后端

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- `--reload`：开发时检测代码变化并自动重启后端。
- 健康检查：<http://127.0.0.1:8000/health>
- API 文档：<http://127.0.0.1:8000/docs>

正常时，健康检查会返回类似结果：

```json
{
  "status": "ok",
  "service": "course-material-api"
}
```

### 终端二：启动 Next.js 前端

```powershell
Set-Location .\frontend
npm run dev
```

如果 PowerShell 因执行策略禁止运行 `npm.ps1`，使用：

```powershell
npm.cmd run dev
```

启动后打开：<http://localhost:3000>

### 关闭服务

分别切换到运行前端和后端的终端，各按一次 `Ctrl + C`。

## 环境变量

根目录的 `.env.example` 是后续功能的配置示例。目前健康检查接口不依赖这些配置。添加真实 API Key 或其他私密配置时，请放在本地环境文件中，并确认没有提交到 Git；不要把真实密钥写入 `.env.example`。

## 后端接口与本地文件保存

启动后端后，可在 <http://127.0.0.1:8000/docs> 直接调用资料上传、列表、详情、状态、解析结果、Workbench、翻译与 AI 处理接口、重新生成和删除接口。接口路径统一使用 `/api/documents` 前缀。处理说明见 [Step 5 学习指南](./docs/step5-docling.md)、[Step 6 内容模型说明](./docs/step6-content-model.md) 和 [Step 7–8 翻译与 AI 处理](./docs/step7-8-processing.md)。

AI 服务设置接口位于 `/api/settings/ai`，支持 OpenAI 与 DeepSeek。Key 由 Windows DPAPI 加密后保存在当前 Windows 用户目录，接口不会返回 Key；测试连接不会保存 Key。资料备份使用 `GET /api/backup/export` 生成 ZIP，`POST /api/backup/import` 合并恢复；ZIP 包含课件原件和处理结果，不包含 AI Key。设置页可授权浏览器文件夹直接保存备份，不支持文件夹授权时可下载 ZIP；导入时跳过已存在的资料。

上传的原文件和 JSON 资料记录保存在 `storage/uploads/`；Markdown、Docling 原生 JSON、归一化内容块和 Workbench JSON 保存在 `storage/parsed/`，AI/翻译任务状态保存在 `storage/parsed/tasks/`。上传接口先保存文件并返回 `202`，Docling 随后在 FastAPI 本地后台任务中解析；`GET /api/documents/{id}/status` 和 Workbench 页面会轮询阶段状态。传输进度由浏览器上传事件显示，解析状态标记排队、解析和保存阶段。解析失败保留原件、错误类别及重试入口。通过 `GET /api/documents/{id}/parsed` 读取原生解析结果，通过 `GET /api/documents/{id}/workbench` 读取结构化 Workbench 数据；`POST /api/documents/{id}/process` 返回任务 ID，使用 `GET /api/documents/{id}/tasks/{task_id}` 轮询翻译或 AI 处理状态。失败任务可从工作台重新运行，服务重启时未完成任务会标记为失败。

后台任务使用进程内 FastAPI `BackgroundTasks`，适合本地单进程开发，不要求额外安装 Redis。当前 Docling 解析通过线程池执行，单个解析器会串行处理文件；如需多进程、多实例或长期任务队列，再迁移到 Redis + Celery/RQ。该应用仍是本地单用户版本，没有登录系统或跨账号权限模型。

普通文本翻译使用本机配置的 LibreTranslate。无用户 Key 时，平台 AI 只允许代码解释和作业步骤拆解；在 AI 页面保存 OpenAI 或 DeepSeek Key 后，可用于翻译、代码提取、代码解释和作业步骤拆解。工作台仍可为单次操作提供临时 Key，该 Key 不会保存。服务仅适用于本地单用户开发场景。

AI 使用 OpenAI-compatible Chat Completions 接口。OpenAI 和 DeepSeek 使用各自固定的官方 Base URL，模型 ID 可在 AI 页面设置；客户端不能通过处理请求更换上游地址。Windows DPAPI 密钥和服务偏好保存在 `%LOCALAPPDATA%/CourseMaterialLearningAssistant/`，不会纳入 ZIP 资料备份。

## 当前实现状态

- [x] Next.js + TypeScript 前端项目初始化
- [x] FastAPI 后端项目初始化
- [x] 后端 `/health` 健康检查接口
- [x] 后端基础接口和可恢复资料记录（重新生成预留）
- [x] PDF / DOCX 文件持久化和大小限制
- [x] Docling PDF / DOCX 解析与 Markdown / JSON 保存
- [x] Step 6 内容块分类、来源位置模型和结构化 Workbench JSON
- [x] Step 7 本地翻译流程、学术术语表和原文保护
- [x] Step 8 AI 处理权限、结构化输出、重试与结果校验
- [x] 上传页与 Workbench 接入资料处理 API
- [x] 双栏文本 PDF、扫描 PDF OCR、DOCX 表格/代码解析回归（自动合成样例）
- [x] Workbench 预览、导出和交互
- [x] 历史记录、设置与本地备份
- [x] Step 12 本地后台任务、进度轮询、失败恢复与重试
- [x] Step 13 上传校验、重复上传、任务范围检查、AI JSON 和代码/公式保护自动测试

## 本地回归测试

在项目根目录运行后端测试：

```powershell
Set-Location .\backend
$env:OPENBLAS_NUM_THREADS = "1"
$env:OMP_NUM_THREADS = "1"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
Set-Location ..
```

测试使用临时目录，不会修改项目的本地资料存储。POSIX 权限位测试仅在 POSIX 系统运行；本工作区的 `storage/uploads` 与 `storage/parsed` ACL 已限制为工作区所有者、服务组、SYSTEM 和管理员。自定义存储目录会继承其父目录 ACL。双栏和扫描 OCR 使用合成样例，仍建议用真实课程论文及低质量扫描件补充版面质量回归。
