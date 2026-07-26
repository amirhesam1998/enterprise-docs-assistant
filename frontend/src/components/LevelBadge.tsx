import type { Level } from "../api/types";
import { IconShield } from "./icons";

const META: Record<
  Level,
  { label: string; cls: string; ring: string; blurb: string }
> = {
  creator: {
    label: "Creator",
    cls: "bg-creator-bg text-creator border-creator/35",
    ring: "shadow-[inset_0_0_0_1px_var(--creator)]",
    blurb: "Full clearance",
  },
  admin: {
    label: "Admin",
    cls: "bg-admin-bg text-admin border-admin/35",
    ring: "shadow-[inset_0_0_0_1px_var(--admin)]",
    blurb: "Panel access",
  },
  user: {
    label: "User",
    cls: "bg-user-bg text-user border-user/35",
    ring: "shadow-[inset_0_0_0_1px_var(--user)]",
    blurb: "No panel",
  },
};

export function LevelBadge({
  level,
  size = "md",
}: {
  level: Level;
  size?: "sm" | "md";
}) {
  const m = META[level];
  const pad = size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-1 text-xs";
  return (
    <span
      className={`stamp inline-flex items-center gap-1.5 rounded-md border font-semibold ${pad} ${m.cls}`}
      title={m.blurb}
    >
      <IconShield width={size === "sm" ? 12 : 14} height={size === "sm" ? 12 : 14} />
      {m.label}
    </span>
  );
}
