/**
 * Thin fetch wrapper around the backend.
 *
 * - Token is read from localStorage per call so it always reflects the session.
 * - A 401 anywhere means the session is dead: we clear it and broadcast an event
 *   the AuthProvider listens for, which returns the app to /login.
 * - A 403 is surfaced as a typed ApiError so callers can show it gracefully —
 *   the frontend is a convenience layer, the backend is the real boundary, and a
 *   403 arriving anyway means the two got out of sync, which is worth saying.
 */
import type {
  AdminUser,
  AskResponse,
  JobStatus,
  Me,
  Permission,
  Role,
  UploadAccepted,
} from "./types";

const BASE = "/api"; // proxied to http://127.0.0.1:8000 by Vite

const TOKEN_KEY = "eda.token";

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
  get isForbidden() {
    return this.status === 403;
  }
}

export const UNAUTHORIZED_EVENT = "eda:unauthorized";

async function request<T>(
  path: string,
  opts: RequestInit & { token?: string | null } = {},
): Promise<T> {
  const token = opts.token !== undefined ? opts.token : tokenStore.get();
  const headers = new Headers(opts.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(BASE + path, { ...opts, headers });

  if (res.status === 401) {
    // Only tear down the real session, not a throwaway comparison token.
    if (opts.token === undefined) {
      tokenStore.clear();
      window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
    }
    throw new ApiError(401, "Session expired");
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail)) detail = body.detail[0]?.msg ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function jsonBody(data: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  };
}

export const api = {
  // --- auth ---
  login: async (username: string, password: string): Promise<string> => {
    const form = new URLSearchParams({ username, password });
    const res = await fetch(BASE + "/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form,
    });
    if (!res.ok) {
      const detail =
        (await res.json().catch(() => null))?.detail ?? "Invalid credentials";
      throw new ApiError(res.status, detail);
    }
    return (await res.json()).access_token as string;
  },

  signup: (body: { username: string; password: string; email?: string }) =>
    request<AdminUser>("/auth/signup", jsonBody(body)),

  me: (token?: string) => request<Me>("/auth/me", { token }),

  ask: (question: string, k: number, token?: string) =>
    request<AskResponse>("/ask", { ...jsonBody({ question, k }), token }),

  // --- documents ---
  // No Content-Type is set: the browser must write it itself so the multipart
  // boundary is included. request() only ever adds Authorization, so passing a
  // FormData body straight through is safe.
  //
  // Identity is deliberately absent from this call. tenant_id and acl_groups are
  // read off the token server-side; a UI that sent them would be the
  // privilege-escalation hole the backend is careful not to open.
  uploadDocument: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<UploadAccepted>("/documents/upload", {
      method: "POST",
      body: form,
    });
  },
  jobStatus: (jobId: string) =>
    request<JobStatus>(`/documents/jobs/${encodeURIComponent(jobId)}`),

  // --- admin: users ---
  listUsers: () => request<AdminUser[]>("/admin/users"),
  createUser: (body: Record<string, unknown>) =>
    request<AdminUser>("/admin/users", jsonBody(body)),
  updateUser: (id: number, body: Record<string, unknown>) =>
    request<AdminUser>(`/admin/users/${id}`, { ...jsonBody(body), method: "PATCH" }),
  deleteUser: (id: number) =>
    request<void>(`/admin/users/${id}`, { method: "DELETE" }),
  assignRole: (userId: number, roleId: number) =>
    request<AdminUser>(`/admin/users/${userId}/roles`, jsonBody({ role_id: roleId })),
  unassignRole: (userId: number, roleId: number) =>
    request<AdminUser>(`/admin/users/${userId}/roles/${roleId}`, { method: "DELETE" }),

  // --- admin: roles ---
  listRoles: () => request<Role[]>("/admin/roles"),
  createRole: (body: {
    name: string;
    description?: string;
    permission_ids?: number[];
  }) => request<Role>("/admin/roles", jsonBody(body)),
  updateRole: (id: number, body: { name?: string; description?: string }) =>
    request<Role>(`/admin/roles/${id}`, { ...jsonBody(body), method: "PATCH" }),
  deleteRole: (id: number) =>
    request<void>(`/admin/roles/${id}`, { method: "DELETE" }),
  attachPermission: (roleId: number, permissionId: number) =>
    request<Role>(`/admin/roles/${roleId}/permissions`, jsonBody({ permission_id: permissionId })),
  detachPermission: (roleId: number, permId: number) =>
    request<Role>(`/admin/roles/${roleId}/permissions/${permId}`, { method: "DELETE" }),

  // --- admin: permissions ---
  listPermissions: () => request<Permission[]>("/admin/permissions"),
  createPermission: (body: { name: string; description?: string }) =>
    request<Permission>("/admin/permissions", jsonBody(body)),
  deletePermission: (id: number) =>
    request<void>(`/admin/permissions/${id}`, { method: "DELETE" }),
};
