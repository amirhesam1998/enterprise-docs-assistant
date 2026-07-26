import { motion } from "framer-motion";
import type { Source } from "../api/types";
import { formatLocation, formatScore } from "../lib/format";
import { IconDoc } from "./icons";

function ScoreMeter({ score }: { score: number }) {
  const { pct, label, band } = formatScore(score);
  const color =
    band === "strong" ? "var(--ok)" : band === "good" ? "var(--accent)" : "var(--faint)";
  return (
    <div className="w-32 shrink-0">
      <div className="mb-1 flex items-baseline justify-between">
        <span className="stamp text-[10px]" style={{ color }}>
          {label}
        </span>
        <span className="font-mono text-xs tabular-nums text-muted">{pct}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-panel-2">
        <motion.div
          className="h-full rounded-full"
          style={{ background: color }}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ type: "spring", stiffness: 160, damping: 24, delay: 0.1 }}
        />
      </div>
    </div>
  );
}

export function SourceCard({
  source,
  unique = false,
}: {
  source: Source;
  /** In comparison view, true when this source appears for only one identity. */
  unique?: boolean;
}) {
  return (
    <div
      className={`flex items-center gap-3 rounded-lg border bg-panel px-3 py-2.5 transition-colors ${
        unique ? "border-accent/50 bg-accent/5" : "border-line"
      }`}
    >
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-panel-2 text-muted">
        <IconDoc width={17} height={17} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          {source.ref ? (
            <span className="stamp rounded bg-ink/5 px-1.5 py-0.5 font-mono text-[11px] text-accent dark:bg-white/5">
              {source.ref}
            </span>
          ) : (
            <span className="stamp text-[11px] text-faint">no ref</span>
          )}
          {unique && (
            <span className="stamp text-[10px] text-accent">only this identity</span>
          )}
        </div>
        <div className="mt-0.5 truncate text-sm font-medium">{source.source}</div>
        <div className="text-xs text-muted">{formatLocation(source.location)}</div>
      </div>
      <ScoreMeter score={source.score} />
    </div>
  );
}
