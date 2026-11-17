"use client";

import type { ReactNode } from "react";
import { X } from "lucide-react";

import { COPY, type Language } from "@/lib/copy";

/** Shared accessible confirmation dialog used by library and admin views. */
export default function Modal({
  title,
  children,
  onClose,
  language,
  confirmLabel,
  onConfirm,
  busy = false,
  danger = false,
}: {
  title: string;
  children?: ReactNode;
  onClose: () => void;
  language: Language;
  confirmLabel: string;
  onConfirm: () => void;
  busy?: boolean;
  danger?: boolean;
}) {
  const copy = COPY[language];
  return (
    <div
      className="fixed inset-0 z-50 flex animate-fade-in items-center justify-center bg-black/70 p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        className="w-full max-w-sm animate-scale-in rounded-2xl border border-app bg-surface-elevated p-5 shadow-modal"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start gap-3">
          <h3 id="modal-title" className="flex-1 text-sm font-semibold text-primary">
            {title}
          </h3>
          <button
            type="button"
            className="btn-ghost h-8 w-8 p-0"
            onClick={onClose}
            disabled={busy}
            aria-label={copy.closePanel}
            title={copy.closePanel}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {children ? <div className="mt-3 text-xs text-secondary">{children}</div> : null}
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            className="btn-secondary"
            onClick={onClose}
            disabled={busy}
          >
            {copy.usersCancel}
          </button>
          <button
            type="button"
            className={danger ? "btn-danger" : "btn-primary"}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
