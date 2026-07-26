import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "../auth/AuthContext";
import { Spinner } from "./primitives";
import { IconShield } from "./icons";

function Splash() {
  return (
    <div className="grid min-h-screen place-items-center text-muted">
      <div className="flex items-center gap-3">
        <Spinner /> <span className="stamp text-xs">verifying clearance…</span>
      </div>
    </div>
  );
}

/**
 * Route guards redirect imperatively via useEffect rather than rendering
 * <Navigate>. AnimatePresence(mode="wait") keeps an exiting route mounted through
 * its exit animation; a <Navigate> in that subtree re-navigates on every render
 * and spins into "Maximum update depth exceeded". useEffect fires once per state
 * change, so it's safe inside the animated tree.
 */

/** Authenticated session required. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const navigate = useNavigate();
  const loc = useLocation();

  useEffect(() => {
    if (status === "anon")
      navigate("/login", { replace: true, state: { from: loc.pathname } });
  }, [status, navigate, loc.pathname]);

  if (status === "loading") return <Splash />;
  if (status === "anon") return null;
  return <>{children}</>;
}

/** Level must grant panel access, and (optionally) a specific permission must be
 *  held. A `user`-level caller never sees the nav, but a deep link is handled
 *  explicitly rather than crashing.
 *
 *  Named for /admin/*, where it started, but the check it performs is exactly
 *  `require_permission` in api/auth.py — which folds the panel-level test into
 *  every permission it guards, including non-admin ones like `documents.upload`.
 *  So this is the right guard for any permission-gated feature, wherever it
 *  lives in the route tree. Gating an upload route on the permission alone would
 *  put the UI ahead of the backend and earn a 403. */
export function RequirePanel({
  perm,
  children,
}: {
  perm?: string;
  children: ReactNode;
}) {
  const { hasAdminPanel, can } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!hasAdminPanel) navigate("/ask", { replace: true });
  }, [hasAdminPanel, navigate]);

  if (!hasAdminPanel) return null;
  if (perm && !can(perm)) return <Forbidden perm={perm} />;
  return <>{children}</>;
}

export function Forbidden({ perm }: { perm?: string }) {
  return (
    <div className="mx-auto max-w-md py-16 text-center">
      <div className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-full bg-danger-bg text-danger">
        <IconShield />
      </div>
      <h2 className="text-lg font-semibold">Not cleared for this section</h2>
      <p className="mt-2 text-sm text-muted">
        Your account reaches this area, but not the{" "}
        {perm ? <code className="stamp text-accent">{perm}</code> : "required"}{" "}
        permission. Ask a creator or a role manager to grant it.
      </p>
    </div>
  );
}
