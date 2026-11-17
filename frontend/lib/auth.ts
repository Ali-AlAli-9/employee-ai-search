import { ApiError } from "./api-error";

/**
 * Account and session helpers.
 *
 * The session cookie is HttpOnly, so this module never sees it. The CSRF token
 * is deliberately readable (`eais_csrf`) and is mirrored in memory and sent as
 * `X-CSRF-Token`. The Next.js proxy forwards that header verbatim; it never
 * reconstructs it from the cookie, which would defeat the double submit.
 */

/** Workspace summary returned by the auth endpoints. */
export interface WorkspaceInfo {
  id: string;
  name: string;
  invite_code: string;
  invite_url?: string;
}

export interface AuthUser {
  id: string;
  email: string | null;
  role: "viewer" | "user" | "admin" | string;
  display_name?: string | null;
  /** Legacy column kept for API compatibility; no guest accounts are created. */
  is_guest: boolean;
  workspace_id?: string | null;
  workspace?: WorkspaceInfo | null;
  created_at?: string | null;
  last_login_at?: string | null;
  kind?: "session" | "api_key";
}

export interface AuthConfig {
  demo: boolean;
  registration: boolean;
  invite_required: boolean;
}

/** Admin user row (mirrors the backend projection). */
export interface AdminUser {
  id: string;
  email: string | null;
  role: "viewer" | "user" | "admin";
  display_name: string | null;
  is_guest: boolean;
  is_active: boolean;
  created_at: string | null;
  last_login_at: string | null;
  last_sign_in_at: string | null;
}

export interface UserPage {
  items: AdminUser[];
  total: number;
  page: number;
  page_size: number;
  provider: string;
}

export interface AdminUpdate {
  role?: "viewer" | "user" | "admin";
  is_active?: boolean;
}

export interface SyncResponse {
  synced: number;
  provider: string;
}

const DIRECT_API = process.env.NEXT_PUBLIC_API_URL;
const BASE = DIRECT_API ? `${DIRECT_API.replace(/\/$/, "")}/api/v1` : "/api/v1";

/** Cross-origin cookie auth is only possible when the backend is explicit. */
export const CREDENTIALS: RequestCredentials = DIRECT_API ? "include" : "same-origin";

let csrfToken: string | null = null;

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function clearCsrfToken(): void {
  csrfToken = null;
}

/** Header for unsafe requests; falls back to the readable cookie after reload. */
export function csrfHeader(): Record<string, string> {
  const token = csrfToken ?? readCookie("eais_csrf");
  return token ? { "X-CSRF-Token": token } : {};
}

/** Keep the backend detail internal; the UI localises it through friendlyError. */
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

/** Generic helper for authenticated requests (GET, POST, PATCH, DELETE). */
async function authRequest<T>(
  path: string,
  body?: unknown,
  method: "GET" | "POST" | "PATCH" | "DELETE" = "GET",
): Promise<T> {
  // The browser refuses GET/HEAD requests that carry a body. Fail loudly here
  // instead of letting a forgotten `"POST"` become a cryptic TypeError in the
  // UI ("Request with GET/HEAD method cannot have body").
  if (body !== undefined && method === "GET") {
    throw new Error(`authRequest: ${method} ${path} cannot have a body`);
  }
  const response = await fetch(`${BASE}${path}`, {
    method,
    credentials: CREDENTIALS,
    headers: {
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...csrfHeader(),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  if (!response.ok) throw await readError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

interface AuthResponse {
  user: AuthUser;
  csrf_token?: string;
  workspace?: WorkspaceInfo | null;
}

export type RegistrationKind = "employer" | "member";

export interface RegisterFields {
  workspace_name?: string;
  invite_code?: string;
  display_name?: string;
}

export interface RegisterInput extends RegisterFields {
  email: string;
  password: string;
  kind: RegistrationKind;
}

export interface RegisterResult {
  user: AuthUser;
  csrf_token?: string;
  workspace: WorkspaceInfo | null;
}

function remember(response: AuthResponse): AuthUser {
  if (response.csrf_token) setCsrfToken(response.csrf_token);
  return response.user;
}

/** The current user, or `null` for an anonymous visitor (401 is not an error). */
export async function getMe(): Promise<AuthUser | null> {
  try {
    const response = await fetch(`${BASE}/auth/me`, {
      credentials: CREDENTIALS,
      cache: "no-store",
    });
    if (response.status === 401) return null;
    if (!response.ok) return null;
    const body = (await response.json()) as { user: AuthUser };
    return body.user;
  } catch {
    return null;
  }
}

export async function login(email: string, password: string): Promise<AuthUser> {
  const body = await authRequest<AuthResponse>("/auth/login", { email, password }, "POST");
  return remember(body);
}

/**
 * Register either as an employer (new workspace, returns its invite code) or as
 * a member (joins through an invite code). Both object and positional calls are
 * accepted; the positional legacy form (invite code in third place) keeps older
 * callers compiling while always mapping to `kind: "member"`.
 */
export async function register(input: RegisterInput): Promise<RegisterResult>;
export async function register(
  email: string,
  password: string,
  kind: RegistrationKind,
  fields?: RegisterFields,
): Promise<RegisterResult>;
export async function register(
  email: string,
  password: string,
  inviteCode?: string,
  displayName?: string,
): Promise<RegisterResult>;
export async function register(
  inputOrEmail: RegisterInput | string,
  password?: string,
  kindOrInvite?: RegistrationKind | string,
  fieldsOrDisplay?: RegisterFields | string,
  legacyDisplayName?: string,
): Promise<RegisterResult> {
  let input: RegisterInput;
  if (typeof inputOrEmail !== "string") {
    input = inputOrEmail;
  } else if (kindOrInvite === "employer" || kindOrInvite === "member") {
    input = {
      email: inputOrEmail,
      password: password ?? "",
      kind: kindOrInvite,
      ...(typeof fieldsOrDisplay === "string"
        ? { invite_code: fieldsOrDisplay }
        : fieldsOrDisplay),
    };
  } else {
    // Legacy positional call: register(email, password, inviteCode, displayName).
    input = {
      email: inputOrEmail,
      password: password ?? "",
      kind: "member",
      invite_code: kindOrInvite ?? "",
      display_name: typeof fieldsOrDisplay === "string" ? fieldsOrDisplay : legacyDisplayName,
    };
  }

  const body: Record<string, unknown> = {
    email: input.email,
    password: input.password,
    kind: input.kind,
  };
  if (input.workspace_name) body.workspace_name = input.workspace_name;
  if (input.invite_code) body.invite_code = input.invite_code;
  if (input.display_name) body.display_name = input.display_name;

  const response = await authRequest<AuthResponse>("/auth/register", body, "POST");
  const user = remember(response);
  return {
    user,
    csrf_token: response.csrf_token,
    workspace: response.workspace ?? user.workspace ?? null,
  };
}

export async function logout(): Promise<void> {
  try {
    await fetch(`${BASE}/auth/logout`, {
      method: "POST",
      credentials: CREDENTIALS,
      headers: csrfHeader(),
      cache: "no-store",
    });
  } finally {
    clearCsrfToken();
  }
}

/**
 * Admin: list users with search and pagination. The optional legacy flag is
 * accepted for older callers; new UI never filters by guest status.
 */
export async function listUsers(
  page: number,
  pageSize: number,
  q: string,
  includeGuests?: boolean,
): Promise<UserPage> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    ...(q ? { q } : {}),
    ...(includeGuests ? { include_guests: "true" } : {}),
  });
  return authRequest<UserPage>(`/auth/users?${params.toString()}`);
}

/** Admin: update role and/or active status. */
export async function updateUser(
  userId: string,
  payload: AdminUpdate,
): Promise<{ user: AdminUser }> {
  return authRequest<{ user: AdminUser }>(`/auth/users/${userId}`, payload, "PATCH");
}

/** Admin: request a password reset email (always 202 to avoid enumeration). */
export async function resetPassword(userId: string): Promise<{ detail: string }> {
  return authRequest<{ detail: string }>(`/auth/users/${userId}/password-reset`, {}, "POST");
}

/** Admin: delete a user account (legacy helper kept for compatibility). */
export async function deleteUser(userId: string): Promise<void> {
  return authRequest<void>(`/auth/users/${userId}`, undefined, "DELETE");
}

/** Admin: sync profiles from Supabase. */
export async function syncUsers(): Promise<SyncResponse> {
  return authRequest<SyncResponse>("/auth/users/sync", {}, "POST");
}

/**
 * Finish a password recovery. The token comes from the emailed link's URL
 * fragment; this call is unauthenticated (the token *is* the credential) and
 * works even when the visitor has no session.
 */
export async function completePasswordReset(
  accessToken: string,
  password: string,
): Promise<void> {
  const response = await fetch(`${BASE}/auth/password-reset`, {
    method: "POST",
    credentials: CREDENTIALS,
    headers: { "Content-Type": "application/json", ...csrfHeader() },
    body: JSON.stringify({ access_token: accessToken, password }),
    cache: "no-store",
  });
  if (!response.ok) throw await readError(response);
}
