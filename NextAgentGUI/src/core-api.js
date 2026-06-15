async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Core request failed (${response.status})`);
  return data;
}

export const coreApi = {
  health: () => request("/api/health"),
  preflight: () => request("/api/preflight"),
  sessions: () => request("/api/sessions"),
  stats: () => request("/api/stats"),
  state: () => request("/api/state"),
  workspace: () => request("/api/workspace"),
  saveState: (payload) => request("/api/state", { method: "POST", body: JSON.stringify(payload) }),
  saveConfig: (apiKey) => request("/api/config", { method: "POST", body: JSON.stringify({ api_key: apiKey }) }),
  createSession: (payload = {}) => request("/api/sessions", { method: "POST", body: JSON.stringify(payload) }),
  chat: (messages, model, sessionId) => request("/api/chat", {
    method: "POST",
    body: JSON.stringify({ messages, model, session_id: sessionId }),
  }),
  sendMessage: (sessionId, message) => request(`/api/sessions/${sessionId}/messages`, {
    method: "POST",
    body: JSON.stringify({ message }),
  }),
};
