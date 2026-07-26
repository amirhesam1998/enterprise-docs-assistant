import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

/**
 * The /ask request takes 5–20s (a local LLM generates the answer). Rather than a
 * bare spinner, narrate the pipeline so the wait reads as work happening — and
 * so the *reason* answers differ (tenant + ACL filtering) is front of mind.
 */
const STAGES = [
  "Verifying your clearance",
  "Filtering documents by tenant + ACL groups",
  "Embedding your question",
  "Searching the vector index",
  "Reading the top matches",
  "Composing an answer with the local model",
];

export function LoadingNarrator() {
  const [i, setI] = useState(0);

  useEffect(() => {
    // Advance but hold on the last stage (generation) until the answer lands.
    const id = setInterval(() => {
      setI((v) => Math.min(v + 1, STAGES.length - 1));
    }, 2400);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="rounded-xl border border-line bg-panel p-6">
      <div className="flex items-center gap-2">
        <span className="stamp text-[11px] text-accent">Working</span>
        <span className="font-mono text-xs text-faint">
          {String(i + 1).padStart(2, "0")}/{String(STAGES.length).padStart(2, "0")}
        </span>
      </div>

      <div className="mt-3 h-7 overflow-hidden">
        <AnimatePresence mode="wait">
          <motion.div
            key={i}
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -14 }}
            transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            className="text-base font-medium"
          >
            {STAGES[i]}
            <motion.span
              animate={{ opacity: [0.2, 1, 0.2] }}
              transition={{ repeat: Infinity, duration: 1.4 }}
            >
              …
            </motion.span>
          </motion.div>
        </AnimatePresence>
      </div>

      <div className="mt-4 flex gap-1.5">
        {STAGES.map((_, s) => (
          <div key={s} className="h-1 flex-1 overflow-hidden rounded-full bg-panel-2">
            <motion.div
              className="h-full rounded-full bg-accent"
              initial={false}
              animate={{ width: s < i ? "100%" : s === i ? "60%" : "0%" }}
              transition={{ duration: 0.5 }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
