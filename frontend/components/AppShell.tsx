"use client";

import { useState, type ReactNode } from "react";
import {
  BookOpenCheck,
  Building2,
  ChevronDown,
  FolderArchive,
  KeyRound,
  Languages,
  LogOut,
  Menu,
  MessageSquareText,
  Moon,
  Plus,
  Settings,
  Sun,
  UserRound,
  Users,
  X,
} from "lucide-react";

import type { AuthUser } from "@/lib/auth";
import { COPY, type Language } from "@/lib/copy";
import type { Theme } from "@/lib/theme";

export type ViewKey = "chat" | "library" | "users" | "settings";

export interface KeyStatus {
  label: string;
  tone: "user" | "server" | "offline" | "required";
}

const TONE_DOT: Record<KeyStatus["tone"], string> = {
  user: "bg-emerald-400",
  server: "bg-sky-400",
  offline: "bg-slate-500",
  required: "bg-amber-400",
};

/**
 * Responsive workspace chrome: a persistent desktop sidebar, a mobile drawer,
 * and a top bar with language/theme/key/account controls. All data and actions
 * are supplied by ChatInterface; this component is purely presentational.
 */
export default function AppShell({
  view,
  onViewChange,
  language,
  onLanguage,
  theme,
  onTheme,
  user,
  keyStatus,
  byokEnabled,
  onOpenKey,
  onNewChat,
  onOpenAuth,
  onSignOut,
  children,
}: {
  view: ViewKey;
  onViewChange: (view: ViewKey) => void;
  language: Language;
  onLanguage: () => void;
  theme: Theme;
  onTheme: () => void;
  user: AuthUser | null;
  keyStatus: KeyStatus;
  byokEnabled: boolean;
  onOpenKey: () => void;
  onNewChat: () => void;
  onOpenAuth: () => void;
  onSignOut: () => void;
  children: ReactNode;
}) {
  const copy = COPY[language];
  const [mobileOpen, setMobileOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);

  const navItems: { key: ViewKey; label: string; icon: typeof MessageSquareText; adminOnly?: boolean }[] = [
    { key: "chat", label: copy.navChat, icon: MessageSquareText },
    { key: "library", label: copy.navLibrary, icon: FolderArchive },
    { key: "users", label: copy.navUsers, icon: Users, adminOnly: true },
    { key: "settings", label: copy.navSettings, icon: Settings },
  ];
  const visibleNav = navItems.filter((item) => !item.adminOnly || user?.role === "admin");

  const header =
    view === "chat"
      ? { title: copy.viewChatTitle, subtitle: copy.viewChatSubtitle }
      : view === "library"
        ? { title: copy.viewLibraryTitle, subtitle: copy.viewLibrarySubtitle }
        : view === "users"
          ? { title: copy.viewUsersTitle, subtitle: copy.viewUsersSubtitle }
          : { title: copy.viewSettingsTitle, subtitle: copy.viewSettingsSubtitle };

  const sidebar = (
    <>
      <div className="flex h-14 shrink-0 items-center gap-3 border-b border-app px-5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-600 text-white">
          <BookOpenCheck className="h-[18px] w-[18px]" />
        </div>
        <div className="min-w-0">
          <h1 className="truncate text-sm font-bold text-primary">Employee AI Search</h1>
          <p className="truncate text-[10px] text-muted">
            {user?.workspace?.name ?? copy.navWorkspace}
          </p>
        </div>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto p-3">
        <button
          type="button"
          onClick={() => {
            onNewChat();
            onViewChange("chat");
            setMobileOpen(false);
          }}
          className="btn-primary mb-2 w-full justify-start"
        >
          <Plus className="h-4 w-4" />
          {copy.newChat}
        </button>
        {visibleNav.map((item) => {
          const active = view === item.key;
          return (
            <button
              key={item.key}
              type="button"
              onClick={() => {
                onViewChange(item.key);
                setMobileOpen(false);
              }}
              className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-200 ${
                active
                  ? "bg-primary-600 text-white shadow-sm shadow-primary-600/20"
                  : "text-secondary hover:bg-white/5 hover:text-primary"
              }`}
              aria-current={active ? "page" : undefined}
            >
              <item.icon className="h-[18px] w-[18px] shrink-0" />
              <span className="truncate">{item.label}</span>
            </button>
          );
        })}
      </nav>
    </>
  );

  return (
    <div className="flex h-screen overflow-hidden bg-app">
      {/* Kept outside the header: a backdrop-filter ancestor would otherwise
          turn this fixed layer into a header-sized overlay. */}
      {accountOpen ? (
        <div
          className="fixed inset-0 z-40"
          onClick={() => setAccountOpen(false)}
          aria-hidden
        />
      ) : null}
      <aside className="hidden w-60 shrink-0 flex-col border-e border-app bg-surface md:flex">
        {sidebar}
      </aside>

      {mobileOpen ? (
        <>
          <div
            className="fixed inset-0 z-40 bg-neutral-950/40 backdrop-blur-sm md:hidden"
            onClick={() => setMobileOpen(false)}
            aria-hidden
          />
          <aside className="fixed inset-y-0 start-0 z-50 flex w-60 flex-col border-e border-app bg-surface animate-slide-in-right md:hidden">
            <button
              type="button"
              onClick={() => setMobileOpen(false)}
              className="absolute end-4 top-4 rounded-lg p-1.5 text-muted hover:bg-white/5"
              aria-label={copy.menuClose}
              title={copy.menuClose}
            >
              <X className="h-[18px] w-[18px]" />
            </button>
            {sidebar}
          </aside>
        </>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="relative z-50 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-app bg-surface px-4">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              onClick={() => setMobileOpen(true)}
              className="rounded-lg p-2 text-secondary hover:bg-white/5 md:hidden"
              aria-label={copy.menuOpen}
              title={copy.menuOpen}
            >
              <Menu className="h-5 w-5" />
            </button>
            <div className="min-w-0">
              <h2 className="truncate text-sm font-semibold text-primary">{header.title}</h2>
              <p className="hidden truncate text-xs text-muted sm:block">{header.subtitle}</p>
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            <span className="hidden items-center gap-1.5 rounded-full border border-app bg-white/[0.03] px-2.5 py-1 text-[11px] text-secondary lg:inline-flex">
              <span className={`h-1.5 w-1.5 rounded-full ${TONE_DOT[keyStatus.tone]}`} />
              {keyStatus.label}
            </span>

            <button
              type="button"
              onClick={onLanguage}
              className="btn-ghost gap-1.5 px-2.5 text-xs"
              aria-label={copy.language}
              title={copy.language}
            >
              <Languages className="h-[15px] w-[15px]" />
              {language === "en" ? "AR" : "EN"}
            </button>

            <button
              type="button"
              onClick={onTheme}
              className="btn-ghost p-2"
              aria-label={theme === "dark" ? copy.toggleThemeLight : copy.toggleThemeDark}
              title={theme === "dark" ? copy.toggleThemeLight : copy.toggleThemeDark}
            >
              {theme === "dark" ? <Sun className="h-[17px] w-[17px]" /> : <Moon className="h-[17px] w-[17px]" />}
            </button>

            {byokEnabled ? (
              <button
                type="button"
                onClick={onOpenKey}
                className="btn-ghost relative p-2"
                aria-label={copy.llmButton}
                title={copy.llmButton}
              >
                <KeyRound className="h-[17px] w-[17px]" />
                {keyStatus.tone === "user" ? (
                  <span className="absolute end-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-emerald-400" />
                ) : null}
              </button>
            ) : null}

            <div className="relative">
              <button
                type="button"
                onClick={() => setAccountOpen((open) => !open)}
                className="flex items-center gap-2 rounded-lg py-1.5 ps-1.5 pe-1 transition-colors hover:bg-white/5"
                aria-expanded={accountOpen}
                aria-label={copy.authButton}
              >
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary-600 text-xs font-semibold text-white">
                  {(user?.display_name ?? user?.email ?? "U").charAt(0).toUpperCase()}
                </span>
                <span className="hidden max-w-[9rem] truncate text-xs font-medium text-primary sm:block">
                  {user?.display_name ?? user?.email ?? copy.authSignIn}
                </span>
                <ChevronDown className="h-3.5 w-3.5 text-muted" />
              </button>

              {accountOpen ? (
                <div className="absolute top-full z-50 mt-2 w-56 animate-scale-in rounded-xl border border-app bg-surface-elevated py-2 shadow-menu start-0 sm:end-0 sm:start-auto">
                  <div className="border-b border-app px-3 py-2">
                    <p className="truncate text-sm font-medium text-primary">
                      {user?.display_name ?? copy.authSignIn}
                    </p>
                    <p className="truncate text-xs text-muted">
                      {user?.email ?? copy.authNotProvided}
                    </p>
                    <p className="mt-1 flex items-center gap-1 truncate text-[11px] text-secondary">
                      <Building2 className="h-3 w-3 shrink-0" />
                      {user?.workspace?.name ?? copy.authNoWorkspace}
                    </p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1">
                      <span className="badge bg-white/5 text-secondary">
                        {user?.role === "admin" ? copy.adminBadge : copy.usersRoleUser}
                      </span>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      onViewChange("settings");
                      setAccountOpen(false);
                    }}
                    className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-secondary transition-colors hover:bg-white/5 hover:text-primary"
                  >
                    <Settings className="h-4 w-4" />
                    {copy.navSettings}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setAccountOpen(false);
                      onOpenAuth();
                    }}
                    className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-secondary transition-colors hover:bg-white/5 hover:text-primary"
                  >
                    <UserRound className="h-4 w-4" />
                    {copy.authSignIn}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setAccountOpen(false);
                      onSignOut();
                    }}
                    className="flex w-full items-center gap-2.5 px-3 py-2 text-sm text-red-300 transition-colors hover:bg-red-500/10"
                  >
                    <LogOut className="h-4 w-4 flip-rtl" />
                    {copy.navSignOut}
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
