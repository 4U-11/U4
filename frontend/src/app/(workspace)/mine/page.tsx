"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type DocumentRecord = {
  id: string;
  filename: string;
  file_type: "pdf" | "docx";
  size_bytes: number | null;
  status: "pending" | "processing" | "completed" | "failed";
  created_at: string;
  error_message?: string | null;
};

type DocumentList = { items: DocumentRecord[]; total: number };

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

async function fetchDocuments(): Promise<DocumentRecord[]> {
  const response = await fetch(`${API_BASE}/api/documents`, { cache: "no-store" });
  const result = await response.json().catch(() => null);
  if (!response.ok) throw new Error(apiMessage(result, "无法读取资料列表。"));
  return ((result as DocumentList).items ?? []).sort(
    (left, right) => Date.parse(right.created_at) - Date.parse(left.created_at),
  );
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatFileSize(size: number | null) {
  if (size === null) return "大小未知";
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

const statusLabels: Record<DocumentRecord["status"], string> = {
  pending: "等待处理",
  processing: "处理中",
  completed: "已完成",
  failed: "处理失败",
};

export default function MinePage() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [busyDocumentId, setBusyDocumentId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let active = true;
    fetchDocuments()
      .then((items) => {
        if (active) setDocuments(items);
      })
      .catch((loadError: unknown) => {
        if (active) {
          setError(
            loadError instanceof Error
              ? loadError.message
              : "无法连接后端，请确认 FastAPI 正在运行。",
          );
        }
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const hasActiveDocuments = documents.some(
    (document) => document.status === "pending" || document.status === "processing",
  );

  useEffect(() => {
    if (!hasActiveDocuments) return;
    const timer = window.setInterval(() => {
      fetchDocuments().then(setDocuments).catch((loadError: unknown) => {
        setError(loadError instanceof Error ? loadError.message : "无法更新处理状态。");
      });
    }, 1500);
    return () => window.clearInterval(timer);
  }, [hasActiveDocuments]);

  async function refreshDocuments() {
    setDocuments(await fetchDocuments());
  }

  async function deleteDocument(document: DocumentRecord) {
    if (!window.confirm(`确定删除“${document.filename}”及其处理结果吗？`)) return;
    setBusyDocumentId(document.id);
    setError("");
    setNotice("");
    try {
      const response = await fetch(
        `${API_BASE}/api/documents/${encodeURIComponent(document.id)}`,
        { method: "DELETE" },
      );
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(apiMessage(result, "删除失败，请重试。"));
      await refreshDocuments();
      setNotice(`已删除 ${document.filename}。`);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "删除失败，请重试。");
    } finally {
      setBusyDocumentId(null);
    }
  }

  async function reprocessDocument(document: DocumentRecord) {
    setBusyDocumentId(document.id);
    setError("");
    setNotice("");
    try {
      const response = await fetch(
        `${API_BASE}/api/documents/${encodeURIComponent(document.id)}/regenerate`,
        { method: "POST" },
      );
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(apiMessage(result, "重新处理失败，请重试。"));
      const updated = result as DocumentRecord;
      await refreshDocuments();
      setNotice(
        updated.status === "completed"
          ? `已重新处理 ${document.filename}。`
          : `已启动 ${document.filename} 的重新解析。`,
      );
    } catch (actionError) {
      setError(
        actionError instanceof Error ? actionError.message : "重新处理失败，请重试。",
      );
    } finally {
      setBusyDocumentId(null);
    }
  }

  return (
    <main className="mine-page">
      <div className="mine-heading-row">
        <div>
          <p className="mine-eyebrow">课程材料学习助手</p>
          <h1>我的资料</h1>
          <p className="mine-list-summary">
            {isLoading ? "正在读取资料…" : `共 ${documents.length} 份课程资料`}
          </p>
        </div>
        <div className="mine-actions">
          <Link href="/upload" className="mine-button mine-button-secondary">
            <span aria-hidden="true">⇧</span>
            导入资料
          </Link>
          <Link href="/upload" className="mine-button mine-button-primary">
            <span aria-hidden="true">＋</span>
            上传资料
          </Link>
        </div>
      </div>

      {error && <p className="mine-feedback is-error" role="alert">{error}</p>}
      {notice && <p className="mine-feedback" role="status">{notice}</p>}

      <section className="mine-document-grid" aria-label="课程资料列表">
        <Link href="/upload" className="mine-new-card">
          <span className="mine-new-card-icon" aria-hidden="true">＋</span>
          <h2>添加课程资料</h2>
          <p>上传 PDF 或 DOCX，开始学习</p>
        </Link>

        {!isLoading && documents.length === 0 && (
          <div className="mine-empty-state">
            <span aria-hidden="true">▤</span>
            <h2>还没有课程资料</h2>
            <p>上传 PDF 或 DOCX 后，资料和最近一次工作台结果会保存在这里。</p>
          </div>
        )}

        {documents.map((document) => {
          const busy = busyDocumentId === document.id;
          return (
            <article className="mine-document-card" key={document.id}>
              <Link
                href={`/workbench/${encodeURIComponent(document.id)}`}
                className="mine-document-open"
                aria-label={`打开 ${document.filename} 工作台`}
              >
                <div className={`mine-document-preview is-${document.file_type}`} aria-hidden="true">
                  <div className="mine-preview-page">
                    <span className="mine-preview-label">
                      {document.file_type.toUpperCase()} · 课程资料
                    </span>
                    <strong>{document.filename}</strong>
                    <span className="mine-preview-rule" />
                    <span className="mine-preview-subtitle">学习工作台</span>
                    <span className="mine-preview-line" />
                    <span className="mine-preview-line short" />
                    <span className="mine-preview-line" />
                    <span className="mine-preview-line medium" />
                  </div>
                </div>
              </Link>

              <div className="mine-document-info">
                <div className="mine-document-meta">
                  <div className="mine-document-title-group">
                    <h2 title={document.filename}>{document.filename}</h2>
                    <p>{formatDate(document.created_at)}</p>
                  </div>
                  <span className={`mine-status is-${document.status}`}>
                    {statusLabels[document.status]}
                  </span>
                </div>
                {document.status === "failed" && document.error_message && (
                  <p className="mine-document-error">{document.error_message}</p>
                )}
                <div className="mine-document-detail-line">
                  <span>{document.file_type.toUpperCase()}</span>
                  <span>{formatFileSize(document.size_bytes)}</span>
                </div>
                <div className="mine-document-footer">
                  <Link href={`/workbench/${encodeURIComponent(document.id)}`}>
                    打开工作台 <span aria-hidden="true">→</span>
                  </Link>
                  <div className="mine-document-actions">
                    <button
                      type="button"
                      onClick={() => void reprocessDocument(document)}
                      disabled={busy || document.status === "processing" || document.status === "pending"}
                    >
                      {busy ? "处理中…" : "重新处理"}
                    </button>
                    <button
                      type="button"
                      className="is-danger"
                      onClick={() => void deleteDocument(document)}
                      disabled={busy || document.status === "processing" || document.status === "pending"}
                    >
                      删除
                    </button>
                  </div>
                </div>
              </div>
            </article>
          );
        })}
      </section>
    </main>
  );
}
