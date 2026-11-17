"use client";

import type { Language } from "@/lib/copy";

export const SAMPLES: Record<Language, string[]> = {
  en: [
    "How many annual leave days do employees get?",
    "What is the remote work policy?",
    "Summarize the sick leave requirements.",
  ],
  ar: [
    "كم عدد أيام الإجازة السنوية للموظفين؟",
    "ما هي سياسة العمل عن بُعد؟",
    "لخّص متطلبات الإجازة المرضية.",
  ],
};

/**
 * First view before any message: a short prompt and a few example questions.
 * Intentionally icon-free (see EmptyState.test.tsx) and fully localized.
 */
export default function EmptyState({
  language,
  onPick,
}: {
  language: Language;
  onPick: (question: string) => void;
}) {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col items-center gap-6 px-6 py-16 text-center animate-fade-in-up">
      <div className="space-y-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-primary-500">
          {language === "ar" ? "البحث الذكي في المستندات" : "DOCUMENT INTELLIGENCE"}
        </p>
        <h2 className="text-2xl font-bold text-primary">
          {language === "ar" ? "ابحث في مستندات شركتك" : "Ask about your company documents"}
        </h2>
        <p className="mx-auto max-w-md text-sm leading-relaxed text-secondary">
          {language === "ar"
            ? "ارفع المستندات ثم اطرح سؤالاً. تحصل على إجابة موثّقة بالمصادر."
            : "Upload documents, then ask a question. Get cited answers from your sources."}
        </p>
      </div>
      <div className="grid w-full gap-2 sm:grid-cols-1">
        {SAMPLES[language].map((sample) => (
          <button
            key={sample}
            type="button"
            onClick={() => onPick(sample)}
            className="rounded-xl border border-app bg-surface/60 px-4 py-3 text-start text-sm text-secondary transition hover:border-primary-500/50 hover:bg-primary-500/5 hover:text-primary"
          >
            {sample}
          </button>
        ))}
      </div>
    </div>
  );
}
