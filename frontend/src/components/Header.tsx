"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { useUI } from "@/contexts/UIContext";

function MoonIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

function SunIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  );
}

export default function Header() {
  const { user, loading, logout } = useAuth();
  const { theme, toggleTheme, lang, setLang, t } = useUI();
  const pathname = usePathname();

  return (
    <header className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700/60 px-5 py-3 flex items-center gap-4">
      {/* Logo */}
      <Link href="/" className="flex items-center gap-2.5 shrink-0">
        <img src="/logo.png" alt="Hawi logo" className="w-8 h-8 rounded-lg" />
        <div className="hidden sm:block">
          <p className="text-sm font-semibold text-gray-900 dark:text-gray-100 leading-tight">{t("app.name")}</p>
        </div>
      </Link>

      {/* Nav */}
      <nav className="flex items-center gap-1 ms-2">
        <Link
          href="/chat"
          className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
            pathname === "/chat"
              ? "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400"
              : "text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 hover:bg-gray-100 dark:hover:bg-gray-800"
          }`}
        >
          {t("nav.chat")}
        </Link>
        <Link
          href="/explore"
          className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
            pathname === "/explore"
              ? "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400"
              : "text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 hover:bg-gray-100 dark:hover:bg-gray-800"
          }`}
        >
          {t("nav.explore")}
        </Link>
      </nav>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Right controls */}
      <div className="flex items-center gap-2">
        {/* Language switcher */}
        <div className="flex items-center rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden text-xs font-medium">
          <button
            onClick={() => setLang("en")}
            aria-pressed={lang === "en"}
            aria-label="Switch to English"
            className={`px-2.5 py-1.5 transition-colors ${
              lang === "en"
                ? "bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900"
                : "text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
            }`}
          >
            EN
          </button>
          <button
            onClick={() => setLang("ar")}
            aria-pressed={lang === "ar"}
            aria-label="Switch to Arabic"
            className={`px-2.5 py-1.5 transition-colors ${
              lang === "ar"
                ? "bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900"
                : "text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"
            }`}
          >
            AR
          </button>
        </div>

        {/* Dark mode toggle */}
        <button
          onClick={(e) => toggleTheme(e.clientX, e.clientY)}
          className="p-2 rounded-lg text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          aria-label="Toggle dark mode"
        >
          {theme === "dark" ? <SunIcon /> : <MoonIcon />}
        </button>

        {/* Auth */}
        {loading ? (
          <div className="w-20 h-8 rounded-lg bg-gray-100 dark:bg-gray-800 animate-pulse" />
        ) : user ? (
          <div className="flex items-center gap-2">
            <span className="hidden sm:block text-xs text-gray-500 dark:text-gray-400 max-w-[120px] truncate">{user.email}</span>
            <button
              onClick={logout}
              className="px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
            >
              {t("nav.signOut")}
            </button>
          </div>
        ) : (
          <Link
            href="/login"
            className="px-3 py-1.5 rounded-lg bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700 transition-colors"
          >
            {t("nav.signIn")}
          </Link>
        )}
      </div>
    </header>
  );
}
