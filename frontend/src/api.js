/**
 * API client for the RoundtabLLM backend.
 *
 * Auth: All requests include the AUTH_TOKEN as a Bearer header.
 * In dev, requests are proxied by Vite to localhost:8000.
 */

const getToken = () => localStorage.getItem("roundtable_token") || "";

const headers = () => {
  const token = getToken();
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
};

export async function sendMessage({ message, conversation_id, mode, anchor, protocol, enabled_models, debate_roles, context_mode, selected_topics }) {
  const body = { message, conversation_id, mode, anchor, protocol, enabled_models, context_mode };
  if (debate_roles) body.debate_roles = debate_roles;
  if (selected_topics) body.selected_topics = selected_topics;
  const res = await fetch("/chat", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

export async function getConversations() {
  const res = await fetch("/conversations", { headers: headers() });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export async function getConversation(id) {
  const res = await fetch(`/conversations/${id}`, { headers: headers() });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

// --- Legacy context endpoints ---

export async function getContext() {
  const res = await fetch("/context", { headers: headers() });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export async function updateContext(content) {
  const res = await fetch("/context", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

// --- Memory endpoints ---

export async function getMemory() {
  const res = await fetch("/memory", { headers: headers() });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export async function getMemoryTopic(key) {
  const res = await fetch(`/memory/${key}`, { headers: headers() });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export async function updateMemoryTopic(key, content) {
  const res = await fetch(`/memory/${key}`, {
    method: "PUT",
    headers: headers(),
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

// --- AutoDream endpoints ---

export async function triggerDream(conversationIds) {
  const body = conversationIds ? { conversation_ids: conversationIds } : {};
  const res = await fetch("/memory/dream", {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(body),
  });
  if (res.status === 409) throw new Error("DREAM_LOCKED");
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

export async function getDream(id) {
  const res = await fetch(`/memory/dream/${id}`, { headers: headers() });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export async function listDreams() {
  const res = await fetch("/memory/dreams", { headers: headers() });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export async function applyDream(id, approvedIndices) {
  const res = await fetch(`/memory/dream/${id}/apply`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ approved_indices: approvedIndices }),
  });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

export async function rejectDream(id) {
  const res = await fetch(`/memory/dream/${id}/reject`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({}),
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

// --- Export ---

export async function exportConversation(id) {
  const res = await fetch(`/conversations/${id}/export`, { headers: headers() });
  if (!res.ok) throw new Error(`${res.status}`);
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="(.+)"/);
  const filename = match ? match[1] : `roundtabllm-${id}.md`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function setAuthToken(token) {
  localStorage.setItem("roundtable_token", token);
  window.location.reload();
}
