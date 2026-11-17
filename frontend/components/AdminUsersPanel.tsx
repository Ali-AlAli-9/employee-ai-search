"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  KeyRound,
  Loader2,
  RefreshCw,
  Search,
  Trash2,
  UserRound,
  X,
} from "lucide-react";

import {
  deleteUser,
  listUsers,
  resetPassword,
  syncUsers,
  updateUser,
  type AdminUser,
  type UserPage,
} from "@/lib/auth";
import { COPY, type Language } from "@/lib/copy";
import { friendlyError } from "@/lib/errors";

const ROLES = ["viewer", "user", "admin"] as const;
type Role = (typeof ROLES)[number];

function roleLabel(role: Role, t: typeof COPY.en): string {
  return {
    viewer: t.usersRoleViewer,
    user: t.usersRoleUser,
    admin: t.usersRoleAdmin,
  }[role];
}

function initials(name: string | null, email: string | null): string {
  const source = name ?? email?.split("@")[0] ?? "?";
  return source.slice(0, 2).toUpperCase();
}

function when(value: string | null, language: Language): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  try {
    return new Intl.DateTimeFormat(language === "ar" ? "ar" : "en", {
      dateStyle: "medium",
    }).format(date);
  } catch {
    return date.toISOString().slice(0, 10);
  }
}

/**
 * Admin user management: search, pagination, role changes, enable/disable,
 * password reset emails, guest cleanup and a Supabase profile sync.
 *
 * Every mutation is confirmed by a re-read of `/auth/me` on close; individual
 * rows update optimistically only after the server accepts the change, so the
 * table never shows a state the API rejected.
 */
export default function AdminUsersPanel({
  language,
  currentUserId,
  onClose,
}: {
  language: Language;
  currentUserId?: string;
  onClose: () => void;
}) {
  const t = COPY[language];
  const dir = language === "ar" ? "rtl" : "ltr";
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [includeGuests, setIncludeGuests] = useState(false);
  const [data, setData] = useState<UserPage | null>(null);
  const [busy, setBusy] = useState(false);
  const [rowBusy, setRowBusy] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState<string | null>(null);
  const pageSize = 20;

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setData(await listUsers(page, pageSize, q, includeGuests));
    } catch (cause) {
      setError(friendlyError(cause, language, "users"));
    } finally {
      setBusy(false);
    }
  }, [page, q, includeGuests, language]);

  useEffect(() => {
    void load();
  }, [load]);

  const markRow = (id: string, value: boolean) =>
    setRowBusy((current) => ({ ...current, [id]: value }));

  const fail = (cause: unknown) =>
    setError(friendlyError(cause, language, "users"));

  const changeRole = async (user: AdminUser, role: Role) => {
    markRow(user.id, true);
    setError(null);
    setNotice(null);
    try {
      await updateUser(user.id, { role });
      setData((current) =>
        current
          ? {
              ...current,
              items: current.items.map((item) =>
                item.id === user.id ? { ...item, role } : item,
              ),
            }
          : current,
      );
    } catch (cause) {
      fail(cause);
      // Re-read so an optimistic row cannot drift from the server.
      void load();
    } finally {
      markRow(user.id, false);
    }
  };

  const toggleActive = async (user: AdminUser) => {
    markRow(user.id, true);
    setError(null);
    setNotice(null);
    try {
      const next = !user.is_active;
      await updateUser(user.id, { is_active: next });
      setData((current) =>
        current
          ? {
              ...current,
              items: current.items.map((item) =>
                item.id === user.id ? { ...item, is_active: next } : item,
              ),
            }
          : current,
      );
    } catch (cause) {
      fail(cause);
      void load();
    } finally {
      markRow(user.id, false);
    }
  };

  const requestReset = async (userId: string) => {
    setConfirmReset(null);
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await resetPassword(userId);
      setNotice(t.usersResetSent);
    } catch (cause) {
      fail(cause);
    } finally {
      setBusy(false);
    }
  };

  const removeGuest = async (userId: string) => {
    setConfirmDelete(null);
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await deleteUser(userId);
      setData((current) =>
        current
          ? {
              ...current,
              items: current.items.filter((item) => item.id !== userId),
              total: Math.max(0, current.total - 1),
            }
          : current,
      );
    } catch (cause) {
      fail(cause);
    } finally {
      setBusy(false);
    }
  };

  const sync = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await syncUsers();
      await load();
      setNotice(t.usersSyncDone.replace("{count}", String(result.synced)));
    } catch (cause) {
      fail(cause);
    } finally {
      setBusy(false);
    }
  };

  const pages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;
  const remote = data?.provider === "supabase";
  const isSelf = (user: AdminUser) => Boolean(currentUserId && user.id === currentUserId);

  return (
    <section
      dir={dir}
      aria-label={t.usersTitle}
      className="mx-auto mt-4 w-full max-w-5xl px-4"
    >
      <div className="animate-fade-up rounded-2xl border border-white/10 bg-white/[0.04] p-4 shadow-glow">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-accent-500/30 bg-accent-500/10">
            <UserRound className="h-4 w-4 text-accent-400" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold">{t.usersTitle}</h2>
            <p className="mt-1 text-xs text-slate-400">
              {data ? `${data.total} ${t.usersAccounts} · ${data.provider}` : t.loading}
            </p>
          </div>
          {remote ? (
            <button
              type="button"
              className="btn h-8 gap-1.5 px-2 text-xs"
              onClick={() => void sync()}
              disabled={busy}
              title={t.usersSync}
            >
              <RefreshCw className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} />
              <span className="hidden sm:inline">{t.usersSync}</span>
            </button>
          ) : null}
          <button
            type="button"
            className="btn h-8 w-8 p-0"
            onClick={onClose}
            aria-label={t.authClose}
            title={t.authClose}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
          <label className="relative flex-1">
            <Search className="pointer-events-none absolute start-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
            <input
              type="search"
              className="w-full rounded-lg border border-white/10 bg-ink-800 py-2 pe-3 ps-9 text-sm text-slate-100 outline-none focus:border-accent-500/50"
              placeholder={t.usersSearchPlaceholder}
              aria-label={t.usersSearch}
              value={q}
              onChange={(event) => {
                setQ(event.target.value);
                setPage(1);
              }}
            />
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-300">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-white/20 bg-ink-800 accent-accent-500"
              checked={includeGuests}
              onChange={(event) => {
                setIncludeGuests(event.target.checked);
                setPage(1);
              }}
            />
            {t.usersShowGuests}
          </label>
        </div>

        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[46rem] text-sm">
            <caption className="sr-only">{t.usersTitle}</caption>
            <thead>
              <tr className="border-b border-white/10 text-start text-[11px] uppercase tracking-wider text-slate-500">
                <th scope="col" className="pb-2 pe-3 text-start font-medium">
                  {t.authEmail}
                </th>
                <th scope="col" className="pb-2 pe-3 text-start font-medium">
                  {t.usersRole}
                </th>
                <th scope="col" className="pb-2 pe-3 text-start font-medium">
                  {t.usersStatus}
                </th>
                <th scope="col" className="pb-2 pe-3 text-start font-medium">
                  {t.usersCreated}
                </th>
                <th scope="col" className="pb-2 text-end font-medium">
                  {t.usersActions}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {data && data.items.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-8 text-center text-xs text-slate-500">
                    {t.usersEmpty}
                  </td>
                </tr>
              ) : null}
              {!data && busy ? (
                <tr>
                  <td colSpan={5} className="py-8 text-center">
                    <Loader2 className="mx-auto h-5 w-5 animate-spin text-slate-500" />
                  </td>
                </tr>
              ) : null}
              {data?.items.map((user) => {
                const self = isSelf(user);
                const locked = self || Boolean(rowBusy[user.id]) || busy;
                return (
                  <tr key={user.id} className="hover:bg-white/[0.02]">
                    <td className="py-3 pe-3">
                      <div className="flex items-center gap-2">
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.02] text-[11px] font-medium text-slate-300">
                          {initials(user.display_name, user.email)}
                        </div>
                        <div className="min-w-0">
                          <div className="truncate text-slate-100">
                            {user.email ?? "—"}
                          </div>
                          <div className="flex items-center gap-1.5 truncate text-[11px] text-slate-500">
                            {user.display_name ? <span>{user.display_name}</span> : null}
                            {user.is_guest ? (
                              <span className="rounded-full bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-300">
                                {t.usersGuest}
                              </span>
                            ) : null}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="py-3 pe-3">
                      <select
                        className="rounded-lg border border-white/10 bg-ink-800 px-2 py-1 text-xs text-slate-100 outline-none focus:border-accent-500/50 disabled:opacity-50"
                        value={user.role}
                        aria-label={t.usersRole}
                        onChange={(event) =>
                          void changeRole(user, event.target.value as Role)
                        }
                        disabled={locked}
                        title={self ? t.usersGuardSelf : t.usersRole}
                      >
                        {ROLES.map((role) => (
                          <option key={role} value={role}>
                            {roleLabel(role, t)}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="py-3 pe-3">
                      <button
                        type="button"
                        className={`inline-flex items-center rounded-full px-2 py-1 text-[11px] font-medium disabled:opacity-50 ${
                          user.is_active
                            ? "bg-emerald-500/15 text-emerald-300"
                            : "bg-red-500/15 text-red-300"
                        }`}
                        onClick={() => void toggleActive(user)}
                        disabled={locked}
                        title={self ? t.usersGuardSelf : t.usersStatus}
                      >
                        {user.is_active ? t.usersActive : t.usersDisabled}
                      </button>
                    </td>
                    <td className="py-3 pe-3 text-xs text-slate-400">
                      {when(user.created_at, language)}
                    </td>
                    <td className="py-3 text-end">
                      <div className="flex items-center justify-end gap-1">
                        {remote && !user.is_guest ? (
                          <button
                            type="button"
                            className="btn h-8 w-8 p-0"
                            onClick={() => setConfirmReset(user.id)}
                            disabled={busy}
                            aria-label={t.usersResetPassword}
                            title={t.usersResetPassword}
                          >
                            <KeyRound className="h-3.5 w-3.5" />
                          </button>
                        ) : null}
                        {user.is_guest ? (
                          <button
                            type="button"
                            className="btn h-8 w-8 p-0 text-red-300 hover:bg-red-500/10"
                            onClick={() => setConfirmDelete(user.id)}
                            disabled={busy}
                            aria-label={t.usersDelete}
                            title={t.usersDelete}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {data && data.total > pageSize ? (
          <div className="mt-4 flex items-center justify-between gap-3 text-xs text-slate-500">
            <span>
              {t.usersPage} {page} {t.usersOf} {pages}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="btn h-8 w-8 p-0"
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                disabled={page <= 1 || busy}
                aria-label={t.usersPrevious}
                title={t.usersPrevious}
              >
                <ChevronLeft className="h-4 w-4 rtl:rotate-180" />
              </button>
              <button
                type="button"
                className="btn h-8 w-8 p-0"
                onClick={() => setPage((current) => Math.min(pages, current + 1))}
                disabled={page >= pages || busy}
                aria-label={t.usersNext}
                title={t.usersNext}
              >
                <ChevronRight className="h-4 w-4 rtl:rotate-180" />
              </button>
            </div>
          </div>
        ) : null}

        {data && !remote ? (
          <p className="mt-4 text-[11px] text-slate-500">{t.usersLocalNote}</p>
        ) : null}

        {error ? (
          <p role="alert" className="mt-4 flex items-start gap-2 text-xs text-red-300">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {error}
          </p>
        ) : null}
        {notice ? (
          <p role="status" className="mt-4 flex items-start gap-2 text-xs text-emerald-300">
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {notice}
          </p>
        ) : null}
      </div>

      {confirmDelete ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => setConfirmDelete(null)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-delete-title"
        >
          <div
            className="w-full max-w-sm rounded-2xl border border-white/10 bg-ink-800 p-5 shadow-glow"
            onClick={(event) => event.stopPropagation()}
          >
            <h3 id="confirm-delete-title" className="text-sm font-semibold">
              {t.usersConfirmDelete}
            </h3>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                className="btn"
                onClick={() => setConfirmDelete(null)}
              >
                {t.usersCancel}
              </button>
              <button
                type="button"
                className="btn bg-red-500/20 text-red-200 hover:bg-red-500/30"
                onClick={() => void removeGuest(confirmDelete)}
                disabled={busy}
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : t.usersDelete}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {confirmReset ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => setConfirmReset(null)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-reset-title"
        >
          <div
            className="w-full max-w-sm rounded-2xl border border-white/10 bg-ink-800 p-5 shadow-glow"
            onClick={(event) => event.stopPropagation()}
          >
            <h3 id="confirm-reset-title" className="text-sm font-semibold">
              {t.usersConfirmReset}
            </h3>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                className="btn"
                onClick={() => setConfirmReset(null)}
              >
                {t.usersCancel}
              </button>
              <button
                type="button"
                className="btn-primary"
                onClick={() => void requestReset(confirmReset)}
                disabled={busy}
              >
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  t.usersResetPassword
                )}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
