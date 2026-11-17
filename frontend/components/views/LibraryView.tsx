"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  FileText,
  Loader2,
  Search,
  Trash2,
  Upload,
} from "lucide-react";

import Modal from "@/components/Modal";
import {
  deleteDocument,
  DuplicateDocumentError,
  getDocument,
  listDocuments,
  UNAUTHORISED_DETAIL,
  uploadDocument,
} from "@/lib/api";
import { COPY, type Language } from "@/lib/copy";
import { friendlyError } from "@/lib/errors";
import { formatBytes, timeAgo } from "@/lib/format";
import type { DocumentInfo } from "@/lib/types";

function statusBadge(status: string, language: Language) {
  const copy = COPY[language];
  if (status === "completed") {
    return (
      <span className="badge bg-emerald-500/15 text-emerald-300">
        <CheckCircle2 className="h-3 w-3" /> {copy.ready}
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="badge bg-red-500/15 text-red-300">
        <AlertCircle className="h-3 w-3" /> {copy.failed}
      </span>
    );
  }
  const label =
    status === "processing"
      ? copy.processing
      : status === "pending"
        ? copy.pending
        : status;
  return (
    <span className="badge bg-amber-500/15 text-amber-300">
      <Clock className="h-3 w-3" /> {label}
    </span>
  );
}

/**
 * Full-page library. The API sequence is the same as the old DocumentPanel:
 * list → upload → poll getDocument until indexed → refresh; duplicate 409 asks
 * before replacing; deletes stay gated by the server, not by this component.
 */
export default function LibraryView({
  language,
  canUpload,
  canDelete,
  onAuthRequired,
}: {
  language: Language;
  canUpload: boolean;
  canDelete: boolean;
  onAuthRequired: () => void;
}) {
  const copy = COPY[language];
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [phase, setPhase] = useState<"idle" | "uploading" | "indexing">("idle");
  const [progress, setProgress] = useState(0);
  const [query, setQuery] = useState("");
  const [dragging, setDragging] = useState(false);
  const [duplicate, setDuplicate] = useState<{ file: File; existingId: string } | null>(
    null,
  );
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const aliveRef = useRef(true);

  const fail = useCallback(
    (cause: unknown) => {
      setError(friendlyError(cause, language, "documents"));
      if (cause instanceof Error && cause.message === UNAUTHORISED_DETAIL) {
        onAuthRequired();
      }
    },
    [language, onAuthRequired],
  );

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    try {
      setDocuments(await listDocuments());
      setError(null);
    } catch (cause) {
      fail(cause);
    } finally {
      setLoading(false);
    }
  }, [fail]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const waitUntilIndexed = useCallback(
    async (documentId: string) => {
      for (let attempt = 0; attempt < 150; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
        if (!aliveRef.current) return;
        try {
          const document = await getDocument(documentId);
          await refresh();
          if (document.status === "completed" || document.status === "failed") return;
        } catch {
          // Transient network error while the service wakes up: keep polling.
        }
      }
    },
    [refresh],
  );

  const upload = async (file: File, replace: boolean) => {
    setPhase("uploading");
    setProgress(0);
    setError(null);
    setDuplicate(null);
    try {
      const documentId = await uploadDocument(file, setProgress, { replace });
      setPhase("indexing");
      await refresh();
      if (documentId) await waitUntilIndexed(documentId);
      await refresh();
    } catch (cause) {
      if (cause instanceof DuplicateDocumentError) {
        setDuplicate({ file, existingId: cause.documentId });
      } else {
        fail(cause);
      }
    } finally {
      setPhase("idle");
      setProgress(0);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const remove = async (id: string) => {
    setDeleting(true);
    try {
      await deleteDocument(id);
      await refresh();
      setDeletingId(null);
    } catch (cause) {
      fail(cause);
    } finally {
      setDeleting(false);
    }
  };

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return documents;
    return documents.filter((document) =>
      document.filename.toLowerCase().includes(needle),
    );
  }, [documents, query]);

  const stats = useMemo(
    () => [
      { label: copy.statDocuments, value: documents.length, icon: FileText },
      {
        label: copy.ready,
        value: documents.filter((item) => item.status === "completed").length,
        icon: CheckCircle2,
      },
      {
        label: copy.chunks,
        value: documents.reduce((sum, item) => sum + item.chunks_count, 0),
        icon: FileText,
      },
    ],
    [documents, copy],
  );

  const busy = phase !== "idle";

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
              <p className="text-xs capitalize text-muted">{stat.label}</p>
            </div>
          </div>
        ))}
      </div>

      {canUpload ? (
        <label
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            void upload(event.dataTransfer.files[0], false);
          }}
          className={`flex cursor-pointer flex-col items-center gap-2 rounded-2xl border-2 border-dashed px-6 py-8 text-center transition ${
            dragging
              ? "border-primary-500 bg-primary-500/10"
              : "border-white/15 bg-surface/60 hover:border-primary-500/50 hover:bg-white/5"
          }`}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.docx,.txt,.md,.markdown"
            className="hidden"
            onChange={(event) => void upload(event.target.files?.[0] as File, false)}
            disabled={busy}
          />
          {busy ? (
            <>
              <Loader2 className="h-6 w-6 animate-spin text-primary-400" />
              <p className="text-sm font-medium text-primary">
                {phase === "uploading"
                  ? `${copy.uploading} ${progress}%`
                  : copy.indexing}
              </p>
              <span className="h-1.5 w-full max-w-xs overflow-hidden rounded-full bg-white/10">
                <span
                  className="block h-full rounded-full bg-primary-500 transition-[width] duration-200"
                  style={{ width: `${phase === "uploading" ? progress : 100}%` }}
                />
              </span>
            </>
          ) : (
            <>
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary-500/15">
                <Upload className="h-5 w-5 text-primary-400" />
              </div>
              <p className="text-sm font-medium text-primary">{copy.upload}</p>
              <p className="text-xs text-muted">{copy.uploadHint}</p>
            </>
          )}
        </label>
      ) : (
        <p className="rounded-xl border border-white/10 bg-surface/60 p-4 text-xs text-secondary">
          {copy.readOnlyDocs}
        </p>
      )}

      {error ? (
        <p role="alert" className="rounded-lg bg-red-500/10 p-3 text-xs text-red-300">
          {error}
        </p>
      ) : null}

      <div className="card overflow-hidden">
        <div className="flex items-center gap-3 border-b border-white/10 p-4">
          <h2 className="text-sm font-semibold text-primary">{copy.knowledgeBase}</h2>
          <label className="relative ms-auto w-full max-w-xs">
            <Search className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={copy.searchDocuments}
              aria-label={copy.searchDocuments}
              className="input ps-9"
            />
          </label>
        </div>

        {loading ? (
          <div className="flex items-center justify-center gap-2 p-10 text-xs text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> {copy.loading}
          </div>
        ) : visible.length === 0 ? (
          <p className="p-10 text-center text-sm text-muted">{copy.emptyDocs}</p>
        ) : (
          <div className="overflow-x-auto">
            <div className="min-w-[44rem]">
              <div className="grid grid-cols-[2.4fr_1fr_0.8fr_0.8fr_3rem] gap-3 border-b border-white/10 px-4 py-2 text-[11px] uppercase tracking-wide text-muted">
                <span>{copy.columnName}</span>
                <span>{copy.usersStatus}</span>
                <span>{copy.chunks}</span>
                <span>{copy.usersCreated}</span>
                <span />
              </div>
              {visible.map((document) => (
                <div
                  key={document.id}
                  className="grid grid-cols-[2.4fr_1fr_0.8fr_0.8fr_3rem] items-center gap-3 border-b border-white/5 px-4 py-3 text-xs last:border-0 hover:bg-white/[0.02]"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-500/15">
                      <FileText className="h-4 w-4 text-primary-400" />
                    </div>
                    <div className="min-w-0">
                      <p className="truncate font-medium text-primary">
                        {document.filename}
                      </p>
                      <p className="text-[11px] text-muted">
                        {formatBytes(document.size_bytes)}
                      </p>
                    </div>
                  </div>
                  <div>{statusBadge(document.status, language)}</div>
                  <div className="text-secondary">{document.chunks_count}</div>
                  <div className="text-secondary">
                    {timeAgo(document.created_at, language)}
                  </div>
                  <div>
                    {canDelete ? (
                      <button
                        type="button"
                        className="btn-ghost h-8 w-8 p-0 text-red-300"
                        onClick={() => setDeletingId(document.id)}
                        disabled={deletingId === document.id}
                        aria-label={`${copy.delete} ${document.filename}`}
                        title={copy.delete}
                      >
                        {deletingId === document.id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Trash2 className="h-3.5 w-3.5" />
                        )}
                      </button>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {duplicate ? (
        <Modal
          title={copy.duplicateFile}
          language={language}
          confirmLabel={copy.replaceFile}
          onClose={() => setDuplicate(null)}
          onConfirm={() => void upload(duplicate.file, true)}
        >
          {duplicate.file.name}
        </Modal>
      ) : null}

      {deletingId ? (
        <Modal
          title={copy.delete}
          language={language}
          confirmLabel={copy.delete}
          danger
          onClose={() => {
            if (!deleting) setDeletingId(null);
          }}
          onConfirm={() => void remove(deletingId)}
          busy={deleting}
        >
          {documents.find((item) => item.id === deletingId)?.filename}
        </Modal>
      ) : null}
    </div>
  );
}
