import { Source, ChatMessage, EntityInfo, AuthUser, TokenResponse, DocumentsResponse, ChatSessionSummary, ChatSessionDetail } from "./types";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export async function* streamChat(
  query: string,
  chatHistory: ChatMessage[],
  entityFilter?: string,
  sessionId?: string,
  token?: string,
): AsyncGenerator<{ type: "text"; content: string } | { type: "sources"; sources: Source[] } | { type: "error"; content: string }> {
  const history = chatHistory.map((m) => ({
    role: m.role,
    content: m.content,
  }));

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(`${BACKEND_URL}/api/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      query,
      chat_history: history,
      entity_filter: entityFilter ?? null,
      session_id: sessionId ?? null,
    }),
  });

  if (!response.ok) {
    yield { type: "error", content: "Failed to connect to the server." };
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) return;

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const raw = line.slice(6).trim();
      if (raw === "[DONE]") return;
      try {
        const parsed = JSON.parse(raw);
        yield parsed;
      } catch {
        // skip malformed lines
      }
    }
  }
}

export async function fetchEntities(): Promise<EntityInfo[]> {
  const res = await fetch(`${BACKEND_URL}/api/documents/entities`);
  if (!res.ok) return [];
  return res.json();
}

export async function fetchDocuments(params: {
  entity?: string;
  doc_type?: string;
  search?: string;
  page?: number;
  page_size?: number;
}): Promise<DocumentsResponse> {
  const qs = new URLSearchParams();
  if (params.entity) qs.set("entity", params.entity);
  if (params.doc_type) qs.set("doc_type", params.doc_type);
  if (params.search) qs.set("search", params.search);
  if (params.page) qs.set("page", String(params.page));
  if (params.page_size) qs.set("page_size", String(params.page_size));

  const res = await fetch(`${BACKEND_URL}/api/documents?${qs}`);
  if (!res.ok) return { total: 0, page: 1, page_size: 24, items: [] };
  return res.json();
}

export async function authRegister(
  email: string,
  password: string,
  full_name?: string,
): Promise<TokenResponse> {
  const res = await fetch(`${BACKEND_URL}/api/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, full_name }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Registration failed" }));
    throw new Error(err.detail ?? "Registration failed");
  }
  return res.json();
}

export async function authLogin(
  email: string,
  password: string,
): Promise<TokenResponse> {
  const res = await fetch(`${BACKEND_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Invalid credentials" }));
    throw new Error(err.detail ?? "Invalid credentials");
  }
  return res.json();
}

export async function createSession(token: string): Promise<{ id: string }> {
  const res = await fetch(`${BACKEND_URL}/api/sessions`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!res.ok) throw new Error("Failed to create session");
  return res.json();
}

export async function fetchSessions(token: string): Promise<ChatSessionSummary[]> {
  const res = await fetch(`${BACKEND_URL}/api/sessions`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) return [];
  return res.json();
}

export async function fetchSessionDetail(token: string, sessionId: string): Promise<ChatSessionDetail> {
  const res = await fetch(`${BACKEND_URL}/api/sessions/${sessionId}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Session not found");
  return res.json();
}

export async function deleteSession(token: string, sessionId: string): Promise<void> {
  await fetch(`${BACKEND_URL}/api/sessions/${sessionId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function renameSession(token: string, sessionId: string, title: string): Promise<ChatSessionSummary> {
  const res = await fetch(`${BACKEND_URL}/api/sessions/${sessionId}`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error("Failed to rename session");
  return res.json();
}

export async function submitFeedback(params: {
  query: string;
  answerExcerpt?: string;
  rating: "up" | "down";
  comment?: string;
  sessionId?: string;
  token?: string;
}): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (params.token) headers["Authorization"] = `Bearer ${params.token}`;
  await fetch(`${BACKEND_URL}/api/feedback`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      query: params.query,
      answer_excerpt: params.answerExcerpt,
      rating: params.rating,
      comment: params.comment,
      session_id: params.sessionId,
    }),
  });
}

export async function authMe(token: string): Promise<AuthUser> {
  const res = await fetch(`${BACKEND_URL}/api/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Not authenticated");
  return res.json();
}
