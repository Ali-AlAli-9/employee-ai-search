import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const NULL_BODY_STATUSES = new Set([204, 205, 304]);

/**
 * Same-origin proxy to the FastAPI backend.
 *
 * The browser holds no backend address and no server key: authentication is the
 * first-party `eais_session` cookie, which this route forwards verbatim. The
 * readable `eais_csrf` cookie is turned into `X-CSRF-Token` for unsafe methods
 * (double submit), so components never have to special-case it.
 */
async function proxy(
  request: NextRequest,
  context: { params: { path: string[] } },
): Promise<Response> {
  const suffix = (context.params.path ?? []).join("/");
  const target = `${BACKEND_URL.replace(/\/$/, "")}/api/v1/${suffix}${request.nextUrl.search}`;
  const method = request.method.toUpperCase();

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);

  // Cookies are the credential now, so they travel both ways untouched.
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("cookie", cookie);

  // A caller may supply its own API key (scripts, CI). It is forwarded as-is;
  // the proxy never invents one.
  const apiKey = request.headers.get("x-api-key");
  if (apiKey) headers.set("x-api-key", apiKey);

  // The CSRF header must come from the caller. Deriving it from the cookie here
  // would defeat the double submit: any request that carries the cookie through
  // the proxy would be auto-authorised. The client sends the readable
  // `eais_csrf` value; a cross-site page can do neither (SameSite=Lax plus the
  // browser's preflight rules).
  const csrf = request.headers.get("x-csrf-token");
  if (csrf && UNSAFE_METHODS.has(method)) headers.set("x-csrf-token", csrf);

  // Render's edge sets X-Forwarded-For for the browser. Forward it (and the
  // request id) so per-IP rate limits and log correlation survive the proxy.
  const forwardedFor = request.headers.get("x-forwarded-for");
  if (forwardedFor) headers.set("x-forwarded-for", forwardedFor);
  const incomingRequestId = request.headers.get("x-request-id");
  if (incomingRequestId) headers.set("x-request-id", incomingRequestId);

  // Bring-your-own-key headers are forwarded for the only two routes that
  // consume them, and nowhere else. They are request-scoped: the backend holds
  // them in memory for one call and never stores or logs them.
  if (suffix === "chat" || suffix === "llm/verify") {
    for (const name of ["x-llm-api-key", "x-llm-model", "x-llm-base-url"]) {
      const value = request.headers.get(name);
      if (value) headers.set(name, value);
    }
  }

  // Stream the body upstream instead of buffering it: a 50MB upload used to be
  // copied twice in the Node process before the backend saw a single byte.
  const body = method === "GET" || method === "HEAD" ? undefined : request.body;
  const contentLength = request.headers.get("content-length");
  if (contentLength) headers.set("content-length", contentLength);

  let response: Response;
  try {
    response = await fetch(target, {
      method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
      // Node's fetch requires this flag when the request body is a stream.
      duplex: "half",
    } as RequestInit & { duplex: "half" });
  } catch (error) {
    // The upstream error can contain internal addresses or connection strings.
    // Keep it in the server log; the browser only gets a stable, generic detail.
    console.error("[api proxy] backend request failed:", error);
    return Response.json(
      { detail: "The service is temporarily unavailable." },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers();
  const responseType = response.headers.get("content-type");
  if (responseType) responseHeaders.set("content-type", responseType);
  responseHeaders.set("cache-control", "no-store");
  const responseRequestId = response.headers.get("x-request-id");
  if (responseRequestId) responseHeaders.set("x-request-id", responseRequestId);

  // `set-cookie` is the one header Headers cannot merge. Newer runtimes expose
  // every value through getSetCookie(); keep a single-value fallback.
  const setCookies =
    typeof response.headers.getSetCookie === "function"
      ? response.headers.getSetCookie()
      : [];
  if (setCookies.length) {
    for (const value of setCookies) responseHeaders.append("set-cookie", value);
  } else {
    const single = response.headers.get("set-cookie");
    if (single) responseHeaders.append("set-cookie", single);
  }

  // Server-sent events must reach the browser token by token.
  if (responseType?.includes("text/event-stream")) {
    return new Response(response.body, {
      status: response.status,
      headers: responseHeaders,
    });
  }

  // 204/205/304 must not carry a body, even an empty one.
  if (NULL_BODY_STATUSES.has(response.status) || method === "HEAD") {
    return new Response(null, {
      status: response.status,
      headers: responseHeaders,
    });
  }

  // Everything else is a small JSON payload. Sending it with a Content-Length
  // lets the browser finish as soon as the bytes arrive instead of waiting for
  // a chunked terminator that the platform edge can hold open for seconds.
  const payload = await response.arrayBuffer();
  responseHeaders.set("content-length", String(payload.byteLength));
  return new Response(payload, {
    status: response.status,
    headers: responseHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
