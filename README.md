# 课程材料学习助手

面向 PDF 和 DOCX 课程资料的本地学习工具。项目包含 Next.js 前端和 FastAPI 后端，支持资料上传与解析、文本翻译、代码提取和解释、作业步骤生成、历史记录及本地备份。

## 功能

- 上传 PDF / DOCX，校验格式、文件内容和大小，并在本机保存原件。
- 使用 Docling 解析文档，保留 Markdown、结构化 JSON、内容分类和来源信息；PDF 支持 OCR。
- 将解析内容整理为 Workbench 结果，展示原文、译文、代码和作业步骤，并支持重新处理与导出。
- 普通文本可连接本机 LibreTranslate；翻译时保护代码、公式和变量占位符。
- 可配置 OpenAI 或 DeepSeek，用于翻译、代码提取与解释、作业拆解。未配置用户密钥时，平台 AI 仅开放代码解释和作业步骤任务。
- 提供 Mine 历史记录、处理状态轮询、失败重试、AI 设置和 ZIP 备份/恢复。
- API 密钥在 Windows 上使用 DPAPI 加密后保存在当前用户本地配置目录；API 不返回已保存的密钥，资料 ZIP 备份也不包含密钥。

## 技术栈

- 前端：Next.js 16、React 19、TypeScript、Tailwind CSS
- 后端：Python、FastAPI、Uvicorn、Docling
- 本地持久化：项目内 `storage/uploads/` 和 `storage/parsed/`；AI 设置保存在当前用户本地配置目录

## 目录结构

```text
.
├── backend/
│   ├── app/                 # FastAPI、解析、内容模型、翻译、AI、备份等
│   ├── tests/               # 后端回归测试
│   └── requirements.txt
├── docs/                    # Docling、数据模型和处理流程说明
├── frontend/
│   ├── src/app/             # 页面与路由
│   └── public/samples/      # 页面示例资料
├── storage/
│   ├── uploads/             # 上传原件与资料记录
│   └── parsed/              # 解析结果、Workbench 与任务状态
├── .env.example
├── README.md
└── step.md                  # 开发步骤与当前进度
```

## 环境要求

- Windows、PowerShell
- Node.js 和 npm
- Python 3.10 或更高版本
- LibreTranslate（仅在需要本地文本翻译时运行；默认连接 `http://127.0.0.1:5000`）

## 安装

在项目根目录打开 PowerShell。

安装前端依赖：

```powershell
Set-Location .\frontend
npm.cmd install
Set-Location ..
```

创建 Python 虚拟环境并安装后端依赖：

```powershell
Set-Location .\backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Set-Location ..
```

## 配置

复制根目录 `.env.example` 为 `.env`，按需修改配置。默认情况下，后端在项目根目录读取 `.env`，相对存储路径也以项目根目录为准。

常用配置：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | 前端调用的后端地址 |
| `BACKEND_HOST` | `127.0.0.1` | 后端监听地址 |
| `BACKEND_PORT` | `8000` | 后端端口 |
| `UPLOAD_DIR` | `./storage/uploads` | 上传文件和资料记录目录 |
| `PARSED_DIR` | `./storage/parsed` | 解析结果和任务状态目录 |
| `MAX_UPLOAD_SIZE_MB` | `50` | 单文件大小上限 |
| `LIBRETRANSLATE_URL` | `http://127.0.0.1:5000` | 本机 LibreTranslate 服务地址 |
| `LIBRETRANSLATE_API_KEY` | 空 | LibreTranslate 可选密钥 |
| `PLATFORM_AI_API_KEY` | 空 | 可选的平台 AI 服务端密钥 |

也可以在应用的 AI 设置页面配置 OpenAI 或 DeepSeek 用户密钥。不要把真实密钥提交到 Git 或写入 `.env.example`。Windows DPAPI 密钥存储依赖当前 Windows 用户环境。

## 启动

前后端分别在两个 PowerShell 终端运行，命令从项目根目录开始。

终端一：启动后端。

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

后端健康检查：<http://127.0.0.1:8000/health>

API 交互文档：<http://127.0.0.1:8000/docs>

终端二：启动前端。

```powershell
Set-Location .\frontend
npm.cmd run dev
```

打开 <http://localhost:3000>。停止服务时，在对应终端按 `Ctrl+C`。

## 本地测试与检查

运行后端回归测试：

```powershell
Set-Location .\backend
$env:OPENBLAS_NUM_THREADS = "1"
$env:OMP_NUM_THREADS = "1"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

运行前端 lint 和 TypeScript 类型检查：

```powershell
Set-Location .\frontend
npm.cmd run lint
npx.cmd tsc --noEmit
```

回归测试包括 PDF / DOCX 上传校验、重复上传、Docling 双栏 PDF / OCR / DOCX 表格与代码解析、任务重试和范围校验、翻译占位符保护、AI JSON 校验及密钥日志保护。POSIX 文件权限位测试在 Windows 上会跳过。真实课程资料的版面质量仍建议单独验证。

## 数据与 API 概览

- `storage/uploads/` 保存上传原件和资料记录。
- `storage/parsed/` 保存 Markdown、Docling JSON、归一化内容块、Workbench 结果和处理任务状态。
- 上传接口返回 `202`，文档解析在 FastAPI 本地后台任务中执行；前端轮询处理状态。解析失败时原文件保留，并可重试。
- 资料 API 使用 `/api/documents` 前缀；处理任务可通过资料详情下的任务接口查询。完整路由与参数见 `/docs`。
- AI 设置路由为 `/api/settings/ai`；备份使用 `/api/backup/export` 和 `/api/backup/import`。
- 本地 ZIP 备份包含资料及处理结果，不包含 AI 密钥；导入会跳过已存在的资料。

## 当前范围与限制

项目按本地单用户场景设计，没有登录和多用户隔离。后台任务使用 FastAPI 进程内任务机制，适合单机开发，不适用于多实例生产队列。没有部署配置或生产环境保障；上线前需另行设计数据库、对象存储、任务队列、访问控制、监控和备份策略。

更多开发进度见 [step.md](./step.md)，处理和数据模型说明见 [docs](./docs/)。
