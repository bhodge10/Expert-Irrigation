/* Every call to the backend goes through here. */

async function request(path, { method = "GET", body } = {}) {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 204) return null;

  const data = await res.json().catch(() => null);

  if (!res.ok) {
    const error = new Error(readDetail(data) || "Something went wrong. Try again.");
    error.status = res.status;
    throw error;
  }
  return data;
}

/* FastAPI returns a string for our own errors and a list for validation
   failures. Pull out something a person can read either way. */
function readDetail(data) {
  const detail = data?.detail;
  if (!detail) return null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail[0]?.msg ?? null;
  return null;
}

export const api = {
  me: () => request("/auth/me"),
  login: (email, password) =>
    request("/auth/login", { method: "POST", body: { email, password } }),
  logout: () => request("/auth/logout", { method: "POST" }),

  users: () => request("/users"),

  messages: (queue, scope) =>
    request(`/messages?queue=${encodeURIComponent(queue)}&scope=${encodeURIComponent(scope)}`),
  message: (id) => request(`/messages/${id}`),

  assign: (id, assigneeId) =>
    request(`/messages/${id}/assign`, {
      method: "POST",
      body: { assignee_id: assigneeId },
    }),
  moveQueue: (id, queue) =>
    request(`/messages/${id}/queue`, { method: "POST", body: { queue } }),
  setStatus: (id, status) =>
    request(`/messages/${id}/status`, { method: "POST", body: { status } }),
  addNote: (id, bodyText) =>
    request(`/messages/${id}/notes`, {
      method: "POST",
      body: { body_text: bodyText },
    }),
  reply: (id, bodyText, markHandled) =>
    request(`/messages/${id}/reply`, {
      method: "POST",
      body: { body_text: bodyText, mark_handled: markHandled },
    }),
};
