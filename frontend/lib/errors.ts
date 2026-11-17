/**
 * Single boundary between API failures and the UI.
 *
 * Backend `detail` strings are internal data: they are useful for control flow
 * and logs, but must never be shown to a user. This helper selects a message
 * authored in this codebase from the HTTP status, the request context and the
 * two recognised control-flow strings. Anything unknown degrades to a generic
 * localised message instead of leaking the server text.
 */
import { ApiError } from "./api-error";
import { LLM_KEY_REQUIRED_DETAIL, UNAUTHORISED_DETAIL } from "./api";
import { COPY, type Language } from "./copy";

export type ErrorContext =
  | "generic"
  | "auth"
  | "verify"
  | "documents"
  | "users"
  | "chat"
  | "reset";

export function friendlyError(
  cause: unknown,
  language: Language,
  context: ErrorContext = "generic",
): string {
  const copy = COPY[language];
  const detail = cause instanceof Error ? cause.message : "";
  const status = cause instanceof ApiError ? cause.status : undefined;

  // Known control-flow tokens are translated, never displayed as received.
  if (detail === LLM_KEY_REQUIRED_DETAIL) return copy.llmKeyNeeded;
  if (detail === UNAUTHORISED_DETAIL) return copy.authRequired;

  if (status === 0) return copy.networkError;
  if (status === 402) return copy.llmKeyNeeded;

  if (status === 401 || status === 403) {
    return context === "auth" && status === 401
      ? copy.authInvalidCredentials
      : context === "auth"
        ? copy.authDenied
        : copy.authRequired;
  }

  if (status === 400) {
    if (context === "verify") return copy.verificationFailed;
    if (context === "reset") return copy.resetInvalidLink;
    if (context === "auth") return copy.authInvalidInput;
    return copy.badRequest;
  }

  if (status === 404) return copy.notFound;
  if (status === 409) return context === "documents" ? copy.duplicateFile : copy.conflict;
  if (status === 413) return copy.fileTooLarge;
  if (status === 429) return copy.rateLimited;
  if (status === 501 && context === "reset") return copy.resetUnavailable;

  if (status !== undefined && status >= 500) return copy.serviceUnavailable;

  switch (context) {
    case "verify":
      return copy.verificationFailed;
    case "users":
      return copy.usersError;
    case "auth":
      return copy.authError;
    case "reset":
      return copy.authError;
    default:
      return copy.genericError;
  }
}

/** A failed document ingestion is always reported from local copy. */
export function documentFailureMessage(language: Language): string {
  return COPY[language].processingFailed;
}
