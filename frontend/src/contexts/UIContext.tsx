"use client";
import { createContext, useContext, useEffect, useState, ReactNode } from "react";

type Theme = "light" | "dark";
type Lang = "ar" | "en";

interface UIContextValue {
  theme: Theme;
  toggleTheme: (x?: number, y?: number) => void;
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string) => string;
  dir: "ltr" | "rtl";
}

const UI_STRINGS: Record<string, { en: string; ar: string }> = {
  "nav.chat": { en: "Chat", ar: "المحادثة" },
  "nav.explore": { en: "Explore", ar: "استكشاف" },
  "nav.signIn": { en: "Sign in", ar: "تسجيل الدخول" },
  "nav.signOut": { en: "Sign out", ar: "تسجيل الخروج" },
  "chat.placeholder": { en: "Ask about health statistics…", ar: "اسأل عن الإحصاءات الصحية…" },
  "chat.send": { en: "Send", ar: "إرسال" },
  "chat.welcome": { en: "Saudi Health Intelligence", ar: "المعلومات الصحية السعودية" },
  "chat.welcomeSub": { en: "Ask questions grounded in official data from MOH, GASTAT, CCHI, SHC, NHIC, and SFDA.", ar: "اطرح أسئلة مستندة إلى بيانات رسمية من وزارة الصحة والهيئة العامة للإحصاء ومجلس الضمان الصحي والمجلس الصحي السعودي والمركز الوطني للمعلومات الصحية وهيئة الغذاء والدواء." },
  "chat.newChat": { en: "New chat", ar: "محادثة جديدة" },
  "chat.noHistory": { en: "No conversations yet", ar: "لا توجد محادثات بعد" },
  "chat.sources": { en: "Sources", ar: "المصادر" },
  "chat.disclaimer": { en: "AI-generated · verify with primary sources", ar: "مُولَّد بالذكاء الاصطناعي · تحقق من المصادر الأصلية" },
  "chat.thinking": { en: "Thinking…", ar: "جارٍ التفكير…" },
  "explore.title": { en: "Document Library", ar: "مكتبة الوثائق" },
  "explore.subtitle": { en: "Browse indexed health publications from MOH, GASTAT, CCHI, SHC, NHIC, and SFDA", ar: "تصفح المنشورات الصحية المفهرسة من وزارة الصحة والهيئة العامة للإحصاء ومجلس الضمان الصحي والمجلس الصحي السعودي وهيئة الغذاء والدواء" },
  "explore.search": { en: "Search documents…", ar: "بحث في الوثائق…" },
  "explore.all": { en: "All types", ar: "جميع الأنواع" },
  "explore.prev": { en: "Previous", ar: "السابق" },
  "explore.next": { en: "Next", ar: "التالي" },
  "explore.noResults": { en: "No documents found", ar: "لا توجد وثائق" },
  "auth.signIn": { en: "Sign in", ar: "تسجيل الدخول" },
  "auth.register": { en: "Create account", ar: "إنشاء حساب" },
  "auth.email": { en: "Email address", ar: "البريد الإلكتروني" },
  "auth.password": { en: "Password", ar: "كلمة المرور" },
  "auth.fullName": { en: "Full name", ar: "الاسم الكامل" },
  "auth.submitSignIn": { en: "Sign in", ar: "تسجيل الدخول" },
  "auth.submitRegister": { en: "Create account", ar: "إنشاء حساب" },
  "auth.continueGuest": { en: "Continue as guest →", ar: "المتابعة كضيف ←" },
  "auth.tagline": { en: "Saudi Health Intelligence Platform", ar: "منصة الذكاء الصحي السعودي" },
  "app.name": { en: "Hawi", ar: "الحاوي" },
};

const UIContext = createContext<UIContextValue | null>(null);

export function UIProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>("light");
  const [lang, setLangState] = useState<Lang>("en");

  useEffect(() => {
    const savedTheme = (localStorage.getItem("shh_theme") as Theme) || "light";
    const savedLang = (localStorage.getItem("shh_lang") as Lang) || "en";
    setTheme(savedTheme);
    setLangState(savedLang);
    applyTheme(savedTheme);
    applyLang(savedLang);
  }, []);

  function applyTheme(t: Theme) {
    document.documentElement.classList.toggle("dark", t === "dark");
  }

  function applyLang(l: Lang) {
    document.documentElement.dir = l === "ar" ? "rtl" : "ltr";
    document.documentElement.lang = l;
  }

  function toggleTheme(x?: number, y?: number) {
    const next = theme === "light" ? "dark" : "light";
    const apply = () => {
      setTheme(next);
      localStorage.setItem("shh_theme", next);
      applyTheme(next);
    };
    if (typeof document !== "undefined" && "startViewTransition" in document) {
      if (x !== undefined && y !== undefined) {
        document.documentElement.style.setProperty("--ripple-x", `${x}px`);
        document.documentElement.style.setProperty("--ripple-y", `${y}px`);
      }
      (document as Document & { startViewTransition: (cb: () => void) => void }).startViewTransition(apply);
    } else {
      apply();
    }
  }

  function setLang(l: Lang) {
    setLangState(l);
    localStorage.setItem("shh_lang", l);
    applyLang(l);
  }

  function t(key: string): string {
    return UI_STRINGS[key]?.[lang] ?? key;
  }

  const dir = lang === "ar" ? "rtl" : "ltr";

  return (
    <UIContext.Provider value={{ theme, toggleTheme, lang, setLang, t, dir }}>
      {children}
    </UIContext.Provider>
  );
}

export function useUI() {
  const ctx = useContext(UIContext);
  if (!ctx) throw new Error("useUI must be used inside UIProvider");
  return ctx;
}
