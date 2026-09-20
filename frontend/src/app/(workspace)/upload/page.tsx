"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  useRef,
  useState,
  type DragEvent,
  type FormEvent,
} from "react";

type SourceMode = "file" | "link";

function apiMessage(result: unknown, fallback: string) {
  if (
    result && typeof result === "object" && "error" in result && result.error &&
    typeof result.error === "object" && "message" in result.error &&
    typeof result.error.message === "string"
  ) {
    return result.error.message;
  }
  return fallback;
}

function formatFileSize(size: number) {
  if (size < 1024 * 1024) {
    return `${Math.max(1, Math.round(size / 1024))} KB`;
  }

  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export default function UploadPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [sourceMode, setSourceMode] = useState<SourceMode>("file");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [sourceUrl, setSourceUrl] = useState("");
  const [notes, setNotes] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);

  const canSubmit =
    sourceMode === "file" ? selectedFile !== null : sourceUrl.trim() !== "";

  function chooseFile(file?: File) {
    if (!file) return;

    if (!/\.(pdf|docx)$/i.test(file.name)) {
      setSelectedFile(null);
      setErrorMessage("目前只支持 PDF 或 DOCX 文件，请重新选择。");
      setSuccessMessage("");
      return;
    }

    setSelectedFile(file);
    setErrorMessage("");
    setSuccessMessage("");
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    chooseFile(event.dataTransfer.files[0]);
  }

  function removeFile() {
    setSelectedFile(null);
    setErrorMessage("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErrorMessage("");
    setSuccessMessage("");

    if (sourceMode !== "file" || !selectedFile) {
      setErrorMessage("目前只支持上传 PDF 或 DOCX 文件，资料链接功能尚未接入。");
      return;
    }

    const formData = new FormData();
    formData.append("file", selectedFile);
    if (notes.trim()) formData.append("notes", notes.trim());

    setIsSubmitting(true);
    setUploadProgress(0);
    try {
      const apiBase =
        process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
      const result = await new Promise<unknown>((resolve, reject) => {
        const request = new XMLHttpRequest();
        request.open("POST", `${apiBase}/api/documents`);
        request.upload.onprogress = (progressEvent) => {
          if (progressEvent.lengthComputable && progressEvent.total > 0) {
            setUploadProgress(
              Math.min(100, Math.round((progressEvent.loaded / progressEvent.total) * 100)),
            );
          }
        };
        request.onerror = () => reject(new Error("上传中断，请检查网络后重试。"));
        request.onload = () => {
          let body: unknown = null;
          try {
            body = JSON.parse(request.responseText);
          } catch {
            body = null;
          }
          if (request.status < 200 || request.status >= 300) {
            reject(new Error(apiMessage(body, "上传失败，请检查后端服务后重试。")));
            return;
          }
          setUploadProgress(100);
          resolve(body);
        };
        request.send(formData);
      });
      if (
        !result || typeof result !== "object" ||
        !("id" in result) || typeof result.id !== "string" ||
        !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
          result.id,
        )
      ) {
        throw new Error("后端没有返回资料编号，请稍后重试。");
      }

      router.push(`/workbench/${encodeURIComponent(result.id)}`);
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : "上传失败，请稍后重试。",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="upload-page">
      <header className="upload-page-heading">
        <p className="upload-eyebrow">新建学习任务</p>
        <h1>添加课程资料</h1>
        <p className="upload-page-description">
          上传 PDF 或 DOCX 课程文件，再补充希望助手关注的内容。资料链接导入尚未接入。
        </p>
      </header>

      <form className="upload-form-card" onSubmit={handleSubmit}>
        <div className="upload-section-heading">
          <div>
            <h2>选择资料来源</h2>
            <p>目前支持 PDF 和 DOCX 文件。</p>
          </div>
          <span className="upload-step-label">第 1 步</span>
        </div>

        <div className="upload-mode-switch" role="tablist" aria-label="资料来源">
          <button
            id="upload-file-tab"
            type="button"
            role="tab"
            aria-selected={sourceMode === "file"}
            className={sourceMode === "file" ? "is-active" : ""}
            onClick={() => {
              setSourceMode("file");
              setErrorMessage("");
              setSuccessMessage("");
            }}
          >
            上传文件
          </button>
          <button
            id="upload-link-tab"
            type="button"
            role="tab"
            aria-selected={sourceMode === "link"}
            className={sourceMode === "link" ? "is-active" : ""}
            onClick={() => {
              setSourceMode("link");
              setErrorMessage("");
              setSuccessMessage("");
            }}
            disabled
          >
            粘贴链接（即将支持）
          </button>
        </div>

        {sourceMode === "file" ? (
          <section
            className="upload-source-panel"
            role="tabpanel"
            aria-labelledby="upload-file-tab"
          >
            <label
              className="upload-dropzone"
              htmlFor="course-file"
              onDragOver={(event) => event.preventDefault()}
              onDrop={handleDrop}
            >
              <input
                ref={fileInputRef}
                id="course-file"
                className="upload-file-input"
                type="file"
                accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                onChange={(event) => chooseFile(event.target.files?.[0])}
              />
              <span className="upload-cloud-icon" aria-hidden="true">
                ↑
              </span>
              <strong>拖放文件到这里，或点击选择</strong>
              <span className="upload-dropzone-description">
                支持 PDF、DOCX 格式
              </span>
              <span className="upload-choose-button">选择文件</span>
            </label>

            {selectedFile && (
              <div className="upload-selected-file">
                <span className="upload-file-type" aria-hidden="true">
                  {selectedFile.name.toLowerCase().endsWith(".pdf")
                    ? "PDF"
                    : "DOCX"}
                </span>
                <div className="upload-selected-file-info">
                  <strong>{selectedFile.name}</strong>
                  <span>{formatFileSize(selectedFile.size)}</span>
                </div>
                <button type="button" onClick={removeFile}>
                  移除
                </button>
              </div>
            )}
          </section>
        ) : (
          <section
            className="upload-source-panel"
            role="tabpanel"
            aria-labelledby="upload-link-tab"
          >
            <label className="upload-field-label" htmlFor="course-link">
              资料链接
            </label>
            <input
              id="course-link"
              className="upload-text-input"
              type="url"
              placeholder="https://example.com/course-material.pdf"
              value={sourceUrl}
              onChange={(event) => {
                setSourceUrl(event.target.value);
                setErrorMessage("");
                setSuccessMessage("");
              }}
              required
            />
            <p className="upload-field-hint">
              请确认链接可以直接访问资料文件。
            </p>
          </section>
        )}

        <div className="upload-divider" />

        <div className="upload-section-heading upload-notes-heading">
          <div>
            <h2>备注</h2>
            <p>告诉助手你希望重点处理的内容，例如章节范围或保留代码原文。</p>
          </div>
          <span className="upload-optional-label">选填</span>
        </div>
        <label className="visually-hidden" htmlFor="course-notes">
          资料备注
        </label>
        <textarea
          id="course-notes"
          className="upload-notes-input"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          maxLength={1000}
          placeholder="例如：请重点整理第 2 到第 4 章，保留代码和公式原文。"
          rows={5}
        />
        <div className="upload-notes-footer">
          <span>最多 1000 字，会与上传的资料一起保存</span>
          <span>{notes.length}/1000</span>
        </div>

        {errorMessage && (
          <p className="upload-feedback is-error" role="alert">
            {errorMessage}
          </p>
        )}
        {successMessage && (
          <p className="upload-feedback is-success" role="status">
            {successMessage}
          </p>
        )}

        {isSubmitting && (
          <div className="upload-progress" role="status" aria-live="polite">
            <div className="upload-progress-label">
              <span>{uploadProgress < 100 ? "正在上传文件" : "文件已上传，正在启动解析"}</span>
              <span>{uploadProgress}%</span>
            </div>
            <progress max={100} value={uploadProgress} aria-label="文件上传进度" />
          </div>
        )}

        <div className="upload-form-footer">
          <Link href="/mine" className="upload-cancel-link">
            返回我的资料
          </Link>
          <button
            className="mine-button mine-button-primary upload-submit-button"
            type="submit"
            disabled={!canSubmit || isSubmitting}
          >
            {isSubmitting ? "正在上传…" : "开始整理"}
            <span aria-hidden="true">→</span>
          </button>
        </div>
      </form>
    </main>
  );
}
