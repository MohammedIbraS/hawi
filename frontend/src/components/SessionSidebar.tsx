"use client";

import { useState, useRef, useEffect } from "react";
import { ChatSessionSummary } from "@/lib/types";
import { deleteSession, renameSession } from "@/lib/api";
import { useUI } from "@/contexts/UIContext";

interface Props {
  sessions: ChatSessionSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDeleted: (id: string) => void;
  onRenamed: (id: string, title: string) => void;
  token: string;
}

export default function SessionSidebar({
  sessions,
  activeId,
  onSelect,
  onNew,
  onDeleted,
  onRenamed,
  token,
}: Props) {
  const { t } = useUI();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editingId && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editingId]);

  async function handleDelete(e: React.MouseEvent, id: string) {
    e.stopPropagation();
    await deleteSession(token, id);
    onDeleted(id);
  }

  function startEdit(e: React.MouseEvent, s: ChatSessionSummary) {
    e.stopPropagation();
    setEditTitle(s.title ?? "");
    setEditingId(s.id);
  }

  async function commitEdit(id: string) {
    const trimmed = editTitle.trim();
    setEditingId(null);
    if (!trimmed) return;
    try {
      await renameSession(token, id, trimmed);
      onRenamed(id, trimmed);
    } catch {
      // non-fatal
    }
  }

  function handleEditKey(e: React.KeyboardEvent, id: string) {
    if (e.key === "Enter") { e.preventDefault(); commitEdit(id); }
    if (e.key === "Escape") setEditingId(null);
  }

  function formatDate(iso: string) {
    const d = new Date(iso);
    const now = new Date();
    const diffDays = Math.floor((now.getTime() - d.getTime()) / 86400000);
    if (diffDays === 0) return "Today";
    if (diffDays === 1) return "Yesterday";
    if (diffDays < 7) return `${diffDays}d ago`;
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  }

  return (
    <aside className="w-60 shrink-0 flex flex-col border-e border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 h-full">
      <div className="p-3 border-b border-gray-100 dark:border-gray-700">
        <button
          onClick={onNew}
          className="w-full flex items-center gap-2 rounded-lg border border-emerald-300 dark:border-emerald-700 bg-emerald-50 dark:bg-emerald-900/20 px-3 py-2 text-sm font-medium text-emerald-700 dark:text-emerald-400 hover:bg-emerald-100 dark:hover:bg-emerald-900/30 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path d="M12 4v16m8-8H4" />
          </svg>
          {t("chat.newChat")}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto py-2">
        {sessions.length === 0 ? (
          <p className="px-4 py-6 text-xs text-gray-400 dark:text-gray-500 text-center">
            {t("chat.noHistory")}
          </p>
        ) : (
          sessions.map((s) => (
            <div
              key={s.id}
              onClick={() => editingId !== s.id && onSelect(s.id)}
              className={`group relative flex flex-col px-3 py-2.5 mx-2 rounded-lg cursor-pointer transition-colors ${
                activeId === s.id
                  ? "bg-emerald-50 dark:bg-gray-800 text-emerald-900 dark:text-gray-100"
                  : "hover:bg-gray-50 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300"
              }`}
            >
              {editingId === s.id ? (
                <input
                  ref={inputRef}
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  onBlur={() => commitEdit(s.id)}
                  onKeyDown={(e) => handleEditKey(e, s.id)}
                  onClick={(e) => e.stopPropagation()}
                  className="text-xs font-medium w-full bg-white dark:bg-gray-700 border border-emerald-400 dark:border-emerald-600 rounded px-1.5 py-0.5 outline-none text-gray-900 dark:text-gray-100"
                  maxLength={120}
                />
              ) : (
                <span className="text-xs font-medium truncate pe-10 leading-snug">
                  {s.title ?? "New conversation"}
                </span>
              )}
              <span className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
                {formatDate(s.updated_at)}
                {s.message_count > 0 && (
                  <span className="ms-1.5">· {s.message_count / 2 | 0} msg{s.message_count > 2 ? "s" : ""}</span>
                )}
              </span>

              {/* Edit + Delete buttons on hover */}
              {editingId !== s.id && (
                <div className="absolute end-1 top-1/2 -translate-y-1/2 flex opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    onClick={(e) => startEdit(e, s)}
                    className="p-1 rounded text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                    title="Rename"
                  >
                    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536M9 11l6.586-6.586a2 2 0 112.828 2.828L11.828 13.828a2 2 0 01-1.414.586H9v-2.414a2 2 0 01.586-1.414L9 11z" />
                    </svg>
                  </button>
                  <button
                    onClick={(e) => handleDelete(e, s.id)}
                    className="p-1 rounded text-gray-400 hover:text-red-500 dark:hover:text-red-400"
                    title="Delete"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
