"use client";

import { type FormEvent, type KeyboardEvent } from "react";
import { Loader2, Send } from "lucide-react";

import { COPY, type Language } from "@/lib/copy";

export default function MessageInput({
  value,
  onChange,
  onSend,
  disabled,
  language,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  disabled: boolean;
  language: Language;
}) {
  const copy = COPY[language];

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!disabled && value.trim()) onSend();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!disabled && value.trim()) onSend();
    }
  };

  const placeholder =
    language === "ar"
      ? "اسأل عن مستندات شركتك… (Shift+Enter لسطر جديد)"
      : "Ask about your company documents… (Shift+Enter for a new line)";

  return (
    <form
      onSubmit={submit}
      className="border-t border-app bg-surface px-4 py-3"
    >
      <div className="mx-auto flex w-full max-w-3xl items-end gap-2 rounded-2xl border border-app bg-white/[0.03] p-2 transition focus-within:border-primary-500/50 focus-within:shadow-glow">
        <textarea
          rows={1}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          className="max-h-40 min-h-[2.75rem] flex-1 resize-none bg-transparent px-3 py-2 text-sm text-primary outline-none placeholder:text-muted"
        />
        <button
          type="submit"
          className="btn-primary h-11 w-11 shrink-0 p-0"
          disabled={disabled || !value.trim()}
          aria-label={copy.send}
          title={copy.send}
        >
          {disabled ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Send className="h-4 w-4 flip-rtl" />
          )}
        </button>
      </div>
    </form>
  );
}
