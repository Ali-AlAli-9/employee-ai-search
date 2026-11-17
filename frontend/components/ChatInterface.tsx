"use client";

import { useCallback, useEffect, useState } from "react";

import AppShell, { type KeyStatus, type ViewKey } from "./AppShell";
import LlmKeyPanel from "./LlmKeyPanel";
import AuthView from "./views/AuthView";
import ChatView from "./views/ChatView";
import LibraryView from "./views/LibraryView";
import SettingsView from "./views/SettingsView";
import UsersView from "./views/UsersView";
import { chatStream, getHealth } from "@/lib/api";
import { shouldSuggestByok } from "@/lib/byok-hint";
import { getMe, logout, type AuthConfig, type AuthUser } from "@/lib/auth";
import { COPY, type Language } from "@/lib/copy";
import { friendlyError } from "@/lib/errors";
import { loadLlmKey, setByokAllowed } from "@/lib/llm";
import { applyTheme, readTheme, storeTheme, toggleTheme, type Theme } from "@/lib/theme";
import type { ChatMessage, Citation } from "@/lib/types";

function withToken(messages: ChatMessage[], token: string): ChatMessage[] {
  const next = [...messages];
  for (let i = next.length - 1; i >= 0; i -= 1) {
    if (next[i].role === "assistant") {
      next[i] = { ...next[i], content: next[i].content + token };
      break;
    }
  }
  return next;
}

function withCitation(messages: ChatMessage[], citation: Citation): ChatMessage[] {
  const next = [...messages];
  for (let i = next.length - 1; i >= 0; i -= 1) {
    if (next[i].role === "assistant") {
      const existing = next[i].citations ?? [];
      const deduped = existing.some((item) => item.chunk_id === citation.chunk_id)
        ? existing
        : [...existing, citation];
      next[i] = { ...next[i], citations: deduped };
      break;
    }
  }
  return next;
}

/**
 * The single stateful controller. Health, identity, BYOK and streaming logic is
 * unchanged from the original implementation; the new shell and views are only
 * presentational. This keeps every permission and privacy decision server-side
 * and avoids duplicating security-sensitive code across views.
 */
export default function ChatInterface() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [view, setView] = useState<ViewKey>("chat");
  const [language, setLanguage] = useState<Language>("en");
  const [error, setError] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [llmOpen, setLlmOpen] = useState(false);
  const [llmConfigured, setLlmConfigured] = useState(false);
  const [byokEnabled, setByokEnabled] = useState(true);
  const [serverLlm, setServerLlm] = useState(false);
  const [serverAdminOnly, setServerAdminOnly] = useState(false);
  const [requireChatByok, setRequireChatByok] = useState(false);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authOpen, setAuthOpen] = useState(false);
  const [theme, setTheme] = useState<Theme>("dark");
  const [themeReady, setThemeReady] = useState(false);

  useEffect(() => {
    setTheme(readTheme(window.localStorage));
    setThemeReady(true);
  }, []);

  useEffect(() => {
    applyTheme(theme, document.documentElement);
    // Do not persist until the stored value has been read: an early write of
    // the "dark" default would clobber a returning visitor's light choice.
    if (themeReady) storeTheme(theme, window.localStorage);
  }, [theme, themeReady]);

  const [authConfig, setAuthConfig] = useState<AuthConfig>({
    demo: false,
    registration: true,
    invite_required: false,
  });
  const copy = COPY[language];

  useEffect(() => {
    setLlmConfigured(Boolean(loadLlmKey()));
    let cancelled = false;
    void (async () => {
      const report = await getHealth();
      if (cancelled) return;
      const llm = report?.checks?.llm_api;
      const allowed = llm?.byok !== false;
      // Tell the request helper too, so a stored key is not sent to a
      // deployment that would reject it with 403.
      setByokAllowed(allowed);
      setByokEnabled(allowed);
      setServerLlm(llm?.status === "reachable");
      setServerAdminOnly(llm?.server_key_admin_only === true);
      setRequireChatByok(llm?.require_chat_byok === true);
      if (!allowed) setLlmOpen(false);

      // Server-reported flags; absent values keep the safe default so an old
      // backend does not silently lock visitors out.
      const authFlags = report?.checks?.auth;
      const config: AuthConfig = {
        demo: Boolean(authFlags?.demo),
        registration: authFlags?.registration !== false,
        invite_required: Boolean(authFlags?.invite_required),
      };
      setAuthConfig(config);

      // Only a real session counts now: there is no guest/demo fallback.
      const current = await getMe();
      if (cancelled) return;
      setUser(current);
      // Every protected route returns 401 without a session, and the health
      // probe itself can be lost to a cold start, so open the account view
      // whenever there is no identity instead of leaving a dead page.
      if (!current) setAuthOpen(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const acceptUser = useCallback((next: AuthUser) => {
    setUser(next);
    setAuthOpen(false);
    setError(null);
    setHint(null);
    // History is partitioned per principal, so start a clean conversation.
    setMessages([]);
  }, []);

  const signedOut = useCallback(() => {
    setError(null);
    setHint(null);
    setMessages([]);
    setView("chat");
    setUser(null);
    setAuthOpen(true);
  }, []);

  // The account menu must destroy the server session too; clearing only React
  // state would leave a live cookie and /auth/me would still authenticate.
  const signOut = useCallback(() => {
    void logout().finally(signedOut);
  }, [signedOut]);

  const refreshLlmState = useCallback(() => {
    setLlmConfigured(Boolean(loadLlmKey()));
    setHint(null);
  }, []);

  /** Stable identity: document views key their refresh loop on this callback. */
  const openAuth = useCallback(() => setAuthOpen(true), []);

  const toggleLanguage = useCallback(() => {
    const next = language === "en" ? "ar" : "en";
    setLanguage(next);
    window.localStorage.setItem("eais-lang", next);
  }, [language]);

  useEffect(() => {
    const stored = window.localStorage.getItem("eais-lang");
    if (stored === "en" || stored === "ar") setLanguage(stored);
  }, []);

  useEffect(() => {
    document.documentElement.lang = language;
    document.documentElement.dir = language === "ar" ? "rtl" : "ltr";
  }, [language]);

  // A role change elsewhere (or a stale view) must never expose admin data.
  useEffect(() => {
    if (view === "users" && user?.role !== "admin") setView("chat");
  }, [view, user]);

  const changeView = useCallback((next: ViewKey) => setView(next), []);

  const send = useCallback(
    async (raw?: string) => {
      const text = (raw ?? input).trim();
      if (!text || isStreaming) return;

      // The deployment's key is an admin privilege. Strict mode extends that
      // same 402 contract to deployments without a server key.
      if (
        byokEnabled &&
        serverAdminOnly &&
        user !== null &&
        user.role !== "admin" &&
        !llmConfigured &&
        (serverLlm || requireChatByok)
      ) {
        setError(copy.llmKeyNeeded);
        setLlmOpen(true);
        return;
      }

      setError(null);
      setHint(null);
      setInput("");
      const userMessage: ChatMessage = { role: "user", content: text };
      const history = [...messages, userMessage];
      setMessages([...history, { role: "assistant", content: "", citations: [] }]);
      setIsStreaming(true);
      let citationCount = 0;

      await chatStream(
        text,
        history,
        {
          onToken: (token) => setMessages((prev) => withToken(prev, token)),
          onCitation: (citation) => {
            citationCount += 1;
            setMessages((prev) => withCitation(prev, citation));
          },
          onDone: (payload) => {
            setIsStreaming(false);
            if (
              shouldSuggestByok({
                llmSource: payload.llm_source,
                confidence: payload.confidence,
                citationCount,
                byokEnabled,
                keyConfigured: Boolean(loadLlmKey()),
              })
            ) {
              setHint(copy.byokHint);
            }
          },
          onKeyRequired: () => setLlmOpen(true),
          onError: (cause) => {
            setHint(null);
            setError(friendlyError(cause, language, "chat"));
            setIsStreaming(false);
            setMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.role === "assistant" && !last.content) {
                next[next.length - 1] = {
                  ...last,
                  content:
                    language === "ar"
                      ? "تعذّر الحصول على إجابة. تحقّق من تشغيل الخادم وحاول مرة أخرى."
                      : "Could not get an answer. Check that the API is running and try again.",
                };
              }
              return next;
            });
          },
        },
        language,
      );
    },
    [
      input,
      isStreaming,
      language,
      messages,
      byokEnabled,
      serverLlm,
      serverAdminOnly,
      requireChatByok,
      user,
      llmConfigured,
      copy.llmKeyNeeded,
      copy.byokHint,
    ],
  );

  const reset = useCallback(() => {
    setMessages([]);
    setError(null);
    setHint(null);
    setIsStreaming(false);
    setView("chat");
  }, []);

  const needsVisitorKey =
    byokEnabled &&
    !llmConfigured &&
    user?.role !== "admin" &&
    ((serverLlm && serverAdminOnly) || requireChatByok);

  const keyStatus: KeyStatus = llmConfigured
    ? { label: copy.llmModeUser, tone: "user" }
    : serverLlm && (!serverAdminOnly || user?.role === "admin")
      ? { label: copy.llmModeServer, tone: "server" }
      : needsVisitorKey
        ? { label: copy.llmModeKeyRequired, tone: "required" }
        : serverLlm
          ? { label: copy.llmModeServer, tone: "server" }
          : { label: copy.llmModeOffline, tone: "offline" };

  // No identity means the full-page account view: sign in, or register as an
  // employer/member through the real auth API.
  if (authOpen || !user) {
    return (
      <AuthView
        language={language}
        user={user}
        config={authConfig}
        onUser={acceptUser}
        onSignedOut={signedOut}
        onLanguage={toggleLanguage}
      />
    );
  }

  return (
    <>
      <AppShell
        view={view}
        onViewChange={changeView}
        language={language}
        onLanguage={toggleLanguage}
        theme={theme}
        onTheme={() => setTheme(toggleTheme)}
        user={user}
        keyStatus={keyStatus}
        byokEnabled={byokEnabled}
        onOpenKey={() => setLlmOpen(true)}
        onNewChat={reset}
        onOpenAuth={openAuth}
        onSignOut={signOut}
      >
        {view === "chat" ? (
          <div className="flex h-full min-h-0 flex-col">
            {error ? (
              <div className="border-b border-red-500/30 bg-red-500/10 px-4 py-2 text-center text-xs text-red-200">
                {error}
              </div>
            ) : null}
            {hint ? (
              <div
                role="status"
                className="border-b border-amber-400/30 bg-amber-400/10 px-4 py-2 text-center text-xs text-amber-100"
              >
                <button
                  type="button"
                  className="underline underline-offset-2"
                  onClick={() => {
                    setLlmOpen(true);
                    setHint(null);
                  }}
                >
                  {hint}
                </button>
              </div>
            ) : null}
            <ChatView
              messages={messages}
              isStreaming={isStreaming}
              input={input}
              language={language}
              onInput={setInput}
              onSend={() => void send()}
              onPick={(question) => void send(question)}
            />
          </div>
        ) : null}

        {view === "library" ? (
          <LibraryView
            language={language}
            canUpload={Boolean(user)}
            canDelete={user.role === "admin"}
            onAuthRequired={openAuth}
          />
        ) : null}

        {view === "users" && user.role === "admin" ? (
          <UsersView language={language} currentUserId={user.id} />
        ) : null}

        {view === "settings" ? (
          <SettingsView
            language={language}
            onLanguage={toggleLanguage}
            theme={theme}
            onTheme={setTheme}
            user={user}
            byokEnabled={byokEnabled}
            onSaved={refreshLlmState}
            onSignedOut={signedOut}
          />
        ) : null}
      </AppShell>

      {/* Quick BYOK prompt for the 402/hint path; full management lives in Settings. */}
      {llmOpen && byokEnabled ? (
        <div
          className="fixed inset-0 z-50 flex animate-fade-in items-center justify-center bg-black/70 p-4"
          onClick={() => setLlmOpen(false)}
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label={COPY[language].llmTitle}
            className="max-h-[90vh] w-full max-w-2xl animate-scale-in overflow-y-auto"
            onClick={(event) => event.stopPropagation()}
          >
            <LlmKeyPanel
              language={language}
              onClose={() => setLlmOpen(false)}
              onSaved={refreshLlmState}
            />
          </div>
        </div>
      ) : null}
    </>
  );
}
