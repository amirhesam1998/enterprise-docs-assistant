import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ApiError } from "../api/client";
import { IconClose } from "./icons";

type Tone = "info" | "error" | "success";
interface Toast {
  id: number;
  tone: Tone;
  title: string;
  body?: string;
}

interface ToastApi {
  push: (t: Omit<Toast, "id">) => void;
  /** Turn any thrown error into a readable toast. 403 gets a specific framing. */
  fromError: (e: unknown, fallback?: string) => void;
}

const Ctx = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { ...t, id }]);
    setTimeout(() => setToasts((p) => p.filter((x) => x.id !== id)), 5200);
  }, []);

  const fromError = useCallback(
    (e: unknown, fallback = "Something went wrong") => {
      if (e instanceof ApiError && e.isForbidden) {
        push({
          tone: "error",
          title: "Access denied by the server (403)",
          body:
            e.detail +
            " — the UI and backend disagreed. The backend is the real boundary.",
        });
        return;
      }
      const msg = e instanceof Error ? e.message : fallback;
      push({ tone: "error", title: msg });
    },
    [push],
  );

  return (
    <Ctx.Provider value={{ push, fromError }}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(92vw,360px)] flex-col gap-2">
        <AnimatePresence>
          {toasts.map((t) => (
            <motion.div
              key={t.id}
              layout
              initial={{ opacity: 0, x: 40, scale: 0.96 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 40, scale: 0.96 }}
              transition={{ type: "spring", stiffness: 400, damping: 32 }}
              className={`pointer-events-auto rounded-lg border p-3 shadow-lg backdrop-blur-sm ${
                t.tone === "error"
                  ? "border-danger/40 bg-danger-bg text-ink"
                  : t.tone === "success"
                    ? "border-ok/40 bg-ok/12 text-ink"
                    : "border-line bg-panel text-ink"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="text-sm font-semibold">{t.title}</div>
                <button
                  onClick={() => setToasts((p) => p.filter((x) => x.id !== t.id))}
                  className="text-faint hover:text-ink"
                >
                  <IconClose width={14} height={14} />
                </button>
              </div>
              {t.body && (
                <div className="mt-1 text-xs leading-relaxed text-muted">{t.body}</div>
              )}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </Ctx.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
