# Clearance — Frontend

React frontend for the multi-tenant RAG assistant with dynamic RBAC (Part 2).
The one thing this UI exists to make visible: **two identities asking the same
question get different answers from different documents**, because access control
is enforced at the retrieval layer.

## Stack

React 19 · Vite 6 · TypeScript · Tailwind v4 · Framer Motion · React Router 7.
Fonts bundled via `@fontsource-variable` (Inter for Latin, Vazirmatn for Persian,
JetBrains Mono for metadata) — no runtime font CDN.

## Run

The backend (Part 1) must be running on `http://127.0.0.1:8000`:

```bash
# from repo root
uv run uvicorn api.main:app --reload
```

Then the frontend:

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

Vite proxies `/api/*` → `http://127.0.0.1:8000`, so the browser origin stays
`localhost:5173` (which the backend's CORS allows).

`npm run build` type-checks (`tsc -b`) and produces a production bundle in `dist/`.

## What to try

1. Sign in with a one-click demo identity (credentials also in `../API.md`).
2. On **Ask**, run a question — then hit "Ask the identical question as someone
   else" and pick a different identity. The two answers appear side by side with
   the differing sources highlighted.
3. Sign in as `sara` (admin, `users.read`/`users.write`) — the nav shows **Users**
   but not Roles/Permissions. Sign in as `ali` (user) — no admin nav at all. Sign
   in as `creator` — everything.

## Architecture notes

- **Everything authz-related is driven by `GET /auth/me`.** `AuthContext` exposes
  `can(perm)` (creator bypasses) and `hasAdminPanel`; nav and route guards read
  from it. The backend re-enforces every rule and will 403 regardless — a 403
  that arrives anyway is surfaced as a toast rather than crashing.
- **Route guards redirect via `useEffect`, not `<Navigate>`,** and the route
  `<AnimatePresence>` deliberately does not use `mode="wait"`. Both avoid a
  render deadlock/loop when a guard unmounts a protected route on logout.
- `src/lib/format.ts` holds the per-answer RTL/LTR detection, the polymorphic
  source-location renderer (`cell` → "Ops Runbook, row 3", `page` → "page 145"),
  the score→percent/band formatter, and the source-diff key used by the
  comparison view.
- Motion respects `prefers-reduced-motion` (`MotionConfig reducedMotion="user"`
  plus a CSS backstop).
