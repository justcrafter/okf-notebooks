import { useEffect, useState } from "react";
import { useT } from "./i18n";

export type Theme = "light" | "dark";

const systemTheme = (): Theme =>
  window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";

export function initialTheme(): Theme {
  try {
    const saved = localStorage.getItem("okf-theme");
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* storage unavailable */
  }
  return systemTheme();
}

export function applyTheme(theme: Theme, persist: boolean): void {
  document.documentElement.setAttribute("data-theme", theme);
  if (!persist) return;
  try {
    localStorage.setItem("okf-theme", theme);
  } catch {
    /* storage unavailable */
  }
}

export function ThemeToggle() {
  const t = useT();
  const [theme, setTheme] = useState<Theme>(initialTheme);
  useEffect(() => applyTheme(theme, false), [theme]);
  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <button
      className="icon-btn"
      aria-label={next === "dark" ? t.themeDark : t.themeLight}
      title={next === "dark" ? t.themeDark : t.themeLight}
      onClick={() => {
        setTheme(next);
        applyTheme(next, true);
      }}
    >
      {theme === "dark" ? (
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        </svg>
      )}
    </button>
  );
}
