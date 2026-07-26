import { NavLink, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { useAuth } from "../auth/AuthContext";
import { Chip } from "./primitives";
import { LevelBadge } from "./LevelBadge";
import { ThemeToggle } from "./ThemeToggle";
import {
  IconKey,
  IconLogout,
  IconSearch,
  IconShield,
  IconUpload,
  IconUsers,
} from "./icons";
import type { ReactNode } from "react";

function NavItem({ to, icon, label }: { to: string; icon: ReactNode; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `relative flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
          isActive ? "text-ink" : "text-muted hover:text-ink"
        }`
      }
    >
      {({ isActive }) => (
        <>
          {icon}
          <span>{label}</span>
          {isActive && (
            <motion.span
              layoutId="nav-underline"
              className="absolute inset-x-1 -bottom-[7px] h-0.5 rounded-full bg-accent"
              transition={{ type: "spring", stiffness: 500, damping: 34 }}
            />
          )}
        </>
      )}
    </NavLink>
  );
}

/** The persistent identity indicator — username, level, tenant, groups, roles.
 *  Present on every authenticated screen because it is the context that makes
 *  every answer and every admin action on screen interpretable. */
function IdentityRibbon() {
  const { me } = useAuth();
  if (!me) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line bg-panel/60 px-4 py-2.5 text-sm md:px-6">
      <div className="flex items-center gap-2">
        <span className="grid h-7 w-7 place-items-center rounded-full bg-accent/15 text-accent">
          <IconShield width={15} height={15} />
        </span>
        <span className="font-semibold">{me.username}</span>
      </div>
      <LevelBadge level={me.level} size="sm" />
      <div className="flex items-center gap-1.5">
        <span className="stamp text-[10px] text-faint">tenant</span>
        <Chip tone="accent">{me.tenant_id}</Chip>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="stamp text-[10px] text-faint">acl</span>
        {me.acl_groups.length ? (
          me.acl_groups.map((g) => <Chip key={g}>{g}</Chip>)
        ) : (
          <span className="text-xs text-faint">none</span>
        )}
      </div>
      <div className="flex items-center gap-1.5">
        <span className="stamp text-[10px] text-faint">roles</span>
        {me.roles.length ? (
          me.roles.map((r) => (
            <Chip key={r.id} tone="ok">
              {r.name}
            </Chip>
          ))
        ) : (
          <span className="text-xs text-faint">none</span>
        )}
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { me, can, hasAdminPanel, logout } = useAuth();
  const navigate = useNavigate();

  const adminLinks = [
    { to: "/admin/users", label: "Users", perm: "users.read", icon: <IconUsers width={16} height={16} /> },
    { to: "/admin/roles", label: "Roles", perm: "roles.read", icon: <IconShield width={16} height={16} /> },
    { to: "/admin/permissions", label: "Permissions", perm: "permissions.read", icon: <IconKey width={16} height={16} /> },
  ].filter((l) => can(l.perm));

  // Permission-gated, but not part of the admin panel — Upload sits beside Ask.
  // The `hasAdminPanel` term is not decoration: the backend's
  // require_permission("documents.upload") refuses a `user`-level caller before
  // it ever looks at the permission, so a nav item shown on the permission alone
  // would be a door that 403s. Omitted entirely, never disabled.
  const featureLinks = [
    { to: "/upload", label: "Upload", perm: "documents.upload", icon: <IconUpload width={16} height={16} /> },
  ].filter((l) => hasAdminPanel && can(l.perm));

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-30 border-b border-line bg-paper/85 backdrop-blur">
        <div className="flex items-center justify-between gap-4 px-4 py-3 md:px-6">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2.5">
              <span className="grid h-8 w-8 place-items-center rounded-md bg-ink text-paper">
                <IconShield width={17} height={17} />
              </span>
              <div className="leading-tight">
                <div className="text-sm font-semibold tracking-tight">Clearance</div>
                <div className="stamp text-[9px] text-faint">Enterprise Docs</div>
              </div>
            </div>
            <nav className="hidden items-center gap-1 md:flex">
              <NavItem to="/ask" icon={<IconSearch width={16} height={16} />} label="Ask" />
              {featureLinks.map((l) => (
                <NavItem key={l.to} to={l.to} icon={l.icon} label={l.label} />
              ))}
              {hasAdminPanel &&
                adminLinks.map((l) => (
                  <NavItem key={l.to} to={l.to} icon={l.icon} label={l.label} />
                ))}
            </nav>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            {me && (
              <button
                onClick={() => {
                  logout();
                  navigate("/login");
                }}
                className="flex h-9 items-center gap-2 rounded-md border border-line px-3 text-sm
                  text-muted transition-colors hover:bg-panel-2 hover:text-ink"
              >
                <IconLogout width={16} height={16} />
                <span className="hidden sm:inline">Sign out</span>
              </button>
            )}
          </div>
        </div>
        {/* mobile nav */}
        <nav className="flex items-center gap-1 overflow-x-auto px-3 pb-2 md:hidden">
          <NavItem to="/ask" icon={<IconSearch width={16} height={16} />} label="Ask" />
          {featureLinks.map((l) => (
            <NavItem key={l.to} to={l.to} icon={l.icon} label={l.label} />
          ))}
          {hasAdminPanel &&
            adminLinks.map((l) => (
              <NavItem key={l.to} to={l.to} icon={l.icon} label={l.label} />
            ))}
        </nav>
        <IdentityRibbon />
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 md:px-6 md:py-8">
        {children}
      </main>
    </div>
  );
}
