"use client";

import EmptyState from "@/components/EmptyState";
import MessageInput from "@/components/MessageInput";
import MessageList from "@/components/MessageList";
import type { Language } from "@/lib/copy";
import type { ChatMessage } from "@/lib/types";

/** Presentational chat surface; streaming and BYOK decisions stay in ChatInterface. */
export default function ChatView({
  messages,
  isStreaming,
  input,
  language,
  onInput,
  onSend,
  onPick,
}: {
  messages: ChatMessage[];
  isStreaming: boolean;
  input: string;
  language: Language;
  onInput: (value: string) => void;
  onSend: () => void;
  onPick: (question: string) => void;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <main className="flex-1 overflow-y-auto">
        {messages.length === 0 ? (
          <EmptyState language={language} onPick={onPick} />
        ) : (
          <MessageList messages={messages} isStreaming={isStreaming} language={language} />
        )}
      </main>
      <MessageInput
        value={input}
        onChange={onInput}
        onSend={onSend}
        disabled={isStreaming}
        language={language}
      />
    </div>
  );
}
