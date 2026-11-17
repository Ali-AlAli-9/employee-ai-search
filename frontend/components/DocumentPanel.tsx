"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  FileText,
  Loader2,
  Trash2,
  Upload,
  X,
} from "lucide-react";

import {
  deleteDocument,
  DuplicateDocumentError,
  getDocument,
  listDocuments,
  UNAUTHORISED_DETAIL,
  uploadDocument,
} from "@/lib/api";
import { COPY, type Language } from "@/lib/copy";
import { documentFailureMessage, friendlyError } from "@/lib/errors";
import type { DocumentInfo } from "@/lib/types";

function statusBadge(status: string, language: Language) {
  const copy = COPY[language];
  if (status === "completed") {
    return (
      <span className="chip text-emerald-300">
        <CheckCircle2 className="h-3 w-3" /> {copy.ready}
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="chip text-red-300">
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
    <span className="chip text-amber-300">
      <Clock className="h-3 w-3" /> {label}
    </span>
  );
}

export default function DocumentPanel({
  onClose,
  language,
  canUpload,
  canDelete,
  onAuthRequired,
}: {
  onClose: () => void;
  language: Language;
  /** Any signed-in account may add documents; guests included. */
  canUpload: boolean;
  /** Deleting stays admin-only on the server; mirror that in the UI. */
  canDelete: boolean;
  /** Called when the server says there is no session, so the UI can ask for one. */
  onAuthRequired?: () => void;
}) {
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [phase, setPhase] = useState<"idle" | "uploading" | "indexing">("idle");
  const [progress, setProgress] = useState(0);
  const [duplicate, setDuplicate] = useState<{ file: File; existingId: string } | null>(
    null,
  );
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const aliveRef = useRef(true);
  const copy = COPY[language];

  /** Show a localised failure and, for a missing session, reopen the account panel. */
  const fail = useCallback(
    (cause: unknown) => {
      setError(friendlyError(cause, language, "documents"));
      if (cause instanceof Error && cause.message === UNAUTHORISED_DETAIL) {
        onAuthRequired?.();
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

  // Ingestion runs in the background on the server, so the row would sit on
  // "pending" forever if we only refreshed twice. Poll until it settles.
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
      if (documentId) {
        await waitUntilIndexed(documentId);
        await refresh();
      }
    } catch (cause) {
      if (cause instanceof DuplicateDocumentError) {
        // Ask before deleting an existing, possibly cited, document.
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

  const handleFiles = async (files: FileList | null) => {
    const file = files?.[0];
    if (file) await upload(file, false);
  };

  const remove = async (id: string) => {
    setDeletingId(id);
    try {
      await deleteDocument(id);
      await refresh();
    } catch (cause) {
      fail(cause);
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-white/10 px-4 py-3">
        <FileText className="h-4 w-4 text-accent-400" />
        <h2 className="text-sm font-semibold">{copy.knowledgeBase}</h2>
        <button
          type="button"
          className="btn ms-auto h-8 w-8 p-0"
          onClick={onClose}
          aria-label={copy.closePanel}
          title={copy.closePanel}
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="space-y-3 border-b border-white/10 p-4">
        {canUpload ? (
          <label className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed border-white/15 bg-white/[0.02] px-4 py-5 text-center transition hover:border-accent-500/50 hover:bg-white/[0.05]">
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.docx,.txt,.md,.markdown"
            className="hidden"
            onChange={(event) => void handleFiles(event.target.files)}
            disabled={phase !== "idle"}
          />
          {phase === "uploading" ? (
            <>
              <Loader2 className="h-5 w-5 animate-spin text-accent-400" />
              <span className="text-xs font-medium text-slate-200">
                {copy.uploading} {progress}%
              </span>
              <span className="mt-0.5 h-1.5 w-full max-w-[220px] overflow-hidden rounded-full bg-white/10">
                <span
                  className="block h-full rounded-full bg-accent-500 transition-[width] duration-200"
                  style={{ width: `${progress}%` }}
                />
              </span>
              <span className="text-[11px] text-slate-500">{copy.uploadHint}</span>
            </>
          ) : phase === "indexing" ? (
            <>
              <Loader2 className="h-5 w-5 animate-spin text-accent-400" />
              <span className="text-xs font-medium text-slate-200">{copy.indexing}</span>
              <span className="text-[11px] text-slate-500">{copy.uploadHint}</span>
            </>
          ) : (
            <>
              <Upload className="h-5 w-5 text-accent-400" />
              <span className="text-xs font-medium text-slate-200">{copy.upload}</span>
              <span className="text-[11px] text-slate-500">{copy.uploadHint}</span>
            </>
          )}
        </label>
        ) : (
          <p className="rounded-xl border border-white/10 bg-white/[0.02] px-4 py-3 text-[11px] text-slate-400">
            {copy.readOnlyDocs}
          </p>
        )}

        {error ? (
          <p className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
            {error}
          </p>
        ) : null}

        {duplicate ? (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-100">
            <p>{copy.duplicateFile}</p>
            <button
              type="button"
              className="btn mt-2 h-7 px-3 text-[11px]"
              onClick={() => void upload(duplicate.file, true)}
            >
              {copy.replaceFile}
            </button>
          </div>
        ) : null}
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {loading ? (
          <div className="flex items-center justify-center gap-2 py-8 text-xs text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" /> {copy.loading}
          </div>
        ) : documents.length === 0 ? (
          <p className="px-2 py-8 text-center text-xs text-slate-500">{copy.emptyDocs}</p>
        ) : (
          <ul className="space-y-2">
            {documents.map((document) => (
              <li
                key={document.id}
                className="rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2"
              >
                <div className="flex items-start gap-2">
                  <FileText className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium text-slate-200">
                      {document.filename}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      {statusBadge(document.status, language)}
                      <span className="chip">
                        {document.chunks_count} {copy.chunks}
                      </span>
                    </div>
                    {document.status === "failed" ? (
                      <p className="mt-1 line-clamp-2 text-[11px] text-red-300">
                        {documentFailureMessage(language)}
                      </p>
                    ) : null}
                  </div>
                  {canDelete ? (
                    <button
                      type="button"
                      className="btn h-7 w-7 shrink-0 p-0"
                      onClick={() => void remove(document.id)}
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
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
