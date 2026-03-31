/**
 * API client for the roundtable backend.
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

export async function sendMessage({ message, conversation_id, mode, anchor, protocol, enabled_models, debate_roles }) {
  const body = { message, conversation_id, mode, anchor, protocol, enabled_models };
  if (debate_roles) body.debate_roles = debate_roles;
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
