import { ApiError } from "./api-error";
import { CREDENTIALS, csrfHeader } from "./auth";
import { llmHeaders, type LlmKey, type LlmVerifyResult } from "./llm";
import type {
  ChatMessage,
  Citation,
  DocumentInfo,
  DocumentListResponse,
  DonePayload,
} from "./types";

// When NEXT_PUBLIC_API_URL is set the browser talks to the backend directly.
// Otherwise requests go through the same-origin Next.js proxy (/app/api/v1).
const DIRECT_API = process.env.NEXT_PUBLIC_API_URL;
const DIRECT_KEY = process.env.NEXT_PUBLIC_API_KEY;
const BASE = DIRECT_API ? `${DIRECT_API.replace(/\/$/, "")}/api/v1` : "/api/v1";

/** The backend detail for a request with neither a session nor an API key. */
export const UNAUTHORISED_DETAIL = "Invalid or missing credentials";

/** The backend detail when only an admin may spend the deployment's LLM key. */
export const LLM_KEY_REQUIRED_DETAIL =
  "The server API key is reserved for administrators. Add your own provider key to continue.";

/**
 * Headers for one request.
 *
 * `unsafe` adds the double-submit CSRF token. It is required whenever the
 * session cookie authenticates the call, i.e. every POST/PUT/PATCH/DELETE.
 * API-key requests ignore it.
 */
function headers(
  extra: Record<string, string> = {},
  unsafe = false,
): Record<string, string> {
  const result: Record<string, string> = { ...extra };
  if (DIRECT_API && DIRECT_KEY) result["X-API-Key"] = DIRECT_KEY;
  if (unsafe) Object.assign(result, csrfHeader());
  return result;
}

/**
 * Read a failure without turning it into a display string.
 *
 * The raw detail is kept on the error object only so callers can recognise
 * control-flow tokens. Rendering always happens through `friendlyError`.
 */
async function readError(response: Response): Promise<ApiError> {
  let detail: string;
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") detail = body.detail;
    else if (typeof body?.detail?.message === "string") detail = body.detail.message;
    else detail = `HTTP ${response.status}`;
  } catch {
    detail = `HTTP ${response.status} ${response.statusText}`;
  }
  return new ApiError(response.status, detail);
}

interface DuplicateDetail {
  message: string;
  documentId: string;
  filename: string;
}

function duplicateDetailOf(text: string): DuplicateDetail | null {
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    const detail = body?.detail;
    if (!detail || typeof detail !== "object") return null;
    const value = detail as Record<string, unknown>;
    if (typeof value.document_id !== "string" || !value.document_id) return null;
    return {
      message:
        typeof value.message === "string"
          ? value.message
          : "A document with identical content already exists.",
      documentId: value.document_id,
      filename: typeof value.filename === "string" ? value.filename : "",
    };
  } catch {
    return null;
  }
}

/** Raised when the backend already has a document with the same bytes. */
export class DuplicateDocumentError extends Error {
  readonly documentId: string;
  readonly existingFilename: string;

  constructor(message: string, documentId: string, existingFilename: string) {
    super(message);
    this.name = "DuplicateDocumentError";
    this.documentId = documentId;
    this.existingFilename = existingFilename;
  }
}

export async function listDocuments(): Promise<DocumentInfo[]> {
  const response = await fetch(`${BASE}/documents?page_size=50`, {
    headers: headers(),
    credentials: CREDENTIALS,
    cache: "no-store",
  });
  if (!response.ok) throw await readError(response);
  const data = (await response.json()) as DocumentListResponse;
  return data.items;
}

export async function getDocument(id: string): Promise<DocumentInfo> {
  const response = await fetch(`${BASE}/documents/${id}`, {
    headers: headers(),
    credentials: CREDENTIALS,
    cache: "no-store",
  });
  if (!response.ok) throw await readError(response);
  return (await response.json()) as DocumentInfo;
}

/**
 * Upload with real progress.
 *
 * `fetch` cannot report upload progress, so this uses XMLHttpRequest: on a slow
 * link a 7MB file spends a minute in the request body and the UI must show it
 * moving instead of an opaque spinner.
 */
export interface UploadOptions {
  /** Replace an existing document with the same content hash. */
  replace?: boolean;
}

export function uploadDocument(
  file: File,
  onProgress?: (percent: number) => void,
  options: UploadOptions = {},
): Promise<string> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);

    const xhr = new XMLHttpRequest();
    const query = options.replace ? "?replace=true" : "";
    xhr.open("POST", `${BASE}/documents/upload${query}`);
    // XHR does not share fetch's defaults: opt in to the session cookie and
    // add the CSRF token explicitly.
    xhr.withCredentials = true;
    // Never set Content-Type: the browser adds the multipart boundary.
    for (const [name, value] of Object.entries(headers({}, true))) {
      xhr.setRequestHeader(name, value);
    }

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress?.(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const body = JSON.parse(xhr.responseText) as { document_id?: string };
          resolve(body.document_id ?? "");
        } catch {
          resolve("");
        }
        return;
      }
      const duplicate = duplicateDetailOf(xhr.responseText);
      if (xhr.status === 409 && duplicate) {
        reject(
          new DuplicateDocumentError(
            duplicate.message,
            duplicate.documentId,
            duplicate.filename || file.name,
          ),
        );
        return;
      }
      reject(
        new ApiError(xhr.status, duplicate?.message ?? `HTTP ${xhr.status}`),
      );
    };
    xhr.onerror = () => reject(new ApiError(0, "Network error"));
    xhr.onabort = () => reject(new ApiError(0, "Upload cancelled"));
    xhr.send(form);
  });
}

export async function deleteDocument(id: string): Promise<void> {
  const response = await fetch(`${BASE}/documents/${id}`, {
    method: "DELETE",
    headers: headers({}, true),
    credentials: CREDENTIALS,
  });
  if (!response.ok && response.status !== 204) {
    throw await readError(response);
  }
}

export interface StreamHandlers {
  onToken?: (token: string) => void;
  onCitation?: (citation: Citation) => void;
  onDone?: (payload: DonePayload) => void;
  /** Receives the raw failure object; the caller localises it via friendlyError. */
  onError?: (cause: unknown) => void;
  /** The server key is admin-only; the caller should open the key panel. */
  onKeyRequired?: () => void;
}

function handleBlock(block: string, handlers: StreamHandlers): void {
  let event = "message";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!data) return;

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(data) as Record<string, unknown>;
  } catch {
    return;
  }

  if (event === "token") handlers.onToken?.(String(payload.token ?? ""));
  else if (event === "citation") handlers.onCitation?.(payload as unknown as Citation);
  else if (event === "done") handlers.onDone?.(payload as unknown as DonePayload);
  else if (event === "error") {
    // Wrapped so the raw SSE text is treated as internal detail, never as UI copy.
    handlers.onError?.(new Error(String(payload.error ?? "")));
  }
}

export async function chatStream(
  message: string,
  history: ChatMessage[],
  handlers: StreamHandlers,
  language: "en" | "ar" = "en",
): Promise<void> {
  const conversation = history
    .slice(-10)
    .map((item) => ({ role: item.role, content: item.content }));

  let response: Response;
  try {
    response = await fetch(`${BASE}/chat`, {
      method: "POST",
      headers: headers({ "Content-Type": "application/json", ...llmHeaders() }, true),
      credentials: CREDENTIALS,
      body: JSON.stringify({
        message,
        stream: true,
        language,
        conversation_history: conversation,
      }),
    });
  } catch (error) {
    handlers.onError?.(error ?? new ApiError(0, "Network error"));
    return;
  }

  if (!response.ok) {
    const failure = await readError(response);
    if (failure.status === 402) handlers.onKeyRequired?.();
    handlers.onError?.(failure);
    return;
  }
  if (!response.body) {
    handlers.onError?.(new Error("Streaming is not supported in this browser"));
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) handleBlock(block, handlers);
  }
  if (buffer.trim()) handleBlock(buffer, handlers);
}

/** Ask the backend to check a visitor-supplied provider key. */
export async function verifyLlmKey(credential: LlmKey): Promise<LlmVerifyResult> {
  const response = await fetch(`${BASE}/llm/verify`, {
    method: "POST",
    headers: headers(
      {
        "X-LLM-API-Key": credential.key,
        "X-LLM-Model": credential.model,
        "X-LLM-Base-URL": credential.baseUrl,
      },
      true,
    ),
    credentials: CREDENTIALS,
  });
  if (!response.ok) throw await readError(response);
  return (await response.json()) as LlmVerifyResult;
}

export interface HealthChecks {
  status?: string;
  /** llm_api only: may a visitor bring a provider key? */
  byok?: boolean;
  /** llm_api only: the deployment key answers for admins only. */
  server_key_admin_only?: boolean;
  /** llm_api only: keyless non-admin chat is refused when true. */
  require_chat_byok?: boolean;
  /** auth only: guest sessions available? */
  demo?: boolean;
  /** auth only: sign-up is open (always true on current backends) */
  registration?: boolean;
  /** auth only: does the deployment require a shared invite code? */
  invite_required?: boolean;
}

export interface HealthReport {
  status: string;
  version?: string;
  checks?: Record<string, HealthChecks>;
  storage?: { engine?: string };
}

/** Public health probe; also tells the UI whether BYOK and guests are enabled. */
export async function getHealth(): Promise<HealthReport | null> {
  try {
    const response = await fetch(`${BASE}/health`, {
      headers: headers(),
      cache: "no-store",
    });
    if (!response.ok) return null;
    return (await response.json()) as HealthReport;
  } catch {
    return null;
  }
}
