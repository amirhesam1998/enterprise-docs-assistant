import type { ReactNode } from "react";
import { AnimatePresence, MotionConfig, motion } from "framer-motion";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { ToastProvider } from "./components/Toast";
import { AppShell } from "./components/AppShell";
import { RequireAuth, RequirePanel } from "./components/guards";
import { routeFade } from "./lib/motion";
import LoginPage from "./pages/LoginPage";
import SignupPage from "./pages/SignupPage";
import AskPage from "./pages/AskPage";
import UploadPage from "./pages/UploadPage";
import UsersPage from "./pages/admin/UsersPage";
import RolesPage from "./pages/admin/RolesPage";
import PermissionsPage from "./pages/admin/PermissionsPage";

function AnimatedRoute({ children }: { children: ReactNode }) {
  return (
    <motion.div variants={routeFade} initial="hidden" animate="show" exit="exit">
      {children}
    </motion.div>
  );
}

function AppRoutes() {
  const location = useLocation();
  return (
    // NOTE: no mode="wait". A route guard can render null on its way out (e.g. on
    // logout the protected route redirects and returns null). mode="wait" would
    // then block forever waiting on an exit animation that never fires, leaving a
    // blank screen. The default (concurrent) mode mounts the incoming route
    // immediately, so enter animations still play and nothing can deadlock.
    <AnimatePresence>
      <Routes location={location} key={location.pathname}>
        <Route path="/login" element={<AnimatedRoute><LoginPage /></AnimatedRoute>} />
        <Route path="/signup" element={<AnimatedRoute><SignupPage /></AnimatedRoute>} />

        <Route
          path="/ask"
          element={
            <RequireAuth>
              <AppShell>
                <AnimatedRoute><AskPage /></AnimatedRoute>
              </AppShell>
            </RequireAuth>
          }
        />
        {/* Not an /admin route, but gated by RequirePanel all the same: the
            backend's require_permission("documents.upload") folds in the same
            panel-level test, so this mirrors what the server will actually do. */}
        <Route
          path="/upload"
          element={
            <RequireAuth>
              <AppShell>
                <RequirePanel perm="documents.upload">
                  <AnimatedRoute><UploadPage /></AnimatedRoute>
                </RequirePanel>
              </AppShell>
            </RequireAuth>
          }
        />
        <Route
          path="/admin/users"
          element={
            <RequireAuth>
              <AppShell>
                <RequirePanel perm="users.read">
                  <AnimatedRoute><UsersPage /></AnimatedRoute>
                </RequirePanel>
              </AppShell>
            </RequireAuth>
          }
        />
        <Route
          path="/admin/roles"
          element={
            <RequireAuth>
              <AppShell>
                <RequirePanel perm="roles.read">
                  <AnimatedRoute><RolesPage /></AnimatedRoute>
                </RequirePanel>
              </AppShell>
            </RequireAuth>
          }
        />
        <Route
          path="/admin/permissions"
          element={
            <RequireAuth>
              <AppShell>
                <RequirePanel perm="permissions.read">
                  <AnimatedRoute><PermissionsPage /></AnimatedRoute>
                </RequirePanel>
              </AppShell>
            </RequireAuth>
          }
        />

        <Route path="/" element={<Navigate to="/ask" replace />} />
        <Route path="*" element={<Navigate to="/ask" replace />} />
      </Routes>
    </AnimatePresence>
  );
}

export default function App() {
  return (
    <MotionConfig reducedMotion="user">
      <AuthProvider>
        <ToastProvider>
          <AppRoutes />
        </ToastProvider>
      </AuthProvider>
    </MotionConfig>
  );
}
