"use client";

import { useState } from "react";
import { BookOpen, ChevronDown } from "lucide-react";

import { COPY, type Language } from "@/lib/copy";
import type { Citation } from "@/lib/types";

export default function CitationCard({
  citation,
  language,
}: {
  citation: Citation;
  language: Language;
}) {
  const [open, setOpen] = useState(false);
  const index = citation.index ?? citation.chunk_index + 1;
  const copy = COPY[language];
  const label = citation.page_label?.trim();
  const pageText = label || (typeof citation.page_number === "number" ? String(citation.page_number) : null);
  // Page inference removed: citations only show the page provided by the system (page_label or page_number).

  return (
    <button
      type="button"
      onClick={() => setOpen((value) => !value)}
      className="block w-full rounded-xl border border-app bg-surface/60 px-3 py-2 text-start transition hover:border-primary-500/40 hover:bg-primary-500/5"
      aria-expanded={open}
    >
      <span className="flex items-center gap-2 text-xs text-secondary">
        <span className="rounded-md bg-primary-500/15 px-1.5 py-0.5 font-mono text-[11px] text-primary-300">
          [{index}]
        </span>
        <BookOpen className="h-3.5 w-3.5 shrink-0 text-muted" />
        <span className="truncate">{citation.document_filename || "document"}</span>
        {pageText ? (
          <span className="chip shrink-0">
            {copy.page}
            {pageText}
          </span>
        ) : null}
        <ChevronDown
          className={`ms-auto h-4 w-4 shrink-0 text-muted transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </span>
      {open ? (
        <span className="mt-2 block border-t border-white/10 pt-2 text-xs leading-relaxed text-secondary">
          {citation.text_snippet}
        </span>
      ) : null}
    </button>
  );
}
