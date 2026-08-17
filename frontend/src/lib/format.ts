import type { Source, SourceLocation } from "../api/types";

/** Direction detection per answer: RTL if a meaningful share of strong letters
 *  are Arabic-script (Persian). Never hardcode one direction app-wide. */
export function detectDir(text: string): "rtl" | "ltr" {
  // Arabic + Arabic Supplement + Presentation Forms A/B (covers Persian).
  const rtl = (text.match(/[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]/g) || []).length;
  const ltr = (text.match(/[A-Za-z]/g) || []).length;
  if (rtl === 0) return "ltr";
  return rtl >= ltr ? "rtl" : "ltr";
}

/** Render a polymorphic source location as human text — never raw JSON. */
export function formatLocation(loc: SourceLocation): string {
  if (!loc || typeof loc !== "object") return "—";
  if (loc.type === "cell") {
    const l = loc as Extract<SourceLocation, { type: "cell" }>;
    return `${l.sheet}, row ${l.row}`;
  }
  if (loc.type === "page") {
    const l = loc as Extract<SourceLocation, { type: "page" }>;
    return `page ${l.num}`;
  }
  // Unknown shape: degrade gracefully without dumping JSON.
  const anyLoc = loc as Record<string, unknown>;
  return String(anyLoc.type ?? "location");
}

/** A raw float like 0.6062523854221507 is not legible. Turn it into a percent
 *  plus a qualitative band. */
export function formatScore(score: number): {
  pct: number;
  label: string;
  band: "strong" | "good" | "weak";
} {
  const pct = Math.round(Math.max(0, Math.min(1, score)) * 100);
  if (pct >= 60) return { pct, label: "Strong match", band: "strong" };
  if (pct >= 45) return { pct, label: "Good match", band: "good" };
  return { pct, label: "Weak match", band: "weak" };
}

/** Bytes → a short human size. Shown next to a queued filename, where a raw
 *  byte count says nothing about how long ingestion will take. */
export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
}

/** Seconds → m:ss. Ingestion runs from a few seconds to a couple of minutes, so
 *  elapsed time is the honest progress signal — there is no percentage to show. */
export function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** A stable identity key for a source, used to diff two result sets. */
export function sourceKey(s: Source): string {
  return `${s.source}::${s.ref ?? ""}::${JSON.stringify(s.location)}`;
}
