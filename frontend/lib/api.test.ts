import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./api-error";
import { chatStream, LLM_KEY_REQUIRED_DETAIL, UNAUTHORISED_DETAIL } from "./api";
import { COPY } from "./copy";
import { friendlyError } from "./errors";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function sseResponse(blocks: string[]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(blocks.join("\n\n")));
      controller.close();
    },
  });
  return new Response(body, { status: 200 });
}

describe("chat API contract", () => {
  it("keeps the key-required detail identical to the backend", () => {
    expect(LLM_KEY_REQUIRED_DETAIL).toBe(
      "The server API key is reserved for administrators. Add your own provider key to continue.",
    );
    expect(UNAUTHORISED_DETAIL).toBe("Invalid or missing credentials");
  });

  it("opens the key panel on 402 and keeps the detail internal", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: LLM_KEY_REQUIRED_DETAIL }), {
        status: 402,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const onKeyRequired = vi.fn();
    const onError = vi.fn();

    await chatStream("hello", [], { onKeyRequired, onError });

    expect(onKeyRequired).toHaveBeenCalledOnce();
    expect(onError).toHaveBeenCalledOnce();
    const failure = onError.mock.calls[0][0];
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure.status).toBe(402);
    // The raw text is available for control flow, but never as UI copy.
    expect(friendlyError(failure, "en", "chat")).toBe(COPY.en.llmKeyNeeded);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("does not open the key panel for other errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Rate limited" }), {
          status: 429,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    const onKeyRequired = vi.fn();
    const onError = vi.fn();

    await chatStream("hello", [], { onKeyRequired, onError });

    expect(onKeyRequired).not.toHaveBeenCalled();
    const failure = onError.mock.calls[0][0];
    expect(friendlyError(failure, "en", "chat")).toBe(COPY.en.rateLimited);
    expect(friendlyError(failure, "ar", "chat")).toBe(COPY.ar.rateLimited);
  });

  it("routes streamed tokens and citations to their handlers", async () => {
    const blocks = [
      'event: token\ndata: {"token":"مرحبا"}',
      'event: citation\ndata: {"chunk_id":"c1"}',
      'event: done\ndata: {"confidence":0.7,"latency_ms":42}',
    ];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse(blocks)));
    const onToken = vi.fn();
    const onCitation = vi.fn();
    const onDone = vi.fn();

    await chatStream("hello", [], { onToken, onCitation, onDone });

    expect(onToken).toHaveBeenCalledWith("مرحبا");
    expect(onCitation).toHaveBeenCalledWith({ chunk_id: "c1" });
    expect(onDone).toHaveBeenCalledWith({ confidence: 0.7, latency_ms: 42 });
  });

  it("never renders an SSE error string from the server", async () => {
    const blocks = [
      'event: error\ndata: {"error":"psycopg connection to postgres://user:secret@host failed"}',
    ];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse(blocks)));
    const onError = vi.fn();

    await chatStream("hello", [], { onError });

    const message = friendlyError(onError.mock.calls[0][0], "en", "chat");
    expect(message).toBe(COPY.en.genericError);
    expect(message).not.toContain("psycopg");
    expect(message).not.toContain("secret");
  });
});

describe("friendlyError", () => {
  const leaks = [
    "postgres://user:secret@host/db",
    "Traceback (most recent call last)",
    "FileNotFoundError: /srv/secrets/key.pem",
    `HTTP 500 Internal Server Error: ${"x".repeat(200)}`,
  ];

  it.each(leaks)("never returns the raw detail %s", (detail) => {
    for (const language of ["en", "ar"] as const) {
      for (const status of [0, 400, 401, 404, 409, 413, 429, 500, 503]) {
        const message = friendlyError(
          new ApiError(status, detail),
          language,
          "generic",
        );
        expect(message).not.toContain(detail);
        expect(message.length).toBeGreaterThan(0);
      }
    }
  });

  it("maps known control tokens to local copy", () => {
    expect(friendlyError(new ApiError(400, UNAUTHORISED_DETAIL), "ar", "documents")).toBe(
      COPY.ar.authRequired,
    );
    expect(
      friendlyError(new ApiError(402, LLM_KEY_REQUIRED_DETAIL), "ar", "chat"),
    ).toBe(COPY.ar.llmKeyNeeded);
  });

  it("uses context-appropriate copy for authentication failures", () => {
    expect(friendlyError(new ApiError(401, "whatever"), "en", "auth")).toBe(
      COPY.en.authInvalidCredentials,
    );
    expect(friendlyError(new ApiError(401, "whatever"), "en", "documents")).toBe(
      COPY.en.authRequired,
    );
    expect(friendlyError(new ApiError(400, "whatever"), "ar", "verify")).toBe(
      COPY.ar.verificationFailed,
    );
  });
});
