# Step 6：内容分类与 Workbench 数据模型

Step 6 在 Docling 原生 JSON 之外生成应用层数据。原生解析结果继续保留，归一化数据用于定位、筛选和填充 Workbench；这一阶段不调用翻译服务或 AI。

## 分类方式

`ParsedBlock.kind` 表示 Docling 识别出的结构类型：`heading`、`text`、`list_item`、`code`、`formula`、`table`、`picture` 或 `other`。普通文本块会标为 `semantic_role: normal_text`。

作业要求属于语义判断，Docling 的结构标签无法单独确认。当前只在“作业”“课后题”“练习题”“homework”“assignment”“problem set”“exercise(s)”等明确章节标题之下，把正文和列表项标为 `assignment_candidate`。候选项带有 `classification_source` 和 `classification_confidence`，供后续确认；不会自动生成作业步骤。

代码、公式、表格和图片仍按结构类型保留，即使它们出现在作业章节中也不会被改成普通文字。代码另关联到 `CodeBlockRecord`；表格保留单元格网格数据。

## 来源位置

每个块保留稳定块 ID、文档 ID、阅读顺序、Docling 标签与引用、标题路径、提取文本和全部 provenance。每条 provenance 可含页码、页面边界框及字符范围。DOCX 或无页面坐标的内容仍会保留块引用和文档顺序，来源列表为空表示 Docling 没有提供页面位置。

页面边界框原样保留 Docling 坐标和 `coord_origin`，此处不进行单位或原点换算。

## 本地文件

解析成功后，`storage/parsed/` 会为每份资料保存：

```text
<document-id>.md                 # 可读 Markdown
<document-id>.json               # Docling 原生 JSON
<document-id>.blocks.json        # ParsedBlockCollection
<document-id>.workbench.json     # WorkbenchResult
```

资料本身沿用 `storage/uploads/<document-id>.json` 中的 `DocumentDetail`。Step 6 使用 Pydantic 模型表达 `ParsedBlock`、`TranslationRecord`、`CodeBlockRecord`、`AssignmentCandidate`、`GuideStep` 和 `WorkbenchResult`，暂不引入数据库。

## Workbench JSON

`GET /api/documents/{document_id}/workbench` 返回资料详情和版本化 Workbench 结果，其中包含：

- `parsed_blocks`：可按类型展示并回溯原文位置的内容块。
- `translations`：翻译记录列表；当前为空，留给 Step 7 填充。
- `code_blocks`：关联来源块的代码和语言；代码解释留空。
- `assignment_candidates`：基于明确作业章节标题识别的候选要求。
- `guide_steps`：初始为空，留给后续 AI 处理填充。

处理尚未完成时接口返回 `pending` 或 `failed` 状态和空列表。删除资料会一并删除原生解析结果、归一化块及 Workbench JSON。

## 边界

本阶段建立可追踪的数据结构和保守的候选分类规则。标题关键字无法理解复杂语义，Docling 对代码、公式、表格及页面位置的识别也受文件质量影响；后续阶段可以在保留原始数据与 provenance 的前提下改进分类。
