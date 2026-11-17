/**
 * Typed error carrying the HTTP status alongside the raw backend detail.
 *
 * The detail stays internal: it is used only to recognise the few control-flow
 * strings the client understands. It is never rendered directly — every UI
 * surface goes through `friendlyError` instead.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}
