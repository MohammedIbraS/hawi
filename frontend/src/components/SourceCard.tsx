"use client";

import { useState } from "react";
import { Source } from "@/lib/types";
import { useUI } from "@/contexts/UIContext";

interface Props {
  sources: Source[];
}

const ENTITY_LABELS: Record<string, string> = {
  MOH: "وزارة الصحة / MOH",
  SFDA: "هيئة الغذاء والدواء / SFDA",
  GASTAT: "هيئة الإحصاء / GASTAT",
  NHIC: "المركز الوطني لمعلومات الصحة / NHIC",
  SHC: "المجلس الصحي السعودي / SHC",
  SCHS: "الهيئة السعودية للتخصصات الصحية / SCHS",
  CCHI: "مجلس الضمان الصحي / CCHI",
  WEQAYA: "مركز مكافحة الأمراض / Weqaya",
};

function ChevronIcon({ expanded }: { expanded: boolean }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ transform: expanded ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.15s" }}
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}

/** Append #page=N fragment to PDF URLs so the browser jumps to the right page. */
function pdfUrl(url: string, page: number | null): string {
  if (!url || !page) return url;
  if (url.toLowerCase().includes(".pdf")) return `${url}#page=${page}`;
  return url;
}

function ContentPreview({ content }: { content: string }) {
  return (
    <blockquote
      dir="auto"
      className="border-t border-gray-200 dark:border-gray-700 mx-3 mb-2 mt-0 pt-2 text-gray-600 dark:text-gray-400 italic leading-relaxed text-xs"
    >
      {content}
      {content.length >= 300 && <span className="text-gray-400 dark:text-gray-500">…</span>}
    </blockquote>
  );
}

function SourceItem({ s, lang }: { s: Source; lang: "ar" | "en" }) {
  const [expanded, setExpanded] = useState(false);
  const href = pdfUrl(s.url, s.page_number);
  const year = s.publication_date ? s.publication_date.slice(0, 4) : null;

  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-xs text-gray-700 dark:text-gray-300 overflow-hidden">
      <div className="flex items-center gap-1.5 px-3 py-1.5">
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="flex-1 flex items-center gap-1.5 hover:text-emerald-700 dark:hover:text-emerald-400 min-w-0"
        >
          <span className="font-semibold text-emerald-700 dark:text-emerald-400 shrink-0">[{s.index}]</span>
          <span className="truncate">
            {lang === "ar" ? s.title_ar || s.title_en : s.title_en || s.title_ar}
          </span>
          {s.page_number && (
            <span className="text-gray-400 dark:text-gray-500 shrink-0">
              {lang === "ar" ? `ص ${s.page_number}` : `p.${s.page_number}`}
            </span>
          )}
          {year && (
            <span className="rounded bg-blue-100 dark:bg-blue-900/30 px-1.5 py-0.5 text-blue-700 dark:text-blue-300 font-semibold shrink-0">
              {year}
            </span>
          )}
          <span className="rounded bg-emerald-100 dark:bg-emerald-900/30 px-1.5 py-0.5 text-emerald-800 dark:text-emerald-300 font-medium shrink-0">
            {ENTITY_LABELS[s.entity] ?? s.entity}
          </span>
        </a>
        {s.content && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="shrink-0 text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 p-0.5"
            aria-label={expanded ? "Collapse excerpt" : "Expand excerpt"}
          >
            <ChevronIcon expanded={expanded} />
          </button>
        )}
      </div>
      {expanded && s.content && <ContentPreview content={s.content} />}
    </div>
  );
}

export default function SourceCard({ sources }: Props) {
  const { lang, t } = useUI();

  if (!sources.length) return null;

  return (
    <div className="mt-3 space-y-2">
      <p className="text-xs font-semibold text-gray-500 dark:text-gray-500 uppercase tracking-wide">
        {t("chat.sources")}
      </p>
      <div className="flex flex-col gap-1.5">
        {sources.map((s) => (
          <SourceItem key={s.index} s={s} lang={lang} />
        ))}
      </div>
    </div>
  );
}
