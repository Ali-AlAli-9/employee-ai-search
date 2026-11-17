"use client";

import { useEffect, useRef } from "react";
import { Bot, User } from "lucide-react";

import CitationCard from "./CitationCard";
import { COPY, type Language } from "@/lib/copy";
import type { ChatMessage } from "@/lib/types";

function dedupeCitations(message: ChatMessage) {
  const seen = new Set<string>();
  return (message.citations ?? []).filter((citation) => {
    if (seen.has(citation.chunk_id)) return false;
    seen.add(citation.chunk_id);
    return true;
  });
}

export default function MessageList({
  messages,
  isStreaming,
  language,
}: {
  messages: ChatMessage[];
  isStreaming: boolean;
  language: Language;
}) {
  const endRef = useRef<HTMLDivElement | null>(null);
  const copy = COPY[language];

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isStreaming]);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-4 py-6">
      {messages.map((message, index) => {
        const isUser = message.role === "user";
        const citations = dedupeCitations(message);
        const isLast = index === messages.length - 1;
        return (
          <div
            key={index}
            className={`flex animate-fade-up gap-3 ${isUser ? "justify-end" : "justify-start"}`}
          >
            {!isUser ? (
              <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-primary-500/30 bg-primary-500/10">
                <Bot className="h-4 w-4 text-primary-400" />
              </div>
            ) : null}

            <div
              className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                isUser
                  ? "bg-primary-600 text-white ring-1 ring-primary-500/25"
                  : "card"
              }`}
            >
              <p className="whitespace-pre-wrap break-words">
                {message.content}
                {!isUser && isStreaming && isLast ? (
                  <span className="ms-1 inline-block h-4 w-1.5 animate-pulse bg-primary-400 align-middle" />
                ) : null}
              </p>

              {!isUser && citations.length > 0 ? (
                <div className="mt-3 space-y-2 border-t border-white/10 pt-3">
                  <p className="text-[11px] uppercase tracking-wide text-muted">
                    {copy.sources}
                  </p>
                  {citations.map((citation) => (
                    <CitationCard
                      key={citation.chunk_id}
                      citation={citation}
                      language={language}
                    />
                  ))}
                </div>
              ) : null}
            </div>

            {isUser ? (
              <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-app bg-surface-elevated">
                <User className="h-4 w-4 text-secondary" />
              </div>
            ) : null}
          </div>
        );
      })}
      <div ref={endRef} />
    </div>
  );
}
