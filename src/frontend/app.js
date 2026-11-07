"use strict";

const sessionStorageKey = "local-llm-system-prompt";
const chatForm = document.getElementById("chat-form");
const promptInput = document.getElementById("system-prompt");
const messageInput = document.getElementById("message-input");
const historyList = document.getElementById("chat-history");
const emptyHistory = document.getElementById("empty-history");
const sendButton = document.getElementById("send-message");
const resetButton = document.getElementById("reset-chat");
const savePromptButton = document.getElementById("save-prompt");
const appStatus = document.getElementById("app-status");
const promptStatus = document.getElementById("prompt-status");
const modelName = document.getElementById("model-name");
const modelState = document.getElementById("model-state");

let sessionReady = false;
let sending = false;

async function request(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...options,
  });
  let data;

  try {
    data = await response.json();
  } catch {
    throw new Error("サーバーから正しい応答を取得できませんでした。");
  }

  if (!response.ok) {
    throw new Error(data.error || data.detail || `HTTP ${response.status}`);
  }
  return data;
}

function setControls() {
  const enabled = sessionReady && !sending;
  promptInput.disabled = !enabled;
  savePromptButton.disabled = !enabled;
  messageInput.disabled = !enabled;
  sendButton.disabled = !enabled;
  resetButton.disabled = !enabled;
}

function showError(error) {
  appStatus.textContent = error.message || "処理に失敗しました。";
  appStatus.classList.add("is-error");
}

function clearError() {
  appStatus.textContent = "";
  appStatus.classList.remove("is-error");
}

function renderMessage(message) {
  const item = document.createElement("li");
  item.className = `message message-${message.role}`;

  const label = document.createElement("strong");
  label.className = "message-role";
  label.textContent = message.role === "user" ? "あなた" : "Assistant";

  const content = document.createElement("p");
  content.className = "message-content";
  content.textContent = message.content;

  item.append(label, content);
  historyList.append(item);
}

function renderHistory(history) {
  historyList.replaceChildren();
  if (history.length === 0) {
    historyList.append(emptyHistory);
    return;
  }
  history.forEach(renderMessage);
}

function renderModel(model) {
  modelName.textContent = model.name || model.model_id || "不明";
  const labels = {
    ready: "準備完了",
    starting: "起動中",
    stopping: "停止中",
    stopped: "停止",
    error: "エラー",
  };
  modelState.textContent = labels[model.status] || model.status;
  modelState.classList.toggle("is-error", model.status === "error");
}

async function saveSystemPrompt() {
  await request("/api/system-prompt", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ system_prompt: promptInput.value }),
  });
  localStorage.setItem(sessionStorageKey, promptInput.value);
  promptStatus.textContent = "保存しました。";
}

async function loadPage() {
  try {
    await request("/api/session", { method: "POST" });
    sessionReady = true;
    setControls();

    const savedPrompt = localStorage.getItem(sessionStorageKey);
    if (savedPrompt !== null) {
      promptInput.value = savedPrompt;
    }

    try {
      renderModel(await request("/api/models/current"));
    } catch (error) {
      modelName.textContent = "取得できません";
      modelState.textContent = "接続エラー";
      modelState.classList.add("is-error");
      showError(error);
    }

    try {
      const history = await request("/api/history");
      renderHistory(history.history);
    } catch (error) {
      showError(error);
    }

    if (!appStatus.classList.contains("is-error")) {
      appStatus.textContent = "準備完了";
    }
  } catch (error) {
    showError(error);
    appStatus.textContent = `セッションを開始できません: ${appStatus.textContent}`;
  }
}

savePromptButton.addEventListener("click", async () => {
  promptStatus.textContent = "";
  clearError();
  try {
    await saveSystemPrompt();
  } catch (error) {
    showError(error);
  }
});

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = messageInput.value;
  if (!sessionReady || sending || !message.trim()) {
    return;
  }

  sending = true;
  setControls();
  clearError();
  appStatus.textContent = "応答を生成しています...";

  try {
    await saveSystemPrompt();
    const result = await request("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    if (emptyHistory.isConnected) {
      emptyHistory.remove();
    }
    renderMessage({ role: "user", content: message });
    renderMessage({ role: "assistant", content: result.response });
    messageInput.value = "";
    appStatus.textContent = "準備完了";
    historyList.scrollTop = historyList.scrollHeight;
  } catch (error) {
    showError(error);
  } finally {
    sending = false;
    setControls();
    messageInput.focus();
  }
});

messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

resetButton.addEventListener("click", async () => {
  clearError();
  resetButton.disabled = true;
  try {
    await request("/api/reset", { method: "POST" });
    renderHistory([]);
    appStatus.textContent = "履歴をリセットしました。";
  } catch (error) {
    showError(error);
  } finally {
    setControls();
  }
});

loadPage();