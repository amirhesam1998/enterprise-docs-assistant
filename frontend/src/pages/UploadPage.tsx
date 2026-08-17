import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { IngestResult, JobStatus } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../components/Toast";
import { Button, Chip, Panel, SectionTitle, Spinner } from "../components/primitives";
import {
  IconAlert,
  IconArrow,
  IconCheck,
  IconClose,
  IconDoc,
  IconRetry,
  IconUpload,
} from "../components/icons";
import { formatBytes, formatDuration } from "../lib/format";
import { fadeUp, listContainer, listItem } from "../lib/motion";

/** The backend enforces this too (400 on anything else). Checking here as well
 *  means an obvious mistake never costs a round trip or an upload of a file that
 *  was always going to be refused. */
const ACCEPT = [".pdf", ".xlsx", ".docx", ".png", ".jpg", ".jpeg"];
const POLL_MS = 2000;
const TERMINAL = new Set(["SUCCESS", "FAILURE", "REVOKED"]);

function extOf(filename: string): string {
  const i = filename.lastIndexOf(".");
  return i < 0 ? "" : filename.slice(i).toLowerCase();
}

/** How each Celery state reads to someone watching. "queued" is our own
 *  optimistic phase, held between the 202 and the first poll landing. */
const PHASE: Record<string, { label: string; note: string }> = {
  queued: {
    label: "Queued",
    note: "Accepted by the API. Waiting for a worker to pick it up.",
  },
  PENDING: {
    label: "Queued",
    note: "Waiting for a worker to pick it up.",
  },
  STARTED: {
    label: "Ingesting",
    note: "Parsing the file, embedding each chunk, writing to the vector index.",
  },
  RETRY: {
    label: "Retrying",
    note: "The worker hit a transient error and is trying again.",
  },
  SUCCESS: { label: "Indexed", note: "" },
  FAILURE: { label: "Failed", note: "" },
};

function phaseOf(status: string) {
  return PHASE[status] ?? { label: status, note: "Reported by the worker." };
}

/**
 * One job, one poller.
 *
 * A self-rescheduling setTimeout rather than setInterval: a fixed interval can
 * stack requests when one is slow, and stopping it means remembering to clear it
 * on every exit path. Here the chain simply does not reschedule once the job
 * reaches a terminal state, and the cleanup cancels whatever timer is pending —
 * so navigating away mid-poll leaves nothing running.
 */
function useJobPoll(jobId: string, onSettle: (s: JobStatus) => void) {
  const [state, setState] = useState<JobStatus>(() => ({
    job_id: jobId,
    status: "queued",
    result: null,
    error: null,
  }));

  // Held in a ref so a new callback identity on every parent render doesn't
  // restart the poll — the job id is the only thing that should do that.
  const settle = useRef(onSettle);
  settle.current = onSettle;

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;

    // A retry reuses this row with a fresh job id: reset rather than showing the
    // previous attempt's failure while the new one is queued.
    setState({ job_id: jobId, status: "queued", result: null, error: null });

    async function tick() {
      let next: JobStatus;
      try {
        next = await api.jobStatus(jobId);
      } catch (e) {
        if (!alive) return;
        // A 401 already tore the session down inside the client. Anything else
        // here (403, 404) is terminal for this row — polling on would only
        // repeat the same error every two seconds.
        next = {
          job_id: jobId,
          status: "FAILURE",
          result: null,
          error:
            e instanceof ApiError
              ? `${e.detail} (status check, HTTP ${e.status})`
              : "Could not reach the API to check status.",
        };
      }
      if (!alive) return;
      setState(next);
      if (TERMINAL.has(next.status)) {
        settle.current(next);
        return; // no reschedule — this is where polling stops
      }
      timer = window.setTimeout(tick, POLL_MS);
    }

    timer = window.setTimeout(tick, POLL_MS);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [jobId]);

  return state;
}

/** Ticks only while the job is live; freezes at the settle moment. */
function useElapsed(since: number, running: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    setNow(Date.now());
    if (!running) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [running, since]);
  return Math.max(0, Math.floor((now - since) / 1000));
}

interface QueueEntry {
  /** Stable across retries, so the row keeps its place in the list. */
  key: string;
  /** Kept so a failed ingestion can be retried without re-picking the file. */
  file: File;
  jobId: string;
  source: string;
  queuedAt: number;
}

function StatusChip({
  status,
  result,
}: {
  status: string;
  result?: IngestResult | null;
}) {
  // A canonical job can complete (Celery SUCCESS) yet index nothing because the
  // quality gate held or rejected it — say so rather than claiming "Indexed".
  const st = result?.ingestion_status;
  if (status === "SUCCESS" && (st === "needs_review" || st === "failed")) {
    return (
      <Chip tone={st === "failed" ? "danger" : "accent"}>
        {st === "failed" ? "Not indexed" : "Needs review"}
      </Chip>
    );
  }
  const tone =
    status === "SUCCESS" ? "ok" : status === "FAILURE" ? "danger" : "accent";
  return <Chip tone={tone}>{phaseOf(status).label}</Chip>;
}

/** Compact quality line shown on canonical results (absent on legacy shape). */
function QualityLine({ result }: { result: IngestResult }) {
  if (result.quality_score === undefined) return null;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
      <span className="stamp text-[10px] text-faint">quality</span>
      <span className="font-mono tabular-nums">
        {result.quality_score.toFixed(0)}/100
      </span>
      {result.quality_level && (
        <span className="text-faint">
          · {result.quality_level.replace(/_/g, " ")}
        </span>
      )}
      {result.extraction_route && (
        <span className="text-faint">· {result.extraction_route}</span>
      )}
      {typeof result.total_pages === "number" && (
        <span className="text-faint">
          · {result.accepted_pages ?? 0}/{result.total_pages} pages
        </span>
      )}
    </div>
  );
}

function WarningLine({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;
  return (
    <div className="mt-1.5 text-xs text-muted">
      <span className="stamp text-[10px] text-faint">warnings</span>{" "}
      {warnings.slice(0, 3).join(", ").replace(/_/g, " ")}
      {warnings.length > 3 ? ` +${warnings.length - 3} more` : ""}
    </div>
  );
}

/** The receipt. Legacy results (no ingestion_status) read as "indexed"; canonical
 *  results additionally surface quality, warnings, and the held/failed outcomes. */
function IngestReceipt({ result }: { result: IngestResult }) {
  const { me } = useAuth();
  const status = result.ingestion_status ?? "indexed";
  const warnings = result.warnings ?? [];

  if (status === "needs_review" || status === "failed") {
    const failed = status === "failed";
    return (
      <motion.div
        variants={fadeUp}
        initial="hidden"
        animate="show"
        className="mt-2 rounded-lg border border-line bg-panel-2/60 px-3 py-2.5"
      >
        <div className="stamp mb-1.5 flex items-center gap-1.5 text-[10px] text-muted">
          <IconAlert width={12} height={12} />
          {failed ? "Parsed — nothing indexed" : "Parsed — held for review"}
        </div>
        <div className="text-sm text-muted">
          {failed
            ? "No content passed the extraction quality gate, so nothing was written to the index."
            : "The extraction was flagged for review by the quality gate and was not indexed."}
        </div>
        <QualityLine result={result} />
        <WarningLine warnings={warnings} />
      </motion.div>
    );
  }

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      animate="show"
      className="mt-2 rounded-lg border border-ok/30 bg-ok/10 px-3 py-2.5"
    >
      <div className="stamp mb-1.5 text-[10px] text-ok">
        {status === "indexed_with_warnings" ? "Ingested with warnings" : "Ingested"}
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm">
        <span>
          <span className="font-mono font-semibold tabular-nums">
            {result.chunks}
          </span>{" "}
          <span className="text-muted">
            chunk{result.chunks === 1 ? "" : "s"} indexed
          </span>
        </span>
        <span className="flex items-center gap-1.5">
          <span className="stamp text-[10px] text-faint">tenant</span>
          <Chip tone="accent">{result.tenant_id}</Chip>
        </span>
        <span className="flex items-center gap-1.5">
          <span className="stamp text-[10px] text-faint">acl</span>
          {me?.acl_groups.length ? (
            me.acl_groups.map((g) => <Chip key={g}>{g}</Chip>)
          ) : (
            <span className="text-xs text-faint">none</span>
          )}
        </span>
      </div>
      <QualityLine result={result} />
      <WarningLine warnings={warnings} />
      <div className="mt-2 text-xs text-muted">
        Retrievable now — but only by identities inside that tenant and those
        groups.
      </div>
      <Link
        to="/ask"
        className="mt-2 inline-flex items-center gap-1.5 text-sm text-accent hover:underline"
      >
        Ask a question about it <IconArrow width={14} height={14} />
      </Link>
    </motion.div>
  );
}

/** Indeterminate bar. There is no percentage to report — the worker exposes a
 *  state, not progress — so this reads as "still working", with the elapsed
 *  clock carrying the real information. Under prefers-reduced-motion the
 *  MotionConfig in App.tsx stills it and the text stands on its own. */
function WorkingBar() {
  return (
    <div className="mt-2 h-1 overflow-hidden rounded-full bg-panel-2">
      <motion.div
        className="h-full w-1/3 rounded-full bg-accent"
        animate={{ x: ["-100%", "300%"] }}
        transition={{ repeat: Infinity, duration: 1.8, ease: "easeInOut" }}
      />
    </div>
  );
}

function JobRow({
  entry,
  onSettle,
  onRetry,
  onDismiss,
}: {
  entry: QueueEntry;
  onSettle: (s: JobStatus) => void;
  onRetry: (entry: QueueEntry) => Promise<void>;
  onDismiss: (key: string) => void;
}) {
  const job = useJobPoll(entry.jobId, onSettle);
  const done = TERMINAL.has(job.status);
  const elapsed = useElapsed(entry.queuedAt, !done);
  const [retrying, setRetrying] = useState(false);

  async function retry() {
    setRetrying(true);
    try {
      await onRetry(entry);
    } finally {
      setRetrying(false);
    }
  }

  return (
    <motion.div variants={listItem} layout className="px-4 py-3">
      <div className="flex items-start gap-3">
        <span
          className={`grid h-9 w-9 shrink-0 place-items-center rounded-md ${
            job.status === "SUCCESS"
              ? "bg-ok/12 text-ok"
              : job.status === "FAILURE"
                ? "bg-danger-bg text-danger"
                : "bg-panel-2 text-muted"
          }`}
        >
          {job.status === "SUCCESS" ? (
            <IconCheck width={17} height={17} />
          ) : job.status === "FAILURE" ? (
            <IconAlert width={17} height={17} />
          ) : (
            <IconDoc width={17} height={17} />
          )}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="truncate text-sm font-medium">{entry.source}</span>
            <StatusChip status={job.status} result={job.result} />
          </div>

          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted">
            <span>{formatBytes(entry.file.size)}</span>
            <span className="text-faint">·</span>
            <span className="font-mono tabular-nums">{formatDuration(elapsed)}</span>
            <span className="text-faint">·</span>
            <span className="stamp text-[10px] text-faint" title={entry.jobId}>
              job {entry.jobId.slice(0, 8)}
            </span>
          </div>

          {!done && (
            <>
              <div className="mt-1 text-xs text-muted">{phaseOf(job.status).note}</div>
              <WorkingBar />
            </>
          )}

          {/* The receipt. Same detail discipline as a source card: say exactly
              what landed and under whose clearance, not just "done". */}
          {job.status === "SUCCESS" && job.result && (
            <IngestReceipt result={job.result} />
          )}

          {job.status === "FAILURE" && (
            <motion.div
              variants={fadeUp}
              initial="hidden"
              animate="show"
              className="mt-2 rounded-lg border border-danger/35 bg-danger-bg px-3 py-2.5"
            >
              <div className="stamp mb-1 text-[10px] text-danger">
                Ingestion failed
              </div>
              <div className="break-words text-sm text-ink">
                {job.error ?? "The worker reported a failure without a message."}
              </div>
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={retry}
                disabled={retrying}
              >
                {retrying ? <Spinner /> : <IconRetry width={15} height={15} />}
                Try again
              </Button>
            </motion.div>
          )}
        </div>

        <button
          onClick={() => onDismiss(entry.key)}
          className="shrink-0 text-faint transition-colors hover:text-ink"
          aria-label={`Dismiss ${entry.source}`}
          title={done ? "Dismiss" : "Stop watching (the worker keeps going)"}
        >
          <IconClose width={15} height={15} />
        </button>
      </div>
    </motion.div>
  );
}

export default function UploadPage() {
  const { me } = useAuth();
  const toast = useToast();

  const [file, setFile] = useState<File | null>(null);
  const [rejection, setRejection] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [queue, setQueue] = useState<QueueEntry[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  /** Fail fast on extension, before a byte leaves the browser. */
  const accept = useCallback((picked: File | null | undefined) => {
    if (!picked) return;
    const ext = extOf(picked.name);
    if (!ACCEPT.includes(ext)) {
      setFile(null);
      setRejection(
        `“${picked.name}” isn’t supported${ext ? ` — ${ext} files aren’t read by the ingester` : ""}. Pick a .pdf, .xlsx, .docx or an image (.png, .jpg, .jpeg).`,
      );
      return;
    }
    setRejection(null);
    setFile(picked);
  }, []);

  async function submit() {
    if (!file) return;
    setSubmitting(true);
    try {
      const accepted = await api.uploadDocument(file);
      setQueue((prev) => [
        {
          key: crypto.randomUUID(),
          file,
          jobId: accepted.job_id,
          source: accepted.source,
          queuedAt: Date.now(),
        },
        ...prev,
      ]);
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
    } catch (e) {
      // A 403 here means the nav showed a door the backend won't open — the
      // toast says so in those words rather than the page falling over.
      toast.fromError(e, "The upload was not accepted");
    } finally {
      setSubmitting(false);
    }
  }

  /** Re-POST the same File under a fresh job id; the row keeps its key. */
  const retry = useCallback(
    async (entry: QueueEntry) => {
      try {
        const accepted = await api.uploadDocument(entry.file);
        setQueue((prev) =>
          prev.map((q) =>
            q.key === entry.key
              ? { ...q, jobId: accepted.job_id, queuedAt: Date.now() }
              : q,
          ),
        );
      } catch (e) {
        toast.fromError(e, "The retry was not accepted");
      }
    },
    [toast],
  );

  const onSettle = useCallback(
    (s: JobStatus) => {
      if (s.status === "SUCCESS" && s.result) {
        const st = s.result.ingestion_status ?? "indexed";
        if (st === "failed") {
          toast.push({
            tone: "error",
            title: `${s.result.source} not indexed`,
            body: "No content passed the extraction quality gate.",
          });
        } else if (st === "needs_review") {
          toast.push({
            tone: "info",
            title: `${s.result.source} held for review`,
            body: "Parsed, but flagged by the quality gate — not indexed.",
          });
        } else {
          toast.push({
            tone: "success",
            title: `${s.result.source} indexed`,
            body: `${s.result.chunks} chunks are now retrievable inside tenant ${s.result.tenant_id}.`,
          });
        }
      } else if (s.status === "FAILURE") {
        toast.push({
          tone: "error",
          title: "Ingestion failed",
          body: s.error ?? undefined,
        });
      }
    },
    [toast],
  );

  const dismiss = useCallback(
    (key: string) => setQueue((prev) => prev.filter((q) => q.key !== key)),
    [],
  );

  return (
    <div>
      <SectionTitle eyebrow="Ingestion" title="Upload a document" />

      <p className="mb-5 max-w-2xl text-sm text-muted">
        A .pdf, .xlsx, .docx or an image is parsed — images through OCR — then
        chunked, embedded and written to the vector index. It is stamped with{" "}
        <span className="text-ink">your tenant and your ACL groups</span> — read
        from your token, not chosen here — so nobody outside them will ever
        retrieve it.
      </p>

      {me && (
        <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-line bg-panel-2/50 px-4 py-2.5 text-sm">
          <span className="stamp text-[10px] text-faint">will be indexed as</span>
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
        </div>
      )}

      <Panel className="overflow-hidden">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            accept(e.dataTransfer.files?.[0]);
          }}
          className={`dossier-grid m-3 rounded-lg border border-dashed p-6 text-center transition-colors ${
            dragging ? "border-accent bg-accent/5" : "border-line"
          }`}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.xlsx,.docx,.png,.jpg,.jpeg"
            className="hidden"
            onChange={(e) => accept(e.target.files?.[0])}
          />

          <AnimatePresence mode="wait">
            {file ? (
              <motion.div key="picked" {...anim}>
                <div className="mx-auto flex max-w-md items-center gap-3 rounded-lg border border-line bg-panel px-3 py-2.5 text-left">
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-panel-2 text-muted">
                    <IconDoc width={17} height={17} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{file.name}</div>
                    <div className="text-xs text-muted">
                      {formatBytes(file.size)} · {extOf(file.name).slice(1)}
                    </div>
                  </div>
                  <button
                    onClick={() => {
                      setFile(null);
                      if (inputRef.current) inputRef.current.value = "";
                    }}
                    className="shrink-0 text-faint transition-colors hover:text-ink"
                    aria-label="Clear selected file"
                  >
                    <IconClose width={15} height={15} />
                  </button>
                </div>

                <div className="mt-4 flex flex-wrap justify-center gap-2">
                  <Button onClick={submit} disabled={submitting}>
                    {submitting ? <Spinner /> : <IconUpload width={16} height={16} />}
                    {submitting ? "Sending…" : "Queue for ingestion"}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => inputRef.current?.click()}
                    disabled={submitting}
                  >
                    Choose a different file
                  </Button>
                </div>
              </motion.div>
            ) : (
              <motion.div key="empty" {...anim}>
                <div className="mx-auto mb-3 grid h-11 w-11 place-items-center rounded-full bg-panel-2 text-muted">
                  <IconUpload />
                </div>
                <p className="text-sm text-muted">
                  Drop a file here, or{" "}
                  <button
                    onClick={() => inputRef.current?.click()}
                    className="font-medium text-accent hover:underline"
                  >
                    browse
                  </button>
                </p>
                <p className="stamp mt-2 text-[10px] text-faint">
                  .pdf, .xlsx, .docx, .png, .jpg or .jpeg
                </p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <AnimatePresence>
          {rejection && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div
                role="alert"
                className="mx-3 mb-3 flex items-start gap-2 rounded-lg border border-danger/35 bg-danger-bg px-3 py-2.5 text-sm"
              >
                <IconAlert width={16} height={16} className="mt-0.5 shrink-0 text-danger" />
                <span className="flex-1">{rejection}</span>
                <button
                  onClick={() => setRejection(null)}
                  className="shrink-0 text-faint hover:text-ink"
                  aria-label="Dismiss"
                >
                  <IconClose width={14} height={14} />
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </Panel>

      {/* Session-local, deliberately: the backend exposes job state but no upload
          history, so claiming one here would be a lie that survives a reload. */}
      <div className="mt-8">
        <div className="mb-2 flex items-baseline justify-between gap-3">
          <div className="stamp text-[11px] text-faint">
            This session · {queue.length}
          </div>
          {queue.length > 0 && (
            <span className="text-xs text-faint">
              Polled every {POLL_MS / 1000}s until each one settles.
            </span>
          )}
        </div>

        {queue.length === 0 ? (
          <div className="rounded-xl border border-dashed border-line px-6 py-10 text-center text-sm text-muted">
            Nothing queued yet. Uploads you make now will appear here with live
            status — this list is not kept after a reload.
          </div>
        ) : (
          <Panel>
            <motion.div
              variants={listContainer}
              initial="hidden"
              animate="show"
              className="divide-y divide-line"
            >
              <AnimatePresence initial={false}>
                {queue.map((entry) => (
                  <JobRow
                    key={entry.key}
                    entry={entry}
                    onSettle={onSettle}
                    onRetry={retry}
                    onDismiss={dismiss}
                  />
                ))}
              </AnimatePresence>
            </motion.div>
          </Panel>
        )}
      </div>
    </div>
  );
}

const anim = {
  variants: fadeUp,
  initial: "hidden" as const,
  animate: "show" as const,
  exit: "exit" as const,
};
