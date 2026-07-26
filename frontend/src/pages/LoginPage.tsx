import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { useAuth } from "../auth/AuthContext";
import { DEMO_ACCOUNTS } from "../auth/demoAccounts";
import { Button, Field, Input, Spinner } from "../components/primitives";
import { LevelBadge } from "../components/LevelBadge";
import { ThemeToggle } from "../components/ThemeToggle";
import { IconArrow, IconShield } from "../components/icons";
import { ApiError } from "../api/client";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(u: string, p: string) {
    setError(null);
    setBusy(u || "form");
    try {
      await login(u, p);
      navigate("/ask");
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Could not sign in");
      setBusy(null);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      {/* Left: the thesis. This project is about access control being visible. */}
      <aside className="dossier-grid relative hidden flex-col justify-between bg-panel p-10 lg:flex">
        <div className="flex items-center gap-2.5">
          <span className="grid h-9 w-9 place-items-center rounded-md bg-ink text-paper">
            <IconShield width={18} height={18} />
          </span>
          <div className="stamp text-xs text-muted">Clearance · Enterprise Docs</div>
        </div>
        <div className="max-w-md">
          <div className="stamp mb-3 text-xs text-accent">The whole point</div>
          <h1 className="text-3xl font-semibold leading-tight tracking-tight">
            Two people ask the same question and get different answers —
            <span className="text-accent"> because the documents they can reach differ.</span>
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-muted">
            Access control is enforced at retrieval, not bolted on after. Sign in
            as one identity, ask something, then re-run it as another and watch the
            sources change. Feature access (the admin panel) and document access
            (what you can read) are two separate axes here.
          </p>
        </div>
        <div className="flex gap-6 text-xs text-faint">
          <div>
            <div className="stamp text-accent">RBAC</div>
            which features you can invoke
          </div>
          <div>
            <div className="stamp text-accent">ACL</div>
            which documents you can retrieve
          </div>
        </div>
      </aside>

      {/* Right: auth */}
      <div className="flex flex-col p-6 sm:p-10">
        <div className="mb-8 flex items-center justify-between">
          <span className="stamp text-xs text-muted lg:hidden">Clearance</span>
          <div className="ml-auto">
            <ThemeToggle />
          </div>
        </div>

        <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center">
          <h2 className="text-2xl font-semibold tracking-tight">Sign in</h2>
          <p className="mt-1 text-sm text-muted">
            New here?{" "}
            <Link to="/signup" className="font-medium text-accent hover:underline">
              Create an account
            </Link>
          </p>

          <form
            className="mt-6 space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              submit(username, password);
            }}
          >
            <Field label="Username">
              <Input
                autoFocus
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="e.g. sara"
              />
            </Field>
            <Field label="Password">
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
              />
            </Field>
            {error && (
              <motion.div
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                className="rounded-md border border-danger/40 bg-danger-bg px-3 py-2 text-sm text-danger"
              >
                {error}
              </motion.div>
            )}
            <Button type="submit" className="w-full" disabled={busy === "form"}>
              {busy === "form" ? <Spinner /> : "Sign in"}
              {busy !== "form" && <IconArrow width={16} height={16} />}
            </Button>
          </form>

          <div className="my-6 flex items-center gap-3 text-xs text-faint">
            <span className="h-px flex-1 bg-line" />
            <span className="stamp">or step into a demo identity</span>
            <span className="h-px flex-1 bg-line" />
          </div>

          <div className="grid gap-2">
            {DEMO_ACCOUNTS.map((a) => (
              <button
                key={a.username}
                onClick={() => submit(a.username, a.password)}
                disabled={!!busy}
                className="group flex items-center gap-3 rounded-lg border border-line bg-panel px-3 py-2.5
                  text-left transition-colors hover:border-line-strong hover:bg-panel-2 disabled:opacity-60"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{a.username}</span>
                    <LevelBadge level={a.level} size="sm" />
                  </div>
                  <div className="truncate text-xs text-muted">{a.blurb}</div>
                </div>
                {busy === a.username ? (
                  <Spinner className="text-muted" />
                ) : (
                  <IconArrow
                    width={16}
                    height={16}
                    className="text-faint transition-transform group-hover:translate-x-0.5 group-hover:text-accent"
                  />
                )}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
