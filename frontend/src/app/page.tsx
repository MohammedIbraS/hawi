import Link from "next/link";
import Header from "@/components/Header";

const SOURCES = [
  {
    key: "MOH",
    name: "Ministry of Health",
    name_ar: "وزارة الصحة",
    desc: "Statistical yearbooks, clinical guidelines, and hospital performance data.",
    color: "border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20",
    badge: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  },
  {
    key: "GASTAT",
    name: "General Authority for Statistics",
    name_ar: "الهيئة العامة للإحصاء",
    desc: "Health surveys covering disability, maternal health, household health status, and more.",
    color: "border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20",
    badge: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  },
  {
    key: "CCHI",
    name: "Council of Health Insurance",
    name_ar: "مجلس الضمان الصحي",
    desc: "Annual insurance sector reports, coverage statistics, and research white papers.",
    color: "border-sky-200 dark:border-sky-800 bg-sky-50 dark:bg-sky-900/20",
    badge: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300",
  },
  {
    key: "SHC",
    name: "Saudi Health Council",
    name_ar: "المجلس الصحي السعودي",
    desc: "National Cancer Center incidence reports and cancer registry data (1998–2023).",
    color: "border-rose-200 dark:border-rose-800 bg-rose-50 dark:bg-rose-900/20",
    badge: "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300",
  },
  {
    key: "NHIC",
    name: "National Health Information Center",
    name_ar: "المركز الوطني للمعلومات الصحية",
    desc: "National Health Accounts expenditure reports and health financing statistics.",
    color: "border-orange-200 dark:border-orange-800 bg-orange-50 dark:bg-orange-900/20",
    badge: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300",
  },
  {
    key: "SFDA",
    name: "Saudi Food & Drug Authority",
    name_ar: "هيئة الغذاء والدواء",
    desc: "Annual reports on pharmaceutical regulation, drug approvals, and food safety.",
    color: "border-purple-200 dark:border-purple-800 bg-purple-50 dark:bg-purple-900/20",
    badge: "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300",
  },
];

const SAMPLE_QUESTIONS = [
  "What is the total number of hospital beds per 1,000 population?",
  "How many primary healthcare centers does MOH operate?",
  "ما هي نسبة الأطباء السعوديين في وزارة الصحة؟",
  "What are the main cancer types in Saudi Arabia according to SHC?",
];

const STATS = [
  { value: "150+", label: "Documents indexed" },
  { value: "6", label: "Official sources" },
  { value: "AR + EN", label: "Bilingual search" },
  { value: "Real-time", label: "Streaming answers" },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen flex flex-col bg-gray-50 dark:bg-gray-950">
      <Header />

      {/* Hero */}
      <section className="flex flex-col items-center text-center px-6 pt-20 pb-16 max-w-3xl mx-auto w-full">
        <div className="flex items-center gap-3 mb-6">
          <img src="/logo.png" alt="Hawi" className="w-14 h-14 rounded-2xl shadow-md" />
          <div className="text-start">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 leading-tight">Hawi</h1>
            <p className="text-lg text-gray-500 dark:text-gray-400 leading-tight">الحاوي</p>
          </div>
        </div>

        <h2 className="text-3xl sm:text-4xl font-bold text-gray-900 dark:text-gray-100 mb-4 leading-tight">
          Saudi Health Intelligence
        </h2>
        <p className="text-gray-600 dark:text-gray-400 text-lg max-w-xl leading-relaxed mb-8">
          Ask questions about Saudi Arabia&apos;s health system in Arabic or English.
          Grounded in official statistics from 6 government sources — with citations for every answer.
        </p>

        <div className="flex flex-wrap justify-center gap-3">
          <Link
            href="/chat"
            className="px-6 py-3 rounded-xl bg-emerald-600 text-white text-sm font-semibold hover:bg-emerald-700 transition-colors shadow-sm"
          >
            Start asking →
          </Link>
          <Link
            href="/explore"
            className="px-6 py-3 rounded-xl border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm font-semibold text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
          >
            Browse documents
          </Link>
        </div>
      </section>

      {/* Stats bar */}
      <section className="border-y border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 py-6">
        <div className="max-w-3xl mx-auto px-6 grid grid-cols-2 sm:grid-cols-4 gap-6 text-center">
          {STATS.map(({ value, label }) => (
            <div key={label}>
              <p className="text-xl font-bold text-emerald-600 dark:text-emerald-400">{value}</p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Sample questions */}
      <section className="py-12 px-6 max-w-3xl mx-auto w-full">
        <h3 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-4 text-center">
          Example questions
        </h3>
        <div className="grid sm:grid-cols-2 gap-3">
          {SAMPLE_QUESTIONS.map((q) => (
            <Link
              key={q}
              href={`/chat`}
              dir="auto"
              className="flex items-start gap-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 text-sm text-gray-700 dark:text-gray-300 hover:border-emerald-300 dark:hover:border-emerald-700 hover:shadow-sm transition-all group"
            >
              <span className="text-emerald-500 mt-0.5 shrink-0">›</span>
              <span className="group-hover:text-emerald-700 dark:group-hover:text-emerald-400 transition-colors">{q}</span>
            </Link>
          ))}
        </div>
      </section>

      {/* Sources */}
      <section className="py-12 px-6 max-w-4xl mx-auto w-full">
        <h3 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-6 text-center">
          Data sources
        </h3>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {SOURCES.map((s) => (
            <div key={s.key} className={`rounded-xl border p-4 ${s.color}`}>
              <div className="flex items-center gap-2 mb-2">
                <span className={`text-xs font-bold rounded-full px-2.5 py-1 ${s.badge}`}>{s.key}</span>
              </div>
              <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">{s.name}</p>
              <p dir="rtl" className="text-xs text-gray-500 dark:text-gray-400 text-right mb-2">{s.name_ar}</p>
              <p className="text-xs text-gray-600 dark:text-gray-400 leading-relaxed">{s.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="mt-auto border-t border-gray-200 dark:border-gray-700 py-6 text-center text-xs text-gray-400 dark:text-gray-500">
        Hawi — سمي بموسوعة الرازي الطبية &ldquo;الحاوي الكبير&rdquo; من القرن التاسع الميلادي
      </footer>
    </div>
  );
}
