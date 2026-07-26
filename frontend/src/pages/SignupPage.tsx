import { useState, type ChangeEvent, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { Button, Field, Input, Spinner } from "../components/primitives";
import { ThemeToggle } from "../components/ThemeToggle";
import { IconShield } from "../components/icons";

export default function SignupPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ username: "", password: "", email: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (k: keyof typeof form) => (e: ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.signup({
        username: form.username,
        password: form.password,
        email: form.email || undefined,
      });
      // Server always makes new accounts level `user` with the default tenant —
      // the form can't ask for anything more, by design. Log straight in.
      await login(form.username, form.password);
      navigate("/ask");
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Could not create account");
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col p-6 sm:p-10">
      <div className="mb-8 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-md bg-ink text-paper">
            <IconShield width={16} height={16} />
          </span>
          <span className="stamp text-xs text-muted">Clearance</span>
        </div>
        <ThemeToggle />
      </div>

      <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center">
        <h2 className="text-2xl font-semibold tracking-tight">Create an account</h2>
        <p className="mt-1 text-sm text-muted">
          Already have one?{" "}
          <Link to="/login" className="font-medium text-accent hover:underline">
            Sign in
          </Link>
        </p>

        <div className="mt-4 rounded-md border border-line bg-panel-2 px-3 py-2 text-xs leading-relaxed text-muted">
          New accounts are always created at{" "}
          <span className="stamp text-user">user</span> level with the default
          tenant. Level, roles, and document access are assigned by an
          administrator — never chosen at signup.
        </div>

        <form className="mt-6 space-y-4" onSubmit={submit}>
          <Field label="Username">
            <Input autoFocus value={form.username} onChange={set("username")} placeholder="pick a username" />
          </Field>
          <Field label="Email" hint="Optional.">
            <Input type="email" value={form.email} onChange={set("email")} placeholder="you@company.com" />
          </Field>
          <Field label="Password">
            <Input type="password" value={form.password} onChange={set("password")} placeholder="••••••••" />
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
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? <Spinner /> : "Create account"}
          </Button>
        </form>
      </div>
    </div>
  );
}
