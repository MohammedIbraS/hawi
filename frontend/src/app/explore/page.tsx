"use client";
import Header from "@/components/Header";
import ExploreBrowser from "@/components/ExploreBrowser";
import { useUI } from "@/contexts/UIContext";

export default function ExplorePage() {
  const { t } = useUI();
  return (
    <div className="min-h-screen flex flex-col bg-gray-50 dark:bg-gray-950">
      <Header />
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 py-6">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">{t("explore.title")}</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">{t("explore.subtitle")}</p>
        </div>
        <ExploreBrowser />
      </main>
    </div>
  );
}
