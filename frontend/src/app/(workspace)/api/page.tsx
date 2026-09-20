"use client";

import { useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const providers = [
  {
    id: "openai",
    name: "OpenAI",
    symbol: "◎",
    tone: "openai",
    baseUrl: "https://api.openai.com/v1",
    exampleModel: "gpt-4o-mini",
  },
  {
    id: "deepseek",
    name: "DeepSeek",
    symbol: "◈",
    tone: "deepseek",
    baseUrl: "https://api.deepseek.com",
    exampleModel: "deepseek-flash",
  },
] as const;

type ProviderId = (typeof providers)[number]["id"];
type ProviderProfile = {
  name: string;
  base_url: string;
  model: string;
  has_api_key: boolean;
};
type AISettings = {
  provider: ProviderId;
  profiles: Record<ProviderId, ProviderProfile>;
  configured: boolean;
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

async function requestSettings(): Promise<AISettings> {
  const response = await fetch(`${API_BASE}/api/settings/ai`, { cache: "no-store" });
  const result = await response.json().catch(() => null);
  if (!response.ok) throw new Error(apiMessage(result, "无法读取 AI 配置。"));
  return result as AISettings;
}

export default function ApiPage() {
  const [selectedProviderId, setSelectedProviderId] = useState<ProviderId>("openai");
  const [model, setModel] = useState("gpt-4o-mini");
  const [apiKey, setApiKey] = useState("");
  const [hasApiKey, setHasApiKey] = useState(false);
  const [isKeyVisible, setIsKeyVisible] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [feedbackIsError, setFeedbackIsError] = useState(false);
  const [busyAction, setBusyAction] = useState<"load" | "test" | "save" | "delete" | null>("load");
  const [loadError, setLoadError] = useState("");

  const selectedProvider = providers.find((provider) => provider.id === selectedProviderId) ?? providers[0];

  useEffect(() => {
    let active = true;
    requestSettings()
      .then((result) => {
        if (!active) return;
        setSelectedProviderId(result.provider);
        const profile = result.profiles[result.provider];
        setModel(profile.model);
        setHasApiKey(profile.has_api_key);
        setLoadError("");
      })
      .catch((error: unknown) => {
        if (active) {
          setLoadError(error instanceof Error ? error.message : "无法读取 AI 配置。");
        }
      })
      .finally(() => {
        if (active) setBusyAction(null);
      });
    return () => {
      active = false;
    };
  }, []);

  function selectProvider(providerId: ProviderId) {
    setSelectedProviderId(providerId);
    setApiKey("");
    setIsKeyVisible(false);
    setFeedback("");
    setFeedbackIsError(false);
    void requestSettings()
      .then((result) => {
        const profile = result.profiles[providerId];
        setModel(profile.model);
        setHasApiKey(profile.has_api_key);
      })
      .catch((error: unknown) => {
        setFeedback(error instanceof Error ? error.message : "无法读取服务商配置。");
        setFeedbackIsError(true);
      });
  }

  async function runAction(action: "test" | "save" | "delete") {
    setBusyAction(action);
    setFeedback("");
    setFeedbackIsError(false);
    try {
      let response: Response;
      if (action === "test") {
        response = await fetch(`${API_BASE}/api/settings/ai/test`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider: selectedProviderId, model: model.trim(), api_key: apiKey.trim() || null }),
        });
      } else if (action === "save") {
        response = await fetch(`${API_BASE}/api/settings/ai`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider: selectedProviderId, model: model.trim(), api_key: apiKey.trim() || null }),
        });
      } else {
        response = await fetch(`${API_BASE}/api/settings/ai/${selectedProviderId}/key`, {
          method: "DELETE",
        });
      }
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(apiMessage(result, "操作失败，请检查配置后重试。"));

      if (action === "save") {
        setApiKey("");
        setHasApiKey(Boolean((result as { has_api_key?: boolean }).has_api_key));
      } else if (action === "delete") {
        setApiKey("");
        setHasApiKey(Boolean((result as { has_api_key?: boolean }).has_api_key));
      }
      setFeedback(apiMessage(result, action === "test" ? "连接成功。" : "操作完成。"));
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : "操作失败，请重试。");
      setFeedbackIsError(true);
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <main className="api-page">
      <header className="api-page-heading">
        <span className={`api-status-badge${hasApiKey ? " is-configured" : " is-unconfigured"}`}>
          <span aria-hidden="true" />
          {hasApiKey ? "服务商已配置" : "尚未配置 API Key"}
        </span>
        <h1>AI 模型</h1>
        <p>
          配置 OpenAI 或 DeepSeek 的 Chat Completions 接口。API Key 加密保存在本机 Windows 用户凭据下，不会进入项目文件或备份包。
        </p>
      </header>

      {loadError && <p className="api-feedback is-error" role="alert">{loadError}</p>}

      <section className="api-settings-panel" aria-label="AI 服务商配置">
        <aside className="api-provider-picker">
          <div className="api-provider-picker-heading">
            <h2>AI 服务商</h2>
            <p>选择要在工作台中使用的服务商</p>
          </div>

          <div className="api-provider-list">
            {providers.map((provider) => (
              <button
                key={provider.id}
                type="button"
                className={`api-provider-option${selectedProviderId === provider.id ? " is-selected" : ""}`}
                aria-pressed={selectedProviderId === provider.id}
                onClick={() => selectProvider(provider.id)}
              >
                <span className={`api-provider-symbol tone-${provider.tone}`} aria-hidden="true">{provider.symbol}</span>
                <span className="api-provider-option-copy">
                  <strong>{provider.name}</strong>
                  <span>{provider.id === selectedProviderId && hasApiKey ? "已保存密钥" : "OpenAI 兼容接口"}</span>
                </span>
                {selectedProviderId === provider.id && <span className="api-provider-check" aria-hidden="true">✓</span>}
              </button>
            ))}
          </div>
        </aside>

        <div className="api-provider-detail">
          <div className="api-provider-detail-heading">
            <div className="api-provider-title-group">
              <span className={`api-provider-symbol api-provider-symbol-large tone-${selectedProvider.tone}`} aria-hidden="true">
                {selectedProvider.symbol}
              </span>
              <div>
                <h2>{selectedProvider.name}</h2>
                <p>API Base URL：<code>{selectedProvider.baseUrl}</code></p>
              </div>
            </div>
            <span className={`api-config-state${hasApiKey ? " is-configured" : ""}`}>{hasApiKey ? "已配置" : "未配置"}</span>
          </div>

          <div className="api-key-section">
            <label htmlFor="provider-model">模型 ID</label>
            <div className="api-key-input-row">
              <input
                id="provider-model"
                type="text"
                value={model}
                onChange={(event) => setModel(event.target.value)}
                autoComplete="off"
                spellCheck={false}
                placeholder={`例如 ${selectedProvider.exampleModel}`}
                maxLength={128}
              />
            </div>

            <label htmlFor="provider-api-key" className="api-secondary-label">API Key</label>
            <div className="api-key-input-row">
              <input
                id="provider-api-key"
                type={isKeyVisible ? "text" : "password"}
                value={apiKey}
                onChange={(event) => {
                  setApiKey(event.target.value);
                  setFeedback("");
                }}
                autoComplete="new-password"
                spellCheck={false}
                placeholder={hasApiKey ? "已保存密钥；留空可保留现有密钥" : `填写 ${selectedProvider.name} API Key`}
                maxLength={4096}
              />
              <button
                type="button"
                className="api-key-visibility"
                aria-label={isKeyVisible ? "隐藏 API Key" : "显示 API Key"}
                aria-pressed={isKeyVisible}
                onClick={() => setIsKeyVisible((visible) => !visible)}
              >
                {isKeyVisible ? "隐藏" : "显示"}
              </button>
            </div>
            <p className="api-key-helper">
              密钥仅发给所选服务商用于连接测试和 AI 处理。测试不会保存密钥；保存后可在此删除。
            </p>

            <div className="api-config-actions">
              <button type="button" onClick={() => void runAction("test")} disabled={busyAction !== null || !model.trim()}>
                {busyAction === "test" ? "正在测试…" : "测试连接"}
              </button>
              <button type="button" className="is-primary" onClick={() => void runAction("save")} disabled={busyAction !== null || !model.trim()}>
                {busyAction === "save" ? "正在保存…" : "保存配置"}
              </button>
              <button type="button" className="is-danger" onClick={() => void runAction("delete")} disabled={busyAction !== null || !hasApiKey}>
                {busyAction === "delete" ? "正在删除…" : "删除已保存 Key"}
              </button>
            </div>
          </div>

          {feedback && (
            <p className={`api-feedback${feedbackIsError ? " is-error" : ""}`} role={feedbackIsError ? "alert" : "status"}>
              {feedback}
            </p>
          )}
        </div>
      </section>
    </main>
  );
}
