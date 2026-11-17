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
  ShieldCheck,
  Users,
} from "lucide-react";

import Modal from "@/components/Modal";
import {
  listUsers,
  resetPassword,
  syncUsers,
  updateUser,
  type AdminUser,
  type UserPage,
} from "@/lib/auth";
import { COPY, type Language } from "@/lib/copy";
import { friendlyError } from "@/lib/errors";
import { timeAgo } from "@/lib/format";

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

/** Full-page admin view; every mutation still goes through the real admin API. */
export default function UsersView({
  language,
  currentUserId,
}: {
  language: Language;
  currentUserId?: string;
}) {
  const t = COPY[language];
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [data, setData] = useState<UserPage | null>(null);
  const [busy, setBusy] = useState(false);
  const [rowBusy, setRowBusy] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState<string | null>(null);
  const pageSize = 20;

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setData(await listUsers(page, pageSize, q));
    } catch (cause) {
      setError(friendlyError(cause, language, "users"));
    } finally {
      setBusy(false);
    }
  }, [page, q, language]);

  useEffect(() => {
    void load();
  }, [load]);

  const markRow = (id: string, value: boolean) =>
    setRowBusy((current) => ({ ...current, [id]: value }));

  const fail = (cause: unknown) => {
    setError(friendlyError(cause, language, "users"));
    void load();
  };

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
      setError(friendlyError(cause, language, "users"));
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
      setError(friendlyError(cause, language, "users"));
    } finally {
      setBusy(false);
    }
  };

  const pages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;
  const remote = data?.provider === "supabase";
  const isSelf = (user: AdminUser) => Boolean(currentUserId && user.id === currentUserId);
  const items = data?.items ?? [];
  const stats = [
    { label: t.usersAccounts, value: data?.total ?? 0, icon: Users },
    {
      label: t.statAdmins,
      value: items.filter((item) => item.role === "admin").length,
      icon: ShieldCheck,
    },
    {
      label: t.statMembers,
      value: items.filter((item) => item.role !== "admin").length,
      icon: Users,
    },
  ];

  return (
    <div className="mx-auto w-full max-w-6xl space-y-5 p-4 md:p-6">
      <div className="grid gap-3 sm:grid-cols-3">
        {stats.map((stat) => (
          <div key={stat.label} className="card flex items-center gap-3 p-4">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-500/15">
              <stat.icon className="h-4 w-4 text-primary-400" />
            </div>
            <div>
              <p className="text-xl font-semibold text-primary">{stat.value}</p>
              <p className="text-xs text-muted">{stat.label}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="card overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-white/10 p-4 sm:flex-row sm:items-center">
          <label className="relative flex-1">
            <Search className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <input
              type="search"
              className="input ps-9"
              placeholder={t.usersSearchPlaceholder}
              aria-label={t.usersSearch}
              value={q}
              onChange={(event) => {
                setQ(event.target.value);
                setPage(1);
              }}
            />
          </label>
          {remote ? (
            <button
              type="button"
              className="btn-secondary"
              onClick={() => void sync()}
              disabled={busy}
            >
              <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />
              {t.usersSync}
            </button>
          ) : null}
        </div>

        {error ? (
          <p role="alert" className="flex items-center gap-2 bg-red-500/10 p-3 text-xs text-red-300">
            <AlertCircle className="h-3.5 w-3.5" /> {error}
          </p>
        ) : null}
        {notice ? (
          <p role="status" className="flex items-center gap-2 bg-emerald-500/10 p-3 text-xs text-emerald-300">
            <CheckCircle2 className="h-3.5 w-3.5" /> {notice}
          </p>
        ) : null}

        <div className="overflow-x-auto">
          <div className="min-w-[48rem]">
            <div className="grid grid-cols-[2.4fr_1fr_1fr_1fr_6rem] gap-3 border-b border-white/10 px-4 py-2 text-[11px] uppercase tracking-wide text-muted">
              <span>{t.authEmail}</span>
              <span>{t.usersRole}</span>
              <span>{t.usersStatus}</span>
              <span>{t.usersCreated}</span>
              <span className="text-end">{t.usersActions}</span>
            </div>
            {!data && busy ? (
              <div className="flex justify-center p-10">
                <Loader2 className="h-5 w-5 animate-spin text-muted" />
              </div>
            ) : items.length === 0 ? (
              <p className="p-10 text-center text-xs text-muted">{t.usersEmpty}</p>
            ) : (
              items.map((user) => {
                const self = isSelf(user);
                const locked = self || Boolean(rowBusy[user.id]) || busy;
                return (
                  <div
                    key={user.id}
                    className="grid grid-cols-[2.4fr_1fr_1fr_1fr_6rem] items-center gap-3 border-b border-white/5 px-4 py-3 text-xs last:border-0 hover:bg-white/[0.02]"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-500/15 text-[11px] font-medium text-primary-300">
                        {initials(user.display_name, user.email)}
                      </div>
                      <div className="min-w-0">
                        <p className="truncate font-medium text-primary">
                          {user.email ?? "—"}
                        </p>
                        <p className="truncate text-[11px] text-muted">
                          {user.display_name}
                        </p>
                      </div>
                    </div>
                    <div>
                      <select
                        className="input w-auto py-1 text-xs"
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
                    </div>
                    <div>
                      <button
                        type="button"
                        className={`badge ${
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
                    </div>
                    <div className="text-secondary">{timeAgo(user.created_at, language)}</div>
                    <div className="flex justify-end gap-1">
                      {remote ? (
                        <button
                          type="button"
                          className="btn-ghost h-8 w-8 p-0"
                          onClick={() => setConfirmReset(user.id)}
                          disabled={busy}
                          aria-label={t.usersResetPassword}
                          title={t.usersResetPassword}
                        >
                          <KeyRound className="h-3.5 w-3.5" />
                        </button>
                      ) : null}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {data && data.total > pageSize ? (
          <div className="flex items-center justify-between gap-3 border-t border-white/10 p-4 text-xs text-muted">
            <span>
              {t.usersPage} {page} {t.usersOf} {pages}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                className="btn-secondary h-8 w-8 p-0"
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                disabled={page <= 1 || busy}
                aria-label={t.usersPrevious}
              >
                <ChevronLeft className="h-4 w-4 flip-rtl" />
              </button>
              <button
                type="button"
                className="btn-secondary h-8 w-8 p-0"
                onClick={() => setPage((current) => Math.min(pages, current + 1))}
                disabled={page >= pages || busy}
                aria-label={t.usersNext}
              >
                <ChevronRight className="h-4 w-4 flip-rtl" />
              </button>
            </div>
          </div>
        ) : null}
        {data && !remote ? <p className="p-4 text-[11px] text-muted">{t.usersLocalNote}</p> : null}
      </div>

      {confirmReset ? (
        <Modal
          title={t.usersConfirmReset}
          language={language}
          confirmLabel={t.usersResetPassword}
          busy={busy}
          onClose={() => setConfirmReset(null)}
          onConfirm={() => void requestReset(confirmReset)}
        />
      ) : null}
    </div>
  );
}
