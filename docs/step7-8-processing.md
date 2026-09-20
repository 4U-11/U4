# Step 7–8 翻译与 AI 处理

## 翻译

`POST /api/documents/{id}/process` 接受 `{"task":"translate","target_language":"zh-CN"}`。没有用户 Key 时，后端调用 `LIBRETRANSLATE_URL` 指定的 LibreTranslate；示例配置指向 `127.0.0.1`，不会默认把资料发送到公共翻译服务。需要先在本机启动 LibreTranslate，并在项目根目录的私有 `.env` 中配置地址；若服务要求鉴权，可配置 `LIBRETRANSLATE_API_KEY`。

翻译按解析出的标题、普通文本和列表项分别进行。代码块、公式块和表格不进入普通文本翻译；段落中的反引号代码、行内公式、公式块中识别到的变量以及代码中的常见变量声明会用占位符保护。学术术语表定义在 `backend/app/translation.py`。翻译结果通过 `TranslationRecord` 写入 `<document-id>.workbench.json`，原文、Docling JSON 和内容块不会被覆盖。占位符缺失或被改写时，该块标记为翻译失败。

## AI 任务和 Key 策略

工作台提供代码提取、代码解释和作业步骤拆解；也可在提供用户 Key 时使用 AI 翻译。AI 页面可以保存 OpenAI 或 DeepSeek Key，后端使用 Windows DPAPI 加密后写入当前 Windows 用户目录；Key 不会写入项目、日志、资料记录、Workbench JSON 或 ZIP 备份。工作台也可通过 `X-User-API-Key` 请求头按次发送临时 Key，它只暂存在页面内存中。

| Key 状态 | 可执行任务 |
| --- | --- |
| 没有保存或临时用户 Key | 本地 LibreTranslate 翻译；环境变量中的平台 AI Key 只用于代码解释和作业步骤拆解 |
| 已保存 OpenAI / DeepSeek Key，或当前请求带临时 Key | AI 翻译、AI 代码提取、代码解释和作业步骤拆解 |

旧的环境变量平台配置仍可作为本地开发兜底：`PLATFORM_AI_API_KEY`、`PLATFORM_AI_BASE_URL` 和 `PLATFORM_AI_MODEL`。该 Key 不开放翻译或代码提取权限。无可用 Key 时，AI 操作返回配置提示；当前没有自动切换到本地 LLM 的实现。

AI 服务使用 OpenAI-compatible Chat Completions 接口。AI 页面支持 OpenAI 和 DeepSeek，Base URL 由服务端固定，模型 ID 可配置，处理请求不能指定上游地址。所有 AI 请求都使用 Pydantic 结构化模型校验，最多重试一次；代码来源块 ID、作业步骤来源块 ID、输出长度和条数都会校验。资料内容作为不可信引用数据输入，模型不配置工具，也不执行提取出的代码。上游响应正文和 Key 不写日志，接口只返回通用错误信息。

已保存或临时的用户 Key 使用当前选择的 OpenAI 或 DeepSeek 配置。处理目前在 API 请求内同步完成；超长的单个 AI 内容块会返回错误，稍后可从工作台重试。LibreTranslate 或 AI 返回错误时不会覆盖原文。

## 本地运行

1. 按项目说明启动 FastAPI 和 Next.js。
2. 在本机启动 LibreTranslate，并设置 `LIBRETRANSLATE_URL`；没有运行服务时，翻译记录会标记失败，用户可修复配置后重试。
3. 在 AI 页面选择 OpenAI 或 DeepSeek，填写模型 ID 和 API Key，测试连接后保存。也可以在工作台只为单次操作输入临时 Key。
4. 上传 PDF/DOCX 后，在工作台点击翻译或 AI 任务。处理结果保存在对应 Workbench JSON，重复翻译会更新相同文本块和目标语言的记录。

处理接口请求体示例：

```json
{"task":"translate","target_language":"zh-CN"}
```

`task` 还可设为 `extract_code`、`explain_code` 或 `decompose_tasks`。只有使用临时 Key 时才发送 `X-User-API-Key` 请求头；Key 不要放进 URL。已保存 Key 由后端从 DPAPI 加密存储读取。

此版本假设 FastAPI 只绑定本机回环地址，尚无登录、用户隔离或远程部署鉴权。不要将当前服务直接暴露给其他网络用户。
