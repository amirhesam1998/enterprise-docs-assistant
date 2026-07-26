import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "../api/client";
import type { AskResponse, Level } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { DEMO_ACCOUNTS } from "../auth/demoAccounts";
import { useToast } from "../components/Toast";
import { Button, Chip, Panel, Select } from "../components/primitives";
import { LevelBadge } from "../components/LevelBadge";
import { SourceCard } from "../components/SourceCard";
import { LoadingNarrator } from "../components/LoadingNarrator";
import { IconCompare, IconSearch } from "../components/icons";
import { detectDir, sourceKey } from "../lib/format";
import { fadeUp, listContainer, listItem } from "../lib/motion";

interface ResultIdentity {
  username: string;
  level: Level;
  tenant_id: string;
  acl_groups: string[];
}
interface Result {
  identity: ResultIdentity;
  res: AskResponse;
}

const EXAMPLES = [
  "How do I resolve a billing invoice problem?",
  "مشکل درِ سردخانه را چطور برطرف کنم؟",
  "What are the evaporator specifications?",
];

function IdentityHeader({ id }: { id: ResultIdentity }) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
      <span className="font-semibold">{id.username}</span>
      <LevelBadge level={id.level} size="sm" />
      <Chip tone="accent">{id.tenant_id}</Chip>
      {id.acl_groups.map((g) => (
        <Chip key={g}>{g}</Chip>
      ))}
    </div>
  );
}

function AnswerBody({
  res,
  uniqueKeys,
}: {
  res: AskResponse;
  uniqueKeys?: Set<string>;
}) {
  const dir = detectDir(res.answer);
  return (
    <div className="p-4">
      <div
        dir={dir}
        className="whitespace-pre-wrap text-[15px] leading-relaxed text-ink"
      >
        {res.answer}
      </div>
      <div className="mt-4">
        <div className="stamp mb-2 text-[11px] text-faint">
          Sources · {res.sources.length}
        </div>
        <motion.div
          variants={listContainer}
          initial="hidden"
          animate="show"
          className="space-y-2"
        >
          {res.sources.map((s, i) => (
            <motion.div key={sourceKey(s) + i} variants={listItem}>
              <SourceCard source={s} unique={uniqueKeys?.has(sourceKey(s))} />
            </motion.div>
          ))}
          {res.sources.length === 0 && (
            <div className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-sm text-muted">
              No documents matched — this identity may not have access to anything
              relevant.
            </div>
          )}
        </motion.div>
      </div>
    </div>
  );
}

export default function AskPage() {
  const { me } = useAuth();
  const toast = useToast();

  const [question, setQuestion] = useState("");
  const [k, setK] = useState(5);
  const [loading, setLoading] = useState(false);
  const [primary, setPrimary] = useState<Result | null>(null);

  const [compareUser, setCompareUser] = useState<string | null>(null);
  const [comparing, setComparing] = useState(false);
  const [secondary, setSecondary] = useState<Result | null>(null);

  const compareOptions = DEMO_ACCOUNTS.filter((a) => a.username !== me?.username);

  // Diff the two source sets so the comparison view can call out what differs.
  const { uniqueA, uniqueB } = useMemo(() => {
    if (!primary || !secondary) return { uniqueA: undefined, uniqueB: undefined };
    const a = new Set(primary.res.sources.map(sourceKey));
    const b = new Set(secondary.res.sources.map(sourceKey));
    return {
      uniqueA: new Set([...a].filter((x) => !b.has(x))),
      uniqueB: new Set([...b].filter((x) => !a.has(x))),
    };
  }, [primary, secondary]);

  async function runPrimary(q: string) {
    if (!q.trim() || !me) return;
    setLoading(true);
    setPrimary(null);
    setSecondary(null);
    setCompareUser(null);
    try {
      const res = await api.ask(q, k);
      setPrimary({
        identity: {
          username: me.username,
          level: me.level,
          tenant_id: me.tenant_id,
          acl_groups: me.acl_groups,
        },
        res,
      });
    } catch (e) {
      toast.fromError(e, "The question could not be answered");
    } finally {
      setLoading(false);
    }
  }

  async function runCompare(username: string) {
    const acct = DEMO_ACCOUNTS.find((a) => a.username === username);
    if (!acct || !primary) return;
    setCompareUser(username);
    setComparing(true);
    setSecondary(null);
    try {
      // Log in as the other identity on a throwaway token — the real session is
      // untouched — then re-run the identical question.
      const token = await api.login(acct.username, acct.password);
      const who = await api.me(token);
      const res = await api.ask(question, k, token);
      setSecondary({
        identity: {
          username: who.username,
          level: who.level,
          tenant_id: who.tenant_id,
          acl_groups: who.acl_groups,
        },
        res,
      });
    } catch (e) {
      toast.fromError(e, "Comparison failed");
      setCompareUser(null);
    } finally {
      setComparing(false);
    }
  }

  const diffCount =
    uniqueA && uniqueB ? uniqueA.size + uniqueB.size : 0;

  return (
    <div>
      {/* Query toolbar — deliberately not a centered hero with one input. */}
      <Panel className="overflow-hidden">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            runPrimary(question);
          }}
          className="flex flex-col gap-3 p-4 sm:flex-row sm:items-end"
        >
          <div className="flex-1">
            <label className="stamp mb-1.5 block text-[11px] text-faint">
              Ask the corpus
            </label>
            <div className="flex items-center gap-2 rounded-lg border border-line bg-paper px-3 focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/25">
              <IconSearch className="text-faint" />
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Ask in English or Persian…"
                className="h-11 flex-1 bg-transparent text-sm outline-none placeholder:text-faint"
              />
            </div>
          </div>
          <div className="w-24">
            <label className="stamp mb-1.5 block text-[11px] text-faint">
              Top-k
            </label>
            <Select value={k} onChange={(e) => setK(Number(e.target.value))}>
              {[3, 5, 8, 10].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </Select>
          </div>
          <Button type="submit" disabled={loading || !question.trim()} className="sm:w-28">
            {loading ? "Asking…" : "Ask"}
          </Button>
        </form>
      </Panel>

      <div className="mt-6">
        <AnimatePresence mode="wait">
          {loading && (
            <motion.div key="loading" {...anim}>
              <LoadingNarrator />
            </motion.div>
          )}

          {!loading && !primary && (
            <motion.div key="empty" {...anim}>
              <div className="rounded-xl border border-dashed border-line px-6 py-14 text-center">
                <div className="mx-auto mb-4 grid h-11 w-11 place-items-center rounded-full bg-panel-2 text-muted">
                  <IconSearch />
                </div>
                <p className="mx-auto max-w-md text-sm text-muted">
                  Ask a question, then re-run it as another identity to see access
                  control change the answer. Try:
                </p>
                <div className="mt-4 flex flex-wrap justify-center gap-2">
                  {EXAMPLES.map((ex) => (
                    <button
                      key={ex}
                      dir={detectDir(ex)}
                      onClick={() => {
                        setQuestion(ex);
                        runPrimary(ex);
                      }}
                      className="rounded-full border border-line px-3 py-1.5 text-sm text-muted transition-colors hover:border-line-strong hover:text-ink"
                    >
                      {ex}
                    </button>
                  ))}
                </div>
              </div>
            </motion.div>
          )}

          {!loading && primary && !secondary && !comparing && (
            <motion.div key="single" {...anim} className="space-y-5">
              <Panel>
                <IdentityHeader id={primary.identity} />
                <AnswerBody res={primary.res} />
              </Panel>

              {/* Comparison invitation — a first-class prompt, not a hidden extra. */}
              <Panel className="p-4">
                <div className="flex items-center gap-2">
                  <IconCompare className="text-accent" />
                  <div className="text-sm font-semibold">
                    Ask the identical question as someone else
                  </div>
                </div>
                <p className="mt-1 text-sm text-muted">
                  Same words, different clearance. Watch the sources — and the
                  answer — change.
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {compareOptions.map((a) => (
                    <button
                      key={a.username}
                      onClick={() => runCompare(a.username)}
                      className="flex items-center gap-2 rounded-full border border-line px-3 py-1.5 text-sm transition-colors hover:border-accent hover:text-accent"
                    >
                      <span className="font-medium">{a.username}</span>
                      <LevelBadge level={a.level} size="sm" />
                    </button>
                  ))}
                </div>
              </Panel>
            </motion.div>
          )}

          {!loading && primary && (comparing || secondary) && (
            <motion.div key="compare" {...anim} className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="stamp text-[11px] text-accent">Side by side</div>
                  <h2 className="text-lg font-semibold">
                    One question, two identities
                  </h2>
                </div>
                {secondary && (
                  <div className="rounded-md border border-accent/40 bg-accent/10 px-3 py-1.5 text-sm text-accent">
                    {diffCount === 0
                      ? "Same sources for both — no access difference here."
                      : `${diffCount} source${diffCount === 1 ? "" : "s"} differ between them`}
                  </div>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setSecondary(null);
                    setCompareUser(null);
                  }}
                >
                  ← Back to single view
                </Button>
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                <Panel className="ring-1 ring-transparent">
                  <IdentityHeader id={primary.identity} />
                  <AnswerBody res={primary.res} uniqueKeys={uniqueA} />
                </Panel>

                <Panel>
                  {comparing && !secondary ? (
                    <div className="p-4">
                      <div className="stamp mb-3 text-[11px] text-faint">
                        Running as {compareUser}
                      </div>
                      <LoadingNarrator />
                    </div>
                  ) : (
                    secondary && (
                      <>
                        <IdentityHeader id={secondary.identity} />
                        <AnswerBody res={secondary.res} uniqueKeys={uniqueB} />
                      </>
                    )
                  )}
                </Panel>
              </div>

              {secondary && (
                <p className="text-center text-xs text-muted">
                  Highlighted sources appear for only one identity. The retrieval
                  layer filtered them by tenant and ACL groups before the model
                  ever saw them.
                </p>
              )}
            </motion.div>
          )}
        </AnimatePresence>
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
