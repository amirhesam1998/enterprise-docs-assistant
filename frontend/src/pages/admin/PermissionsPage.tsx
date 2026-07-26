import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "../../api/client";
import type { Permission } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { useToast } from "../../components/Toast";
import {
  Button,
  Field,
  Input,
  Panel,
  SectionTitle,
  Spinner,
} from "../../components/primitives";
import { Modal } from "../../components/Modal";
import { IconPlus, IconTrash } from "../../components/icons";
import { listItem } from "../../lib/motion";

export default function PermissionsPage() {
  const { can } = useAuth();
  const toast = useToast();
  const canWrite = can("permissions.write");

  const [perms, setPerms] = useState<Permission[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [draft, setDraft] = useState({ name: "", description: "" });
  const [saving, setSaving] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setPerms(await api.listPermissions());
    } catch (e) {
      toast.fromError(e, "Could not load permissions");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Group by resource (the part before the dot) purely for scannability.
  const groups = useMemo(() => {
    const map = new Map<string, Permission[]>();
    for (const p of perms) {
      const key = p.name.includes(".") ? p.name.split(".")[0] : "other";
      (map.get(key) ?? map.set(key, []).get(key)!).push(p);
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [perms]);

  async function create() {
    setSaving(true);
    try {
      await api.createPermission(draft);
      toast.push({ tone: "success", title: `Created ${draft.name}` });
      setModalOpen(false);
      setDraft({ name: "", description: "" });
      await load();
    } catch (e) {
      toast.fromError(e, "Create failed");
    } finally {
      setSaving(false);
    }
  }

  async function remove(p: Permission) {
    if (!confirm(`Delete permission "${p.name}"?`)) return;
    try {
      await api.deletePermission(p.id);
      toast.push({ tone: "success", title: `Deleted ${p.name}` });
      await load();
    } catch (e) {
      toast.fromError(e, "Delete failed");
    }
  }

  return (
    <div>
      <SectionTitle eyebrow="Admin · Atoms" title="Permissions">
        {canWrite && (
          <Button onClick={() => setModalOpen(true)}>
            <IconPlus width={16} height={16} /> New permission
          </Button>
        )}
      </SectionTitle>

      <p className="mb-5 max-w-2xl text-sm text-muted">
        The granular capabilities that roles bundle. Named{" "}
        <code className="stamp text-accent">resource.action</code>. These gate API
        features — never document access.
      </p>

      {loading ? (
        <div className="flex items-center gap-2 py-10 text-muted">
          <Spinner /> loading…
        </div>
      ) : (
        <div className="space-y-6">
          {groups.map(([resource, list]) => (
            <div key={resource}>
              <div className="stamp mb-2 text-[11px] text-faint">{resource}</div>
              <Panel className="divide-y divide-line">
                <AnimatePresence>
                  {list.map((p) => (
                    <motion.div
                      key={p.id}
                      variants={listItem}
                      initial="hidden"
                      animate="show"
                      exit="exit"
                      layout
                      className="flex items-center justify-between gap-4 px-4 py-2.5"
                    >
                      <div className="min-w-0">
                        <code className="font-mono text-sm text-ink">{p.name}</code>
                        {p.description && (
                          <span className="ml-3 text-sm text-muted">
                            {p.description}
                          </span>
                        )}
                      </div>
                      {canWrite && (
                        <button
                          onClick={() => remove(p)}
                          className="shrink-0 text-faint transition-colors hover:text-danger"
                          aria-label={`Delete ${p.name}`}
                        >
                          <IconTrash width={16} height={16} />
                        </button>
                      )}
                    </motion.div>
                  ))}
                </AnimatePresence>
              </Panel>
            </div>
          ))}
        </div>
      )}

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title="New permission"
        footer={
          <>
            <Button variant="ghost" onClick={() => setModalOpen(false)}>
              Cancel
            </Button>
            <Button onClick={create} disabled={saving || !draft.name.trim()}>
              {saving ? <Spinner /> : "Create"}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Name" hint="Format: resource.action, e.g. reports.read">
            <Input
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              placeholder="reports.read"
            />
          </Field>
          <Field label="Description">
            <Input
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              placeholder="What this capability allows"
            />
          </Field>
        </div>
      </Modal>
    </div>
  );
}
