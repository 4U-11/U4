# Step 5 学习指南：接入 Docling 文件解析

Step 5 在 Step 4 保存原始文件的基础上，接入本地 Docling，将 PDF / DOCX 转换成 Markdown 和 Docling 原生 JSON，并把结果保存在 `storage/parsed/`。

## 1. 安装依赖

从项目根目录安装后端依赖：

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Set-Location ..
```

`backend/requirements.txt` 固定了 Docling 版本。PDF 解析首次运行时会准备版面分析和 OCR 模型文件；默认 OCR 引擎可能从 ModelScope 下载模型。网络受限时，可先准备模型文件，再配置离线模型路径。

## 2. 解析流程

```text
POST /api/documents
        ↓
校验文件类型、大小和文件签名
        ↓
把原文件和 pending 资料记录保存到 storage/uploads/
        ↓
记录 processing 状态，在线程池中运行 Docling
        ↓
原子写入 Markdown 和 Docling JSON
        ↓
将资料状态更新为 completed；失败则保留原文件并记录 failed
```

Docling 转换代码集中在 `backend/app/parser.py`。转换器只允许 PDF 和 DOCX；解析结果分别导出为 Markdown 和 `DoclingDocument` 原生 JSON。Markdown 导出会遍历图片条目，以保留扫描 PDF 中挂在整页图片下的 OCR 文本。同步解析期间，文件仍保存在原始上传目录中。

## 3. 本地文件

上传和解析成功后，每份资料会有以下文件：

```text
storage/uploads/<document-id>.pdf 或 .docx  # 原件
storage/uploads/<document-id>.json           # 资料信息、处理状态和备注
storage/parsed/<document-id>.md               # Markdown
storage/parsed/<document-id>.json             # Docling 原生结构化结果
storage/parsed/<document-id>.blocks.json      # Step 6 归一化内容块
storage/parsed/<document-id>.workbench.json   # Step 6 Workbench 数据
```

磁盘路径只使用服务端生成的 UUID，不使用用户文件名。结果先写到 `.part` 临时文件，再改为正式文件名，避免把半成品当成成功结果。

结构化 JSON 保留 Docling 的文档模型，包括文本元素、表格、图片条目、页面和元素来源信息。来源信息可包含页码和页面坐标。Markdown 便于直接阅读；JSON 用于后续 Step 6 分类和建立 Workbench 数据模型。Docling 的识别结果会受 PDF 排版、字体和扫描质量影响，不能假定每个文件都能完整识别。

Step 6 在不覆盖 Docling 原始 JSON 的前提下，额外写入归一化块集合和 Workbench JSON。模型字段与候选分类规则见 [Step 6 内容模型说明](./step6-content-model.md)。

## 4. 状态和接口

- `completed`：原文件和两种解析结果都已保存。
- `failed`：原文件仍保留，解析错误说明写入资料记录；详细异常只写入后端日志。
- Docling 返回部分结果时仍保存可用内容，并在后端日志记录部分成功状态。
- 上传接口返回 `201` 表示资料已保存；同步解析结束后，响应里的 `status` 是最终状态。
- `GET /api/documents/{document_id}/status` 查看处理状态。
- `GET /api/documents/{document_id}/parsed` 读取 Markdown 和结构化 JSON。
- 删除资料时会同时删除原文件、解析结果和资料记录。

`GET .../parsed` 仅在状态为 `completed` 且两个结果文件都存在时返回结果。失败或尚未解析的资料会返回统一格式的错误响应。

## 5. 手动验证

启动后端：

```powershell
Set-Location .\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000/docs>：

1. 调用 `POST /api/documents` 上传 PDF 或 DOCX。
2. 确认响应是 `201`，并查看状态是否为 `completed`。
3. 在 `storage/uploads/` 和 `storage/parsed/` 中确认文件以响应里的 ID 命名。
4. 调用 `GET /api/documents/{document_id}/parsed`，检查 Markdown 和 JSON 内容。
5. 重启后端，再查详情和解析结果，确认本地记录仍能读取。
6. 上传无效或损坏的 PDF / DOCX，确认资料保留为 `failed`，并且解析错误没有删除原文件。
7. 删除资料，确认原文件、记录和解析输出都被清理。

进一步回归时，还应使用双栏论文、含代码文件和扫描 PDF 验证版面、代码块、表格、公式、图片条目、页码和 OCR 结果。仓库当前提供的样例文件为 `frontend/public/samples/Prac_3.pdf`。

## 6. 当前边界

- 第一版上传请求内同步解析；大型文件和后台任务队列留到 Step 12。
- 前端上传页和 Workbench 仍是演示界面；当前通过 FastAPI 接口读取结果。
- 此阶段保存 Docling 原生结构，不负责将内容分类成作业要求、翻译、代码解释等业务数据；这些属于后续步骤。
- 图片条目和来源信息会保存在结构化结果中；Workbench 中展示页面图片或独立图片资源还需要后续补充资源导出和前端预览。
