"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type PanelId = "source" | "guide" | "code";
type TaskName = "translate" | "extract_code" | "explain_code" | "decompose_tasks";
type WorkbenchViewMode = "preview" | "content";
type ProcessingTask = {
  id: string;
  document_id: string;
  task: TaskName;
  status: "pending" | "processing" | "completed" | "failed";
  progress_percent: number;
  error_message: string | null;
};

type ParsedBlock = {
  id: string;
  kind: string;
  text: string | null;
  heading_path: string[];
  code_language: string | null;
  source: { page_no: number | null }[];
};

type TranslationRecord = {
  id: string;
  block_id: string;
  source_text: string;
  translated_text: string | null;
  target_language: string;
  status: "pending" | "completed" | "failed";
  method: "libretranslate" | "ai" | null;
  error_code: string | null;
};

type CodeBlockRecord = {
  id: string;
  block_id: string;
  code: string;
  language: string | null;
  explanation: string | null;
};

type GuideStep = {
  id: string;
  order: number;
  title: string;
  description: string;
  source_block_ids: string[];
};

type WorkbenchData = {
  document_id: string;
  workbench_status: "pending" | "ready" | "failed";
  generated_at: string;
  parsed_blocks: ParsedBlock[];
  translations: TranslationRecord[];
  code_blocks: CodeBlockRecord[];
  assignment_candidates: { id: string; block_id: string; text: string }[];
  guide_steps: GuideStep[];
  document: {
    id: string;
    filename: string;
    file_type: "pdf" | "docx";
    status: "pending" | "processing" | "completed" | "failed";
    processing_stage: "uploading" | "queued" | "parsing" | "saving" | "completed" | "failed";
    processing_progress_percent: number;
    error_message?: string | null;
  };
};

function apiMessage(result: unknown, fallback: string) {
  if (
    result &&
    typeof result === "object" &&
    "error" in result &&
    result.error &&
    typeof result.error === "object" &&
    "message" in result.error &&
    typeof result.error.message === "string"
  ) {
    return result.error.message;
  }
  return fallback;
}

async function fetchWorkbench(documentId: string): Promise<WorkbenchData> {
  const response = await fetch(
    `${API_BASE}/api/documents/${encodeURIComponent(documentId)}/workbench`,
    { cache: "no-store" },
  );
  const result = await response.json().catch(() => null);
  if (!response.ok) throw new Error(apiMessage(result, "无法读取工作台数据。"));
  return result as WorkbenchData;
}

async function waitForProcessingTask(
  documentId: string,
  taskId: string,
  onUpdate: (task: ProcessingTask) => void,
) {
  while (true) {
    const response = await fetch(
      `${API_BASE}/api/documents/${encodeURIComponent(documentId)}/tasks/${encodeURIComponent(taskId)}`,
      { cache: "no-store" },
    );
    const result = await response.json().catch(() => null);
    if (!response.ok) throw new Error(apiMessage(result, "无法读取处理任务状态。"));
    const task = result as ProcessingTask;
    onUpdate(task);
    if (task.status === "completed") return;
    if (task.status === "failed") {
      throw new Error(task.error_message ?? "处理任务失败，可以重新运行。 ");
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1200));
  }
}

async function waitForParsedWorkbench(documentId: string) {
  while (true) {
    const result = await fetchWorkbench(documentId);
    if (result.document.status === "completed" || result.document.status === "failed") {
      return result;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1200));
  }
}

function downloadFile(filename: string, contents: string, mimeType: string) {
  const blob = new Blob([contents], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function safeFilename(filename: string) {
  return filename.replace(/[/\\?%*:|"<>]/g, "_").replace(/\s+/g, " ");
}

function buildMarkdown(data: WorkbenchData) {
  const translatedByBlock = new Map(
    data.translations
      .filter((item) => item.status === "completed" && item.translated_text)
      .map((item) => [item.block_id, item.translated_text]),
  );
  const lines = [`# ${data.document.filename}`, "", `类型：${data.document.file_type.toUpperCase()}`, ""];

  lines.push("## 原文与翻译", "");
  for (const block of data.parsed_blocks) {
    if (!block.text || block.kind === "picture" || block.kind === "other") continue;
    if (block.heading_path.length) lines.push(`### ${block.heading_path.join(" / ")}`, "");
    lines.push(block.text, "");
    const translation = translatedByBlock.get(block.id);
    if (translation) lines.push(`> ${translation}`, "");
  }

  lines.push("## 作业要求", "");
  for (const candidate of data.assignment_candidates) lines.push(`- ${candidate.text}`);
  lines.push("", "## 分步指南", "");
  for (const step of data.guide_steps) {
    lines.push(`${step.order}. **${step.title}**`, `   ${step.description}`, "");
  }

  lines.push("## 代码", "");
  for (const code of data.code_blocks) {
    lines.push(`### ${code.language ?? "代码"}`, "", `\`\`\`${code.language ?? ""}`, code.code, "\`\`\`", "");
    if (code.explanation) lines.push(`解释：${code.explanation}`, "");
  }
  return lines.join("\n");
}

function PanelToolbar({
  title,
  subtitle,
  panelId,
  isMaximized,
  onToggle,
}: {
  title: string;
  subtitle: string;
  panelId: PanelId;
  isMaximized: boolean;
  onToggle: (panelId: PanelId) => void;
}) {
  return (
    <header className="workbench-panel-toolbar">
      <div className="workbench-panel-title">
        <h2 id={`workbench-${panelId}-title`}>{title}</h2>
        <p>{subtitle}</p>
      </div>
      <button
        className="workbench-expand-button"
        type="button"
        aria-label={isMaximized ? `还原${title}面板` : `放大${title}面板`}
        aria-pressed={isMaximized}
        onClick={() => onToggle(panelId)}
      >
        <span aria-hidden="true">{isMaximized ? "⤡" : "⛶"}</span>
        {isMaximized ? "还原" : "放大"}
      </button>
    </header>
  );
}

export default function WorkbenchView({ documentId }: { documentId: string }) {
  const [data, setData] = useState<WorkbenchData | null>(null);
  const [expandedPanel, setExpandedPanel] = useState<PanelId | null>(null);
  const [viewMode, setViewMode] = useState<WorkbenchViewMode>("preview");
  const [userApiKey, setUserApiKey] = useState("");
  const [targetLanguage, setTargetLanguage] = useState("zh-CN");
  const [busyTask, setBusyTask] = useState<TaskName | null>(null);
  const [processingTaskStatus, setProcessingTaskStatus] = useState<"pending" | "processing" | null>(null);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    async function refresh() {
      try {
        const result = await fetchWorkbench(documentId);
        if (!active) return;
        setData(result);
        setIsLoading(false);
        if (result.document.status === "pending" || result.document.status === "processing") {
          timer = window.setTimeout(() => void refresh(), 1200);
        }
      } catch (loadError) {
        if (active) {
          setError(
            loadError instanceof Error
              ? loadError.message
              : "无法连接后端，请确认 FastAPI 正在运行。",
          );
          setIsLoading(false);
        }
      }
    }
    void refresh();
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [documentId]);

  useEffect(() => {
    if (!expandedPanel) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setExpandedPanel(null);
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [expandedPanel]);

  const translationsByBlock = useMemo(() => {
    const matching = (data?.translations ?? []).filter(
      (translation) => translation.target_language === targetLanguage,
    );
    return new Map(matching.map((translation) => [translation.block_id, translation]));
  }, [data?.translations, targetLanguage]);

  const sourceBlocks = (data?.parsed_blocks ?? []).filter(
    (block) => block.text && block.kind !== "picture" && block.kind !== "other",
  );
  const fileUrl = `${API_BASE}/api/documents/${encodeURIComponent(documentId)}/file`;
  const isReady = data?.document.status === "completed";

  function togglePanel(panelId: PanelId) {
    setExpandedPanel((current) => (current === panelId ? null : panelId));
  }

  async function copyText(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text);
      setMessage(`${label}已复制。`);
      setError("");
    } catch {
      setError("复制失败，请检查浏览器剪贴板权限后重试。");
    }
  }

  async function runTask(task: TaskName) {
    setBusyTask(task);
    setProcessingTaskStatus("pending");
    setError("");
    setMessage("");
    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      const key = userApiKey.trim();
      if (key) headers["X-User-API-Key"] = key;
      const response = await fetch(
        `${API_BASE}/api/documents/${encodeURIComponent(documentId)}/process`,
        {
          method: "POST",
          headers,
          body: JSON.stringify({ task, target_language: targetLanguage }),
        },
      );
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(apiMessage(result, "处理失败，请重试。"));
      const processTask = result as ProcessingTask;
      await waitForProcessingTask(documentId, processTask.id, (status) => {
        if (status.status === "pending" || status.status === "processing") {
          setProcessingTaskStatus(status.status);
        }
      });
      const refreshed = await fetchWorkbench(documentId);
      setData(refreshed);
      if (task === "translate") {
        const failedCount = refreshed.translations.filter(
          (item) => item.target_language === targetLanguage && item.status === "failed",
        ).length;
        setMessage(
          failedCount
            ? `翻译已完成，${failedCount} 个内容块失败。检查本地翻译服务后可重试。`
            : "翻译完成，原文保持不变。",
        );
      } else if (task === "extract_code") {
        setMessage("代码提取完成；提取内容尚未执行。结果已保存。 ");
      } else if (task === "explain_code") {
        setMessage("代码解释已更新并保存。 ");
      } else {
        setMessage("作业步骤已更新并保存。 ");
      }
    } catch (taskError) {
      setError(taskError instanceof Error ? taskError.message : "处理失败，请稍后重试。");
    } finally {
      setBusyTask(null);
      setProcessingTaskStatus(null);
    }
  }

  async function reprocessDocument() {
    setIsRegenerating(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch(
        `${API_BASE}/api/documents/${encodeURIComponent(documentId)}/regenerate`,
        { method: "POST" },
      );
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(apiMessage(result, "重新处理失败，请重试。"));
      const refreshed = await waitForParsedWorkbench(documentId);
      setData(refreshed);
      setMessage(
        refreshed.document.status === "completed"
          ? "原文件已重新解析，工作台结果已更新。"
          : "重新处理失败，请检查文件后重试。",
      );
    } catch (taskError) {
      setError(taskError instanceof Error ? taskError.message : "重新处理失败，请重试。");
    } finally {
      setIsRegenerating(false);
    }
  }

  function exportResults(format: "json" | "md") {
    if (!data) return;
    const base = safeFilename(data.document.filename.replace(/\.[^.]+$/, ""));
    if (format === "json") {
      downloadFile(`${base}-workbench.json`, `${JSON.stringify(data, null, 2)}\n`, "application/json;charset=utf-8");
    } else {
      downloadFile(`${base}-workbench.md`, buildMarkdown(data), "text/markdown;charset=utf-8");
    }
    setMessage("工作台结果已导出。 ");
    setError("");
  }

  const allCode = (data?.code_blocks ?? [])
    .map((block) => block.code)
    .filter(Boolean)
    .join("\n\n");

  return (
    <main className="workbench-page">
      <header className="workbench-topbar">
        <div>
          <Link href="/mine" className="workbench-back-link">
            <span aria-hidden="true">←</span>
            我的资料
          </Link>
          <div className="workbench-document-heading">
            <h1>{data?.document.filename ?? "工作台"}</h1>
            <span>
              {data
                ? `${data.document.file_type.toUpperCase()} · ${
                    data.document.status === "completed"
                      ? "已解析"
                      : data.document.status === "failed"
                        ? "解析失败"
                        : "处理中"
                  }`
                : isLoading
                  ? "正在读取资料"
                  : "无法读取资料"}
            </span>
          </div>
        </div>
        <div className="workbench-topbar-actions">
          <button
            type="button"
            onClick={() => void reprocessDocument()}
            disabled={isRegenerating || busyTask !== null}
          >
            {isRegenerating ? "重新解析中…" : "重新处理"}
          </button>
          <button type="button" onClick={() => exportResults("md")} disabled={!data}>
            导出 Markdown
          </button>
          <button type="button" onClick={() => exportResults("json")} disabled={!data}>
            导出 JSON
          </button>
        </div>
      </header>

      <section className="workbench-process-controls" aria-label="翻译和 AI 处理">
        <div className="workbench-process-options">
          <label className="workbench-key-field" htmlFor="workbench-user-key">
            <span>本次操作使用的用户 API Key（可选）</span>
            <input
              id="workbench-user-key"
              type="password"
              value={userApiKey}
              onChange={(event) => setUserApiKey(event.target.value)}
              autoComplete="off"
              spellCheck={false}
              maxLength={4096}
              placeholder="留空时使用本地翻译，平台 AI 仅解释代码和拆解作业"
            />
          </label>
          <label className="workbench-language-field" htmlFor="workbench-language">
            <span>目标语言</span>
            <select
              id="workbench-language"
              value={targetLanguage}
              onChange={(event) => setTargetLanguage(event.target.value)}
            >
              <option value="zh-CN">简体中文</option>
              <option value="en">English</option>
            </select>
          </label>
        </div>
        <p className="workbench-key-note">
          Key 只保留在此页面内存中，并仅随当前处理请求发送；关闭或离开页面后即清除。
        </p>
        <div className="workbench-action-buttons">
          <button type="button" onClick={() => void runTask("translate")} disabled={!isReady || busyTask !== null || isRegenerating}>
            {busyTask === "translate" ? "翻译中…" : "翻译普通文本"}
          </button>
          <button type="button" onClick={() => void runTask("extract_code")} disabled={!isReady || busyTask !== null || isRegenerating || !userApiKey.trim()}>
            {busyTask === "extract_code" ? "提取中…" : "AI 提取代码 · 需用户 Key"}
          </button>
          <button type="button" onClick={() => void runTask("explain_code")} disabled={!isReady || busyTask !== null || isRegenerating}>
            {busyTask === "explain_code" ? "解释中…" : "解释代码"}
          </button>
          <button type="button" onClick={() => void runTask("decompose_tasks")} disabled={!isReady || busyTask !== null || isRegenerating}>
            {busyTask === "decompose_tasks" ? "拆解中…" : "拆解作业步骤"}
          </button>
          <button type="button" onClick={() => void copyText(allCode, "全部代码")} disabled={!allCode}>
            复制全部代码
          </button>
        </div>
        {error && <p className="workbench-feedback is-error" role="alert">{error}</p>}
        {message && <p className="workbench-feedback" role="status">{message}</p>}
        {busyTask && (
          <p className="workbench-feedback" role="status" aria-live="polite">
            {processingTaskStatus === "pending" ? "任务已排队，等待处理…" : "后台任务处理中…"}
          </p>
        )}
      </section>

      {data?.document.status === "failed" && data.document.error_message && (
        <p className="workbench-feedback is-error" role="status">{data.document.error_message}</p>
      )}
      {data && (data.document.status === "pending" || data.document.status === "processing") && (
        <div className="workbench-feedback" role="status" aria-live="polite">
          <p>
            {data.document.processing_stage === "saving"
              ? "解析完成，正在保存工作台结果…"
              : data.document.processing_stage === "queued"
                ? "资料已保存，等待解析任务启动…"
                : "正在解析课程资料…"}
          </p>
          <progress
            max={100}
            value={data.document.processing_progress_percent}
            aria-label="资料解析阶段"
          />
        </div>
      )}

      <div className="workbench-grid">
        <section
          className={`workbench-panel workbench-pdf-panel${expandedPanel === "source" ? " is-maximized" : ""}`}
          aria-labelledby="workbench-source-title"
        >
          <PanelToolbar
            title="原文件与翻译"
            subtitle={`${sourceBlocks.length} 个文本块`}
            panelId="source"
            isMaximized={expandedPanel === "source"}
            onToggle={togglePanel}
          />
          <div className="workbench-panel-body workbench-pdf-body">
            <div className="workbench-view-switch" role="tablist" aria-label="原文件显示模式">
              <button
                type="button"
                role="tab"
                aria-selected={viewMode === "preview"}
                className={viewMode === "preview" ? "is-active" : ""}
                onClick={() => setViewMode("preview")}
              >
                文件预览
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={viewMode === "content"}
                className={viewMode === "content" ? "is-active" : ""}
                onClick={() => setViewMode("content")}
              >
                解析内容
              </button>
            </div>

            <div className="workbench-pdf-columns">
              <section className="workbench-document-pane" aria-label="原文件预览">
                <div className="workbench-pane-label">
                  <span>{viewMode === "preview" ? "原文件" : "原文"}</span>
                  {data && (
                    <a href={fileUrl} target="_blank" rel="noreferrer">
                      {data.document.file_type === "pdf" ? "在新窗口打开" : "下载 DOCX"}
                    </a>
                  )}
                </div>
                {viewMode === "preview" && data?.document.file_type === "pdf" ? (
                  <iframe
                    className="workbench-pdf-frame"
                    src={`${fileUrl}#page=1&toolbar=1`}
                    title={`${data.document.filename} PDF 预览`}
                  />
                ) : viewMode === "preview" ? (
                  <div className="workbench-docx-preview">
                    <div className="workbench-docx-page">
                      <span className="workbench-docx-label">DOCX · 解析预览</span>
                      {sourceBlocks.slice(0, 12).map((block) => (
                        <p className={block.kind === "heading" ? "is-heading" : ""} key={block.id}>
                          {block.text}
                        </p>
                      ))}
                      {sourceBlocks.length === 0 && <p>解析完成后，这里会显示 DOCX 的文本预览。</p>}
                    </div>
                  </div>
                ) : (
                  <div className="workbench-panel-body workbench-result-list workbench-source-list">
                    {sourceBlocks.map((block) => (
                      <article className="workbench-result-card" key={block.id}>
                        {block.heading_path.length > 0 && (
                          <p className="workbench-source-path">{block.heading_path.join(" / ")}</p>
                        )}
                        <pre className="workbench-source-text">{block.text}</pre>
                      </article>
                    ))}
                    {sourceBlocks.length === 0 && <p className="workbench-empty-hint">没有可显示的文本内容。</p>}
                  </div>
                )}
              </section>

              <section className="workbench-translation-pane" aria-label="中文翻译">
                <div className="workbench-pane-label">
                  <span>{targetLanguage === "zh-CN" ? "中文翻译" : "English translation"}</span>
                  <span className="workbench-demo-label">最近一次处理结果</span>
                </div>
                <div className="workbench-panel-body workbench-result-list">
                  {sourceBlocks.map((block) => {
                    const translation = translationsByBlock.get(block.id);
                    if (!translation && viewMode === "preview") return null;
                    return (
                      <article className="workbench-result-card" key={block.id}>
                        {block.heading_path.length > 0 && (
                          <p className="workbench-source-path">{block.heading_path.join(" / ")}</p>
                        )}
                        {translation?.status === "completed" && translation.translated_text ? (
                          <pre className="workbench-source-text">{translation.translated_text}</pre>
                        ) : translation?.status === "failed" ? (
                          <p className="workbench-translation-failed">此内容块翻译失败，可检查配置后重试。</p>
                        ) : (
                          <p className="workbench-empty-hint">尚无此段的译文</p>
                        )}
                      </article>
                    );
                  })}
                  {viewMode === "preview" &&
                    !sourceBlocks.some((block) => translationsByBlock.has(block.id)) && (
                      <div className="workbench-translation-empty">
                        <span className="workbench-translation-icon" aria-hidden="true">文</span>
                        <h3>尚无翻译</h3>
                        <p>点击“翻译普通文本”，译文会保存在工作台并显示在这里。</p>
                      </div>
                    )}
                </div>
              </section>
            </div>
          </div>
        </section>

        <section
          className={`workbench-panel${expandedPanel === "guide" ? " is-maximized" : ""}`}
          aria-labelledby="workbench-guide-title"
        >
          <PanelToolbar
            title="作业步骤"
            subtitle={`${data?.assignment_candidates.length ?? 0} 个候选要求`}
            panelId="guide"
            isMaximized={expandedPanel === "guide"}
            onToggle={togglePanel}
          />
          <div className="workbench-panel-body workbench-guide-body">
            {(data?.assignment_candidates.length ?? 0) > 0 && (
              <div className="workbench-assignment-candidates">
                <strong>识别到的作业要求</strong>
                {data?.assignment_candidates.map((candidate) => (
                  <p key={candidate.id}>{candidate.text}</p>
                ))}
              </div>
            )}
            {data?.guide_steps.length ? (
              <ol className="workbench-guide-list">
                {data.guide_steps.map((step) => (
                  <li key={step.id}>
                    <span>{String(step.order).padStart(2, "0")}</span>
                    <div>
                      <strong>{step.title}</strong>
                      <p>{step.description}</p>
                      <small>来源块：{step.source_block_ids.join(", ")}</small>
                    </div>
                  </li>
                ))}
              </ol>
            ) : (
              <div className="workbench-translation-empty">
                <h3>暂无步骤</h3>
                <p>如果解析到作业要求，点击“拆解作业步骤”生成带来源引用的学习指引。</p>
              </div>
            )}
          </div>
        </section>

        <section
          className={`workbench-panel workbench-code-panel${expandedPanel === "code" ? " is-maximized" : ""}`}
          aria-labelledby="workbench-code-title"
        >
          <PanelToolbar
            title="代码与解释"
            subtitle={`${data?.code_blocks.length ?? 0} 个代码块`}
            panelId="code"
            isMaximized={expandedPanel === "code"}
            onToggle={togglePanel}
          />
          <div className="workbench-panel-body workbench-result-list">
            {data?.code_blocks.length ? (
              data.code_blocks.map((block) => (
                <article className="workbench-result-card" key={block.id}>
                  <div className="workbench-code-card-heading">
                    <span>{block.language ?? "代码"}</span>
                    <button type="button" onClick={() => void copyText(block.code, "代码")}>
                      复制代码
                    </button>
                  </div>
                  <pre className="workbench-code-text"><code>{block.code}</code></pre>
                  {block.explanation ? (
                    <div className="workbench-code-explanation">
                      <strong>代码解释</strong>
                      <p>{block.explanation}</p>
                    </div>
                  ) : null}
                </article>
              ))
            ) : (
              <div className="workbench-translation-empty">
                <h3>暂无代码块</h3>
                <p>解析出的代码会显示在这里；也可以提供用户 Key，使用 AI 从普通文本中提取。</p>
              </div>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
