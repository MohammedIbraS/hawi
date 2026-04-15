"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import * as XLSX from "xlsx";
import { fetchDocuments, fetchEntities } from "@/lib/api";
import { DocumentSummary, EntityInfo } from "@/lib/types";
import { useUI } from "@/contexts/UIContext";

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

const ENTITY_COLORS: Record<string, string> = {
  MOH: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300",
  GASTAT: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
  SFDA: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300",
  NHIC: "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300",
  SHC: "bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-300",
  CCHI: "bg-sky-100 text-sky-800 dark:bg-sky-900/30 dark:text-sky-300",
  SCHS: "bg-gray-100 text-gray-700 dark:bg-gray-700/50 dark:text-gray-300",
  WEQAYA: "bg-teal-100 text-teal-800 dark:bg-teal-900/30 dark:text-teal-300",
};

/** Returns dot color class and human-readable staleness label for an ISO date string. */
function freshnessInfo(dateStr: string | null): { dot: string; label: string } {
  if (!dateStr) return { dot: "bg-gray-300 dark:bg-gray-600", label: "Never updated" };
  const days = Math.floor((Date.now() - new Date(dateStr).getTime()) / 86_400_000);
  if (days <= 7)  return { dot: "bg-emerald-500", label: days === 0 ? "Updated today" : `Updated ${days}d ago` };
  if (days <= 30) return { dot: "bg-amber-400",   label: `Updated ${days}d ago` };
  if (days <= 90) return { dot: "bg-orange-500",  label: `Updated ${days}d ago` };
  // Older than 90 days — show month/year
  const fmt = new Date(dateStr).toLocaleDateString("en-GB", { year: "numeric", month: "short" });
  return { dot: "bg-red-400", label: `Last: ${fmt}` };
}

function fileUrl(docId: string) {
  return `${BACKEND_URL}/api/documents/${docId}/file`;
}

function DocTypeIcon({ type }: { type: string }) {
  if (type === "excel") {
    return (
      <span className="text-green-600 text-xs font-bold bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded px-1.5 py-0.5">
        XLS
      </span>
    );
  }
  return (
    <span className="text-red-600 text-xs font-bold bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded px-1.5 py-0.5">
      PDF
    </span>
  );
}

// ---------------------------------------------------------------------------
// Excel sheet viewer (SheetJS)
// ---------------------------------------------------------------------------

interface SheetData {
  name: string;
  html: string;
}

function ExcelViewer({ docId }: { docId: string }) {
  const [sheets, setSheets] = useState<SheetData[]>([]);
  const [activeSheet, setActiveSheet] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");

    fetch(fileUrl(docId))
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.arrayBuffer();
      })
      .then((buf) => {
        if (cancelled) return;
        const wb = XLSX.read(buf, { type: "array" });
        const parsed: SheetData[] = wb.SheetNames.map((name) => ({
          name,
          html: XLSX.utils.sheet_to_html(wb.Sheets[name], { header: "", footer: "" }),
        }));
        setSheets(parsed);
        setActiveSheet(0);
      })
      .catch((e) => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [docId]);

  if (loading) return <ViewerSpinner />;
  if (error) return <ViewerError message={error} />;
  if (!sheets.length) return <ViewerError message="No sheets found in this file." />;

  return (
    <div className="flex flex-col h-full">
      {/* Sheet tabs */}
      {sheets.length > 1 && (
        <div className="flex gap-1 px-3 pt-2 pb-0 border-b border-gray-200 dark:border-gray-700 overflow-x-auto shrink-0">
          {sheets.map((s, i) => (
            <button
              key={s.name}
              onClick={() => setActiveSheet(i)}
              className={`px-3 py-1.5 text-xs font-medium rounded-t-lg border border-b-0 transition-colors whitespace-nowrap ${
                i === activeSheet
                  ? "bg-white dark:bg-gray-900 border-gray-200 dark:border-gray-700 text-emerald-700 dark:text-emerald-400"
                  : "bg-gray-100 dark:bg-gray-800 border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200"
              }`}
            >
              {s.name}
            </button>
          ))}
        </div>
      )}
      {/* Table */}
      <div className="flex-1 overflow-auto p-3 text-xs">
        <style>{`
          .xlsx-table table { border-collapse: collapse; width: 100%; }
          .xlsx-table td, .xlsx-table th {
            border: 1px solid #e5e7eb; padding: 4px 8px;
            white-space: nowrap; vertical-align: top;
          }
          .dark .xlsx-table td, .dark .xlsx-table th { border-color: #374151; color: #d1d5db; }
          .xlsx-table tr:nth-child(even) td { background: #f9fafb; }
          .dark .xlsx-table tr:nth-child(even) td { background: #1f2937; }
        `}</style>
        <div
          className="xlsx-table"
          dangerouslySetInnerHTML={{ __html: sheets[activeSheet].html }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// PDF viewer
// ---------------------------------------------------------------------------

function PdfViewer({ docId }: { docId: string }) {
  const [loaded, setLoaded] = useState(false);
  return (
    <div className="relative h-full">
      {!loaded && <ViewerSpinner />}
      <iframe
        src={fileUrl(docId)}
        className="w-full h-full border-0"
        title="PDF viewer"
        onLoad={() => setLoaded(true)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function ViewerSpinner() {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-gray-400 dark:text-gray-500 bg-gray-100 dark:bg-gray-950">
      <svg className="animate-spin w-8 h-8 text-emerald-500" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
      </svg>
      <p className="text-sm">Loading document…</p>
    </div>
  );
}

function ViewerError({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center h-full text-center text-gray-400 dark:text-gray-500 p-8">
      <div>
        <div className="text-3xl mb-3">⚠️</div>
        <p className="text-sm">Could not load document.</p>
        <p className="text-xs mt-1 text-gray-300 dark:text-gray-600">{message}</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Document viewer modal
// ---------------------------------------------------------------------------

function DocumentViewer({ doc, onClose }: { doc: DocumentSummary; onClose: () => void }) {
  const backdropRef = useRef<HTMLDivElement>(null);
  const title = doc.title_en || doc.title_ar || "Untitled Document";
  const entityColor = ENTITY_COLORS[doc.entity] ?? "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300";
  const isExcel = doc.doc_type === "excel";

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = ""; };
  }, []);

  return (
    <div
      ref={backdropRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
      onClick={(e) => { if (e.target === backdropRef.current) onClose(); }}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div className="relative flex flex-col w-full max-w-5xl h-[90vh] bg-white dark:bg-gray-900 rounded-2xl shadow-2xl overflow-hidden">

        {/* Header */}
        <div className="flex items-start gap-3 px-4 py-3 border-b border-gray-200 dark:border-gray-700 shrink-0">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-0.5">
              <span className={`text-xs font-semibold rounded-full px-2 py-0.5 ${entityColor}`}>
                {doc.entity}
              </span>
              <DocTypeIcon type={doc.doc_type} />
            </div>
            <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate" title={title}>
              {title}
            </p>
            {doc.title_ar && doc.title_en && (
              <p dir="rtl" className="text-xs text-gray-500 dark:text-gray-400 truncate text-right">
                {doc.title_ar}
              </p>
            )}
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <a
              href={doc.original_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-1.5 text-xs text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
            >
              <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
              Open original
            </a>
            <button
              onClick={onClose}
              aria-label="Close viewer"
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            >
              <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="relative flex-1 overflow-hidden bg-gray-100 dark:bg-gray-950">
          {isExcel ? <ExcelViewer docId={doc.id} /> : <PdfViewer docId={doc.id} />}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Document card
// ---------------------------------------------------------------------------

function DocumentCard({ doc, onView }: { doc: DocumentSummary; onView: (doc: DocumentSummary) => void }) {
  const title = doc.title_en || doc.title_ar || "Untitled Document";
  const titleAr = doc.title_ar && doc.title_en ? doc.title_ar : null;
  const entityColor = ENTITY_COLORS[doc.entity] ?? "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300";
  const date = doc.last_fetched_at
    ? new Date(doc.last_fetched_at).toLocaleDateString("en-GB", { year: "numeric", month: "short" })
    : null;

  return (
    <button
      onClick={() => onView(doc)}
      className="group flex flex-col text-left bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-4 hover:border-emerald-300 dark:hover:border-emerald-600 hover:shadow-md transition-all duration-150 w-full"
    >
      <div className="flex items-center justify-between mb-3">
        <span className={`text-xs font-semibold rounded-full px-2 py-0.5 ${entityColor}`}>
          {doc.entity}
        </span>
        <DocTypeIcon type={doc.doc_type} />
      </div>
      <p className="text-sm font-medium text-gray-900 dark:text-gray-100 leading-snug group-hover:text-emerald-700 dark:group-hover:text-emerald-400 transition-colors line-clamp-3 flex-1">
        {title}
      </p>
      {titleAr && (
        <p dir="rtl" className="text-xs text-gray-500 dark:text-gray-400 mt-1 line-clamp-2 text-right">
          {titleAr}
        </p>
      )}
      <div className="flex items-center justify-between mt-3 pt-3 border-t border-gray-100 dark:border-gray-700">
        {date ? <span className="text-xs text-gray-400 dark:text-gray-500">{date}</span> : <span />}
        <svg
          aria-hidden="true"
          className="w-3.5 h-3.5 text-gray-300 dark:text-gray-600 group-hover:text-emerald-500 transition-colors"
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
        </svg>
      </div>
    </button>
  );
}

function SkeletonCard() {
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 p-4 animate-pulse">
      <div className="flex justify-between mb-3">
        <div className="h-5 w-12 bg-gray-200 dark:bg-gray-700 rounded-full" />
        <div className="h-5 w-8 bg-gray-200 dark:bg-gray-700 rounded" />
      </div>
      <div className="space-y-2">
        <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-full" />
        <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-5/6" />
        <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-3/4" />
      </div>
      <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-700">
        <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded w-16" />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main browser
// ---------------------------------------------------------------------------

export default function ExploreBrowser() {
  const { t } = useUI();
  const [entities, setEntities] = useState<EntityInfo[]>([]);
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [viewingDoc, setViewingDoc] = useState<DocumentSummary | null>(null);

  const [entityFilter, setEntityFilter] = useState<string>("");
  const [typeFilter, setTypeFilter] = useState<string>("");
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [page, setPage] = useState(1);

  const PAGE_SIZE = 24;
  const totalPages = Math.ceil(total / PAGE_SIZE);

  useEffect(() => {
    fetchEntities().then(setEntities);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    const res = await fetchDocuments({
      entity: entityFilter || undefined,
      doc_type: typeFilter || undefined,
      search: search || undefined,
      page,
      page_size: PAGE_SIZE,
    });
    setDocs(res.items);
    setTotal(res.total);
    setLoading(false);
  }, [entityFilter, typeFilter, search, page]);

  useEffect(() => { load(); }, [load]);

  const applyEntity = (e: string) => { setEntityFilter(e); setPage(1); };
  const applyType = (tp: string) => { setTypeFilter(tp); setPage(1); };
  const applySearch = () => { setSearch(searchInput); setPage(1); };

  return (
    <>
      {viewingDoc && (
        <DocumentViewer doc={viewingDoc} onClose={() => setViewingDoc(null)} />
      )}

      <div className="space-y-5">
        {entities.length > 0 && (() => {
          const totalDocs = entities.reduce((s, e) => s + e.doc_count, 0);
          const totalFailed = entities.reduce((s, e) => s + e.failed_count, 0);
          const lastUpdated = entities
            .map((e) => e.last_updated)
            .filter(Boolean)
            .sort()
            .at(-1) ?? null;
          const { label: freshLabel } = freshnessInfo(lastUpdated);
          return (
            <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800/50 rounded-xl px-4 py-2.5">
              <span className="font-semibold text-gray-700 dark:text-gray-200 text-sm">{totalDocs.toLocaleString()} documents</span>
              <span className="text-gray-300 dark:text-gray-600">|</span>
              <span>{entities.filter(e => e.doc_count > 0).length} active sources</span>
              <span className="text-gray-300 dark:text-gray-600">|</span>
              <span>{freshLabel}</span>
              {totalFailed > 0 && (
                <>
                  <span className="text-gray-300 dark:text-gray-600">|</span>
                  <span className="text-red-600 dark:text-red-400 font-medium">{totalFailed} failed ingestion{totalFailed !== 1 ? "s" : ""}</span>
                </>
              )}
            </div>
          );
        })()}

        {entities.length > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {entities.map((e) => (
              <button
                key={e.entity}
                onClick={() => applyEntity(entityFilter === e.entity ? "" : e.entity)}
                className={`rounded-xl border p-4 text-start transition-all ${
                  entityFilter === e.entity
                    ? "border-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 shadow-sm"
                    : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 hover:border-emerald-200 dark:hover:border-emerald-600 hover:shadow-sm dark:hover:bg-emerald-900/10"
                }`}
              >
                <div className="text-lg font-bold text-gray-900 dark:text-gray-100">{e.doc_count}</div>
                <div className="text-xs font-semibold text-emerald-700 dark:text-emerald-400 mt-0.5">{e.entity}</div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 truncate">{e.name_en}</div>
                {(() => {
                  const { dot, label } = freshnessInfo(e.last_updated);
                  return (
                    <div className="flex items-center gap-1.5 mt-2">
                      <span className={`inline-block w-1.5 h-1.5 rounded-full shrink-0 ${dot}`} />
                      <span className="text-xs text-gray-400 dark:text-gray-500 truncate">{label}</span>
                    </div>
                  );
                })()}
                {e.failed_count > 0 && (
                  <div className="flex items-center gap-1 mt-1.5">
                    <span className="text-xs bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 rounded px-1.5 py-0.5 font-medium">
                      {e.failed_count} failed
                    </span>
                  </div>
                )}
                {e.pending_count > 0 && (
                  <div className="flex items-center gap-1 mt-1.5">
                    <span className="text-xs bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 rounded px-1.5 py-0.5 font-medium">
                      {e.pending_count} processing
                    </span>
                  </div>
                )}
              </button>
            ))}
          </div>
        )}

        <div className="flex flex-wrap gap-3 items-center">
          <div className="flex flex-1 min-w-[220px] items-center gap-2">
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && applySearch()}
              placeholder={t("explore.search")}
              className="flex-1 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
            />
            <button onClick={applySearch} className="rounded-lg bg-emerald-600 px-3 py-2 text-sm text-white hover:bg-emerald-700 transition-colors">
              Search
            </button>
            {search && (
              <button onClick={() => { setSearchInput(""); setSearch(""); setPage(1); }} className="text-sm text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 transition-colors">
                Clear
              </button>
            )}
          </div>
          <div className="flex gap-2">
            {[
              { value: "", label: t("explore.all") },
              { value: "pdf_text", label: "PDF" },
              { value: "excel", label: "Excel" },
            ].map(({ value, label }) => (
              <button
                key={value}
                onClick={() => applyType(value)}
                className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                  typeFilter === value
                    ? "bg-emerald-600 text-white"
                    : "bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:border-emerald-300 dark:hover:border-emerald-600"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="text-xs text-gray-500 dark:text-gray-400">
          {loading ? "Loading…" : `${total.toLocaleString()} document${total !== 1 ? "s" : ""}`}
          {(entityFilter || typeFilter || search) && (
            <button
              onClick={() => { setEntityFilter(""); setTypeFilter(""); setSearch(""); setSearchInput(""); setPage(1); }}
              className="ms-3 text-emerald-600 dark:text-emerald-400 hover:underline"
            >
              Clear all filters
            </button>
          )}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {loading
            ? Array.from({ length: 12 }).map((_, i) => <SkeletonCard key={i} />)
            : docs.map((doc) => <DocumentCard key={doc.id} doc={doc} onView={setViewingDoc} />)}
        </div>

        {!loading && docs.length === 0 && (
          <div className="text-center py-20 text-gray-400 dark:text-gray-500">
            <div className="text-4xl mb-3">📂</div>
            <p className="text-sm">{t("explore.noResults")}</p>
          </div>
        )}

        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-2 pt-4">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1 || loading}
              className="rounded-lg border border-gray-300 dark:border-gray-700 px-3 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              ← {t("explore.prev")}
            </button>
            <div className="flex gap-1">
              {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                const p = totalPages <= 7 ? i + 1 : i === 0 ? 1 : i === 6 ? totalPages : Math.max(2, Math.min(page - 2, totalPages - 5)) + i - 1;
                return (
                  <button key={p} onClick={() => setPage(p)} disabled={loading}
                    className={`w-8 h-8 rounded-lg text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${page === p ? "bg-emerald-600 text-white" : "border border-gray-300 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800"}`}
                  >{p}</button>
                );
              })}
            </div>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages || loading}
              className="rounded-lg border border-gray-300 dark:border-gray-700 px-3 py-1.5 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {t("explore.next")} →
            </button>
          </div>
        )}
      </div>
    </>
  );
}
