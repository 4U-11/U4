"use client";

import { useEffect, useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const DATABASE_NAME = "course-material-learning-assistant";
const STORE_NAME = "backup-handles";
const DIRECTORY_HANDLE_KEY = "backup-directory";

type WritableFile = {
  write: (chunk: Uint8Array) => Promise<void>;
  close: () => Promise<void>;
  abort?: () => Promise<void>;
};
type BackupFileHandle = {
  createWritable: () => Promise<WritableFile>;
};
type BackupDirectoryHandle = {
  name: string;
  queryPermission: (options: { mode: "readwrite" }) => Promise<PermissionState>;
  requestPermission: (options: { mode: "readwrite" }) => Promise<PermissionState>;
  getFileHandle: (name: string, options: { create: boolean }) => Promise<BackupFileHandle>;
};
type DirectoryPickerWindow = Window & {
  showDirectoryPicker?: (options: { mode: "readwrite" }) => Promise<BackupDirectoryHandle>;
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
  if (
    result &&
    typeof result === "object" &&
    "message" in result &&
    typeof result.message === "string"
  ) {
    return result.message;
  }
  return fallback;
}

function openHandleDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE_NAME, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE_NAME)) {
        request.result.createObjectStore(STORE_NAME);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("无法读取浏览器备份设置。"));
  });
}

async function storeDirectoryHandle(handle: BackupDirectoryHandle) {
  const database = await openHandleDatabase();
  await new Promise<void>((resolve, reject) => {
    const transaction = database.transaction(STORE_NAME, "readwrite");
    transaction.objectStore(STORE_NAME).put(handle, DIRECTORY_HANDLE_KEY);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error ?? new Error("无法保存文件夹授权。"));
    transaction.onabort = () => reject(transaction.error ?? new Error("无法保存文件夹授权。"));
  });
  database.close();
}

async function loadDirectoryHandle(): Promise<BackupDirectoryHandle | null> {
  const database = await openHandleDatabase();
  const handle = await new Promise<BackupDirectoryHandle | null>((resolve, reject) => {
    const transaction = database.transaction(STORE_NAME, "readonly");
    const request = transaction.objectStore(STORE_NAME).get(DIRECTORY_HANDLE_KEY);
    request.onsuccess = () => resolve((request.result as BackupDirectoryHandle | undefined) ?? null);
    request.onerror = () => reject(request.error ?? new Error("无法读取浏览器备份设置。"));
  });
  database.close();
  return handle;
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function backupFilename() {
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  return `course-material-backup-${timestamp}.zip`;
}

export default function SettingsPage() {
  const [directoryHandle, setDirectoryHandle] = useState<BackupDirectoryHandle | null>(null);
  const [directoryStatus, setDirectoryStatus] = useState("尚未配置备份文件夹");
  const [message, setMessage] = useState("");
  const [messageIsError, setMessageIsError] = useState(false);
  const [busyAction, setBusyAction] = useState<"choose" | "backup" | "restore" | null>(null);
  const importInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;
    if (!("indexedDB" in window)) return;
    loadDirectoryHandle()
      .then(async (handle) => {
        if (!active || !handle) return;
        setDirectoryHandle(handle);
        const permission = await handle.queryPermission({ mode: "readwrite" });
        if (active) {
          setDirectoryStatus(
            permission === "granted"
              ? `已授权：${handle.name}`
              : `已选择：${handle.name}（备份时需要重新授权）`,
          );
        }
      })
      .catch(() => {
        if (active) setDirectoryStatus("尚未配置备份文件夹");
      });
    return () => {
      active = false;
    };
  }, []);

  async function chooseDirectory() {
    setBusyAction("choose");
    setMessage("");
    setMessageIsError(false);
    try {
      const picker = window as DirectoryPickerWindow;
      if (!picker.showDirectoryPicker) {
        setMessage("当前浏览器不支持文件夹授权，可以使用 ZIP 下载和导入。 ");
        return;
      }
      const handle = await picker.showDirectoryPicker({ mode: "readwrite" });
      await storeDirectoryHandle(handle);
      setDirectoryHandle(handle);
      setDirectoryStatus(`已授权：${handle.name}`);
      setMessage("备份文件夹已保存到当前浏览器。之后可以直接备份到该文件夹。");
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setMessage(error instanceof Error ? error.message : "无法授权备份文件夹。");
      setMessageIsError(true);
    } finally {
      setBusyAction(null);
    }
  }

  async function createBackup() {
    setBusyAction("backup");
    setMessage("");
    setMessageIsError(false);
    try {
      let canWriteToDirectory = false;
      if (directoryHandle) {
        let permission = await directoryHandle.queryPermission({ mode: "readwrite" });
        if (permission !== "granted") {
          permission = await directoryHandle.requestPermission({ mode: "readwrite" });
        }
        canWriteToDirectory = permission === "granted";
      }

      const response = await fetch(`${API_BASE}/api/backup/export`, { cache: "no-store" });
      if (!response.ok) {
        const result = await response.json().catch(() => null);
        throw new Error(apiMessage(result, "生成备份失败，请重试。"));
      }
      const filename = backupFilename();
      if (canWriteToDirectory && directoryHandle && response.body) {
        const fileHandle = await directoryHandle.getFileHandle(filename, { create: true });
        const writable = await fileHandle.createWritable();
        const reader = response.body.getReader();
        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            if (value) await writable.write(value);
          }
          await writable.close();
        } catch (error) {
          await writable.abort?.();
          throw error;
        }
        setMessage(`备份已写入“${directoryHandle.name}”。API Key 不会包含在备份中。`);
      } else {
        const blob = await response.blob();
        triggerDownload(blob, filename);
        setMessage(
          directoryHandle
            ? "文件夹授权已失效，已改为下载 ZIP 备份。"
            : "ZIP 备份已开始下载。API Key 不会包含在备份中。",
        );
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "生成备份失败，请重试。");
      setMessageIsError(true);
    } finally {
      setBusyAction(null);
    }
  }

  async function restoreBackup(file: File | undefined) {
    if (!file) return;
    setBusyAction("restore");
    setMessage("");
    setMessageIsError(false);
    try {
      const body = new FormData();
      body.append("file", file, file.name);
      const response = await fetch(`${API_BASE}/api/backup/import`, {
        method: "POST",
        body,
      });
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(apiMessage(result, "恢复备份失败，文件未导入。"));
      setMessage(apiMessage(result, "备份已恢复。"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "恢复备份失败，文件未导入。");
      setMessageIsError(true);
    } finally {
      setBusyAction(null);
      if (importInput.current) importInput.current.value = "";
    }
  }

  return (
    <main className="settings-page">
      <h1>设置</h1>

      <section className="settings-sync-card" aria-labelledby="sync-title">
        <div className="settings-sync-heading">
          <span className="settings-folder-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              <path
                d="M3.5 6.75A1.75 1.75 0 0 1 5.25 5h4.1l1.85 2h7.55A1.75 1.75 0 0 1 20.5 8.75v8.5A1.75 1.75 0 0 1 18.75 19h-13.5A1.75 1.75 0 0 1 3.5 17.25v-10.5Z"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinejoin="round"
              />
            </svg>
          </span>
          <div>
            <h2 id="sync-title">本地备份</h2>
            <p>备份原始课件、解析结果和最近一次工作台数据。API Key 不会导出。</p>
          </div>
        </div>

        <div className="settings-sync-divider" />

        <div className="settings-folder-row">
          <div className="settings-folder-status" aria-live="polite">
            {directoryStatus}
          </div>
          <button className="settings-folder-button" type="button" onClick={() => void chooseDirectory()} disabled={busyAction !== null}>
            {busyAction === "choose" ? "正在授权…" : "选择文件夹"}
          </button>
        </div>

        <div className="settings-backup-actions">
          <button type="button" onClick={() => void createBackup()} disabled={busyAction !== null}>
            {busyAction === "backup" ? "正在备份…" : "立即备份"}
          </button>
          <button type="button" className="is-secondary" onClick={() => importInput.current?.click()} disabled={busyAction !== null}>
            {busyAction === "restore" ? "正在恢复…" : "从 ZIP 恢复"}
          </button>
          <input
            ref={importInput}
            type="file"
            accept=".zip,application/zip"
            className="settings-file-input"
            onChange={(event) => void restoreBackup(event.target.files?.[0])}
          />
        </div>

        <p className="settings-backup-help">
          导入采用合并方式；已存在的资料会跳过，不会覆盖。浏览器不支持文件夹授权时，“立即备份”会下载 ZIP。
        </p>

        {message && (
          <p className={`settings-preview-message${messageIsError ? " is-error" : ""}`} role={messageIsError ? "alert" : "status"}>
            {message}
          </p>
        )}
      </section>
    </main>
  );
}
