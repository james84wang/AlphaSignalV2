import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { marked } from "marked";
import { fetchAbout } from "../lib/api";
import { useLang } from "../lib/LanguageContext";

const TAB_SPLIT = "<!-- TAB_SPLIT -->";

interface Tab {
  id: string;
  label: string;
  html: string;
}

function parseTabs(markdown: string): Tab[] {
  const sections = markdown.split(TAB_SPLIT);
  const tabs: Tab[] = [];

  for (const section of sections) {
    const trimmed = section.trim();
    if (!trimmed) continue;

    // Only include sections that have a ## heading (skip the preamble)
    const match = trimmed.match(/^##\s+(.+)/m);
    if (!match) continue;

    const label = match[1].trim();
    const id = label.toLowerCase().replace(/[^a-z0-9]+/g, "-");

    // Strip the heading line itself so it's not doubled in the rendered content
    const body = trimmed.replace(/^##\s+.+\n?/, "").trim();
    const html = marked.parse(body) as string;

    tabs.push({ id, label, html });
  }

  return tabs;
}

export function About() {
  const [activeTab, setActiveTab] = useState(0);
  const { lang, t } = useLang();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["about", lang],
    queryFn: () => fetchAbout(lang),
    staleTime: 5 * 60 * 1000,
  });

  const tabs = data ? parseTabs(data.content) : [];

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400">
        {t("loading")}
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="flex-1 flex items-center justify-center text-red-400">
        {t("error")}
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Page header */}
      <div className="px-6 pt-5 pb-0 border-b border-slate-800">
        <div className="flex items-baseline justify-between mb-3">
          <h1 className="text-lg font-semibold text-slate-100">{t("about_title")}</h1>
          <span className="text-xs text-slate-500">
            {t("last_updated")}: {data.last_updated}
          </span>
        </div>

        {/* Tab bar */}
        <div className="flex gap-1">
          {tabs.map((tab, i) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(i)}
              className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-colors border-b-2 ${
                i === activeTab
                  ? "text-cyan-300 border-cyan-400 bg-cyan-500/10"
                  : "text-slate-400 border-transparent hover:text-slate-200 hover:border-slate-600"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        {tabs[activeTab] && (
          <div
            className="about-content max-w-4xl"
            dangerouslySetInnerHTML={{ __html: tabs[activeTab].html }}
          />
        )}
      </div>
    </div>
  );
}
