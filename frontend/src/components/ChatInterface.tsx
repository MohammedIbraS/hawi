"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { v4 as uuidv4 } from "uuid";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ChatMessage, ChatSessionSummary, Source } from "@/lib/types";
import { streamChat, createSession, fetchSessions, fetchSessionDetail, submitFeedback } from "@/lib/api";
import SourceCard from "./SourceCard";
import SessionSidebar from "./SessionSidebar";
import { useAuth } from "@/contexts/AuthContext";
import { useUI } from "@/contexts/UIContext";

interface Props {
  entityFilter?: string;
}

const SUGGESTED_QUESTIONS = [
  "كم عدد مراكز السكري والغدد الصماء حسب المنطقة الصحية؟",
  "What is the total number of hospital beds per 1,000 population?",
  "ما هي نسبة الأطباء السعوديين في وزارة الصحة؟",
  "How many primary healthcare centers does MOH operate?",
  "ما هي أبرز المؤشرات الصحية لعام 2023؟",
  "What are the main health statistics for Hajj pilgrims?",
];

function isArabic(text: string): boolean {
  const arabicChars = (text.match(/[\u0600-\u06FF]/g) ?? []).length;
  return arabicChars / Math.max(text.length, 1) > 0.3;
}

function citedIndices(content: string): Set<number> {
  const matches = content.matchAll(/\[(\d+)\]/g);
  const indices = new Set<number>();
  for (const m of matches) indices.add(parseInt(m[1]));
  return indices;
}

function ThinkingDots() {
  return (
    <div role="status" aria-label="Thinking…" className="flex items-center gap-1.5 py-1">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="block w-2 h-2 rounded-full bg-emerald-400"
          style={{ animation: `bounce 1.2s ease-in-out ${i * 0.2}s infinite` }}
        />
      ))}
      <style>{`
        @keyframes bounce {
          0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
          40% { transform: translateY(-6px); opacity: 1; }
        }
      `}</style>
    </div>
  );
}

function WelcomeIcon() {
  return (
    <svg width="48" height="48" viewBox="0 0 48 48" fill="none" className="text-emerald-500/60 dark:text-emerald-400/40">
      <rect x="4" y="8" width="40" height="32" rx="6" stroke="currentColor" strokeWidth="2.5"/>
      <path d="M14 18h20M14 24h14" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"/>
      <circle cx="36" cy="34" r="8" fill="currentColor" fillOpacity="0.15"/>
      <path d="M33 34l2 2 4-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}

const mdComponents: React.ComponentProps<typeof ReactMarkdown>["components"] = {
  table: ({ children }) => (
    <div className="overflow-x-auto my-3">
      <table className="min-w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-emerald-50 dark:bg-emerald-900/20">{children}</thead>,
  th: ({ children }) => <th className="border border-gray-200 dark:border-gray-600 px-3 py-2 text-start font-semibold text-gray-700 dark:text-gray-300">{children}</th>,
  td: ({ children }) => <td className="border border-gray-200 dark:border-gray-600 px-3 py-2 text-gray-700 dark:text-gray-300">{children}</td>,
  tr: ({ children }) => <tr className="even:bg-gray-50 dark:even:bg-gray-700/30">{children}</tr>,
  h1: ({ children }) => <h1 className="text-base font-bold mt-4 mb-1 text-gray-900 dark:text-gray-100">{children}</h1>,
  h2: ({ children }) => <h2 className="text-sm font-bold mt-3 mb-1 text-gray-900 dark:text-gray-100">{children}</h2>,
  h3: ({ children }) => <h3 className="text-sm font-semibold mt-2 mb-1 text-gray-800 dark:text-gray-200">{children}</h3>,
  p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
  ul: ({ children }) => <ul className="list-disc list-inside mb-2 space-y-0.5">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-0.5">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-gray-900 dark:text-gray-100">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  code: ({ children }) => <code className="bg-gray-100 dark:bg-gray-700 dark:text-gray-200 rounded px-1 py-0.5 text-xs font-mono">{children}</code>,
  hr: () => <hr className="my-3 border-gray-200 dark:border-gray-700" />,
  blockquote: ({ children }) => (
    <blockquote className="border-s-4 border-emerald-300 dark:border-emerald-700 ps-3 text-gray-600 dark:text-gray-400 italic my-2">{children}</blockquote>
  ),
};

export default function ChatInterface({ entityFilter }: Props) {
  const { user, token } = useAuth();
  const { lang, t } = useUI();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  // Track which message IDs have been voted on to prevent double-voting
  const [voted, setVoted] = useState<Record<string, "up" | "down">>({});
  const [copied, setCopied] = useState<Record<string, boolean>>({});
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Load session list when user logs in
  useEffect(() => {
    if (user && token) {
      fetchSessions(token).then(setSessions).catch(() => setSessions([]));
    } else {
      setSessions([]);
      setActiveSessionId(null);
    }
  }, [user, token]);

  const startNewChat = useCallback(() => {
    setMessages([]);
    setActiveSessionId(null);
  }, []);

  const loadSession = useCallback(async (sessionId: string) => {
    if (!token) return;
    try {
      const detail = await fetchSessionDetail(token, sessionId);
      const loaded: ChatMessage[] = detail.messages.map((m) => ({
        id: uuidv4(),
        role: m.role,
        content: m.content,
        sources: (m.sources as Source[] | undefined) ?? [],
        timestamp: new Date(m.created_at),
      }));
      setMessages(loaded);
      setActiveSessionId(sessionId);
    } catch {
      // Session may have been deleted externally — silently ignore
    }
  }, [token]);

  const handleDeleted = useCallback((id: string) => {
    setSessions((prev) => prev.filter((s) => s.id !== id));
    if (activeSessionId === id) startNewChat();
  }, [activeSessionId, startNewChat]);

  const handleRenamed = useCallback((id: string, title: string) => {
    setSessions((prev) => prev.map((s) => s.id === id ? { ...s, title } : s));
  }, []);

  const handleCopy = useCallback((messageId: string, content: string) => {
    navigator.clipboard.writeText(content).then(() => {
      setCopied((prev) => ({ ...prev, [messageId]: true }));
      setTimeout(() => setCopied((prev) => ({ ...prev, [messageId]: false })), 2000);
    }).catch(() => {});
  }, []);

  const sendMessage = useCallback(async (overrideQuery?: string) => {
    const query = (overrideQuery ?? input).trim();
    if (!query || isStreaming) return;

    // Create session on first message if authenticated
    let sessionId = activeSessionId;
    if (user && token && !sessionId) {
      try {
        const s = await createSession(token);
        sessionId = s.id;
        setActiveSessionId(s.id);
        setSessions((prev) => [{
          id: s.id,
          title: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          message_count: 0,
        }, ...prev]);
      } catch {
        // non-fatal — continue without session
      }
    }

    const userMessage: ChatMessage = {
      id: uuidv4(),
      role: "user",
      content: query,
      timestamp: new Date(),
    };
    const assistantMessage: ChatMessage = {
      id: uuidv4(),
      role: "assistant",
      content: "",
      sources: [],
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    if (!overrideQuery) setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    setIsStreaming(true);

    try {
      for await (const event of streamChat(query, messages, entityFilter, sessionId ?? undefined, token ?? undefined)) {
        if (event.type === "text") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessage.id ? { ...m, content: m.content + event.content } : m
            )
          );
        } else if (event.type === "sources") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessage.id ? { ...m, sources: event.sources } : m
            )
          );
          // Update session title in sidebar after first exchange
          if (sessionId) {
            setSessions((prev) =>
              prev.map((s) =>
                s.id === sessionId && !s.title
                  ? { ...s, title: query.slice(0, 60), message_count: s.message_count + 2 }
                  : s
              )
            );
          }
        }
      }
    } finally {
      setIsStreaming(false);
    }
  }, [input, isStreaming, messages, entityFilter, activeSessionId, user, token]);

  const handleFeedback = useCallback(async (
    assistantMessageId: string,
    rating: "up" | "down",
    assistantContent: string,
    precedingQuery: string,
  ) => {
    if (voted[assistantMessageId]) return;
    setVoted((prev) => ({ ...prev, [assistantMessageId]: rating }));
    try {
      await submitFeedback({
        query: precedingQuery,
        answerExcerpt: assistantContent.slice(0, 500),
        rating,
        sessionId: activeSessionId ?? undefined,
        token: token ?? undefined,
      });
    } catch {
      // non-fatal — feedback is best-effort
    }
  }, [voted, activeSessionId, token]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    e.target.style.height = "auto";
    e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
  };

  return (
    <div className="flex h-full">
      {/* Sidebar — only for logged-in users */}
      {user && token && (
        <SessionSidebar
          sessions={sessions}
          activeId={activeSessionId}
          onSelect={loadSession}
          onNew={startNewChat}
          onDeleted={handleDeleted}
          onRenamed={handleRenamed}
          token={token}
        />
      )}

      {/* Chat area */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-6 space-y-6 bg-gray-50 dark:bg-gray-950">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center gap-5 px-6 max-w-2xl mx-auto">
              <WelcomeIcon />
              <div>
                <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-100 mb-2">{t("chat.welcome")}</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400 max-w-sm leading-relaxed">{t("chat.welcomeSub")}</p>
              </div>
              {/* Source badges */}
              <div className="flex flex-wrap justify-center gap-1.5">
                {[
                  { label: "MOH", color: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300" },
                  { label: "GASTAT", color: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300" },
                  { label: "CCHI", color: "bg-sky-100 text-sky-800 dark:bg-sky-900/30 dark:text-sky-300" },
                  { label: "SHC", color: "bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300" },
                  { label: "NHIC", color: "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300" },
                  { label: "SFDA", color: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300" },
                ].map(({ label, color }) => (
                  <span key={label} className={`text-xs font-semibold rounded-full px-2.5 py-1 ${color}`}>{label}</span>
                ))}
              </div>
              <div className="flex flex-wrap justify-center gap-2 max-w-lg">
                {SUGGESTED_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    onClick={() => sendMessage(q)}
                    dir="auto"
                    className="rounded-full border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20 px-3 py-1.5 text-xs text-emerald-800 dark:text-emerald-300 hover:bg-emerald-100 dark:hover:bg-emerald-900/40 hover:border-emerald-300 dark:hover:border-emerald-700 transition-colors text-left"
                  >
                    {q}
                  </button>
                ))}
              </div>
              {!user && (
                <p className="text-xs text-gray-400 dark:text-gray-500">
                  <a href="/login" className="text-emerald-600 dark:text-emerald-400 hover:underline">{t("nav.signIn")}</a> to save your conversations
                </p>
              )}
            </div>
          )}

          {messages.map((message, idx) => {
            const msgLang = isArabic(message.content) ? "ar" : "en";
            const isUser = message.role === "user";
            const isThinking = !isUser && message.content === "" && isStreaming;
            const cited = citedIndices(message.content);
            const filteredSources = (message.sources ?? []).filter((s) => cited.has(s.index));
            // Find the user message that preceded this assistant message
            const precedingQuery = !isUser
              ? (messages.slice(0, idx).reverse().find((m) => m.role === "user")?.content ?? "")
              : "";
            const isDone = !isUser && !isThinking && message.content.length > 0;

            return (
              <div
                key={message.id}
                dir="ltr"
                className={`flex ${isUser ? "justify-end" : "justify-start"}`}
              >
                <div
                  dir={msgLang === "ar" ? "rtl" : "ltr"}
                  className={`max-w-2xl rounded-2xl px-4 py-3 text-sm ${
                    isUser
                      ? "bg-emerald-600 text-white leading-relaxed"
                      : "bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-800 dark:text-gray-100 shadow-sm"
                  }`}
                >
                  {isUser ? (
                    <p className="whitespace-pre-wrap">{message.content}</p>
                  ) : isThinking ? (
                    <ThinkingDots />
                  ) : (
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                      {message.content}
                    </ReactMarkdown>
                  )}
                  {!isUser && filteredSources.length > 0 && (
                    <SourceCard sources={filteredSources} />
                  )}
                  {isDone && (
                    <div className="flex items-center gap-1 mt-2 pt-2 border-t border-gray-100 dark:border-gray-700">
                      {/* Copy button */}
                      <button
                        onClick={() => handleCopy(message.id, message.content)}
                        title={copied[message.id] ? "Copied!" : "Copy answer"}
                        className="p-1 rounded text-gray-300 dark:text-gray-600 hover:text-gray-500 dark:hover:text-gray-400 transition-colors me-1"
                      >
                        {copied[message.id] ? (
                          <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="text-emerald-500"><polyline points="20 6 9 17 4 12"/></svg>
                        ) : (
                          <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                        )}
                      </button>
                      <span className="text-xs text-gray-400 dark:text-gray-500 me-1">
                        {lang === "ar" ? "مفيد؟" : "Helpful?"}
                      </span>
                      {(["up", "down"] as const).map((rating) => {
                        const isVoted = voted[message.id] === rating;
                        const wasVoted = !!voted[message.id];
                        return (
                          <button
                            key={rating}
                            onClick={() => handleFeedback(message.id, rating, message.content, precedingQuery)}
                            disabled={wasVoted}
                            title={rating === "up" ? "Good answer" : "Poor answer"}
                            className={`p-1 rounded transition-colors ${
                              isVoted
                                ? rating === "up" ? "text-emerald-600" : "text-red-500"
                                : wasVoted
                                ? "text-gray-200 dark:text-gray-600 cursor-default"
                                : "text-gray-300 dark:text-gray-600 hover:text-gray-500 dark:hover:text-gray-400"
                            }`}
                          >
                            {rating === "up" ? (
                              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill={isVoted ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3H14z"/><path d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>
                            ) : (
                              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill={isVoted ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3H10z"/><path d="M17 2h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/></svg>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 px-4 py-4">
          <div className="flex items-end gap-3 max-w-3xl mx-auto">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={handleInput}
              onKeyDown={handleKeyDown}
              placeholder={t("chat.placeholder")}
              rows={1}
              dir="auto"
              className="flex-1 resize-none rounded-xl border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-4 py-3 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
              style={{ maxHeight: "120px" }}
            />
            <button
              onClick={() => sendMessage()}
              disabled={!input.trim() || isStreaming}
              className="rounded-xl bg-emerald-600 px-4 py-3 text-white text-sm font-medium hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {isStreaming ? (
                <span className="flex items-center gap-1">
                  {[0, 1, 2].map((i) => (
                    <span key={i} className="w-1.5 h-1.5 bg-white rounded-full animate-bounce"
                      style={{ animationDelay: `${i * 150}ms` }} />
                  ))}
                </span>
              ) : t("chat.send")}
            </button>
          </div>
          <p className="text-xs text-gray-400 dark:text-gray-500 text-center mt-2">
            {t("chat.disclaimer")}
          </p>
        </div>
      </div>
    </div>
  );
}
