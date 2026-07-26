import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "../../api/client";
import type { Permission, Role } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { useToast } from "../../components/Toast";
import {
  Button,
  Chip,
  Field,
  Input,
  Panel,
  SectionTitle,
  Spinner,
} from "../../components/primitives";
import { Modal } from "../../components/Modal";
import { IconCheck, IconEdit, IconPlus, IconTrash } from "../../components/icons";
import { listContainer, listItem } from "../../lib/motion";

export default function RolesPage() {
  const { can } = useAuth();
  const toast = useToast();
  const canWrite = can("roles.write");
  const canSeePerms = can("permissions.read");

  const [roles, setRoles] = useState<Role[]>([]);
  const [perms, setPerms] = useState<Permission[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Role | null>(null);
  const [draft, setDraft] = useState({ name: "", description: "" });
  const [draftPerms, setDraftPerms] = useState<Set<number>>(new Set());
  const [saving, setSaving] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const [r, p] = await Promise.all([
        api.listRoles(),
        canSeePerms ? api.listPermissions() : Promise.resolve<Permission[]>([]),
      ]);
      setRoles(r);
      setPerms(p);
    } catch (e) {
      toast.fromError(e, "Could not load roles");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function openCreate() {
    setEditing(null);
    setDraft({ name: "", description: "" });
    setDraftPerms(new Set());
    setModalOpen(true);
  }
  function openEdit(r: Role) {
    setEditing(r);
    setDraft({ name: r.name, description: r.description });
    setModalOpen(true);
  }

  async function save() {
    setSaving(true);
    try {
      if (editing) {
        await api.updateRole(editing.id, draft);
        toast.push({ tone: "success", title: "Role updated" });
      } else {
        await api.createRole({
          name: draft.name,
          description: draft.description,
          permission_ids: [...draftPerms],
        });
        toast.push({ tone: "success", title: `Created ${draft.name}` });
      }
      setModalOpen(false);
      await load();
    } catch (e) {
      toast.fromError(e, "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function remove(r: Role) {
    if (!confirm(`Delete role "${r.name}"? It will be detached from all users.`))
      return;
    try {
      await api.deleteRole(r.id);
      toast.push({ tone: "success", title: `Deleted ${r.name}` });
      await load();
    } catch (e) {
      toast.fromError(e, "Delete failed");
    }
  }

  async function togglePerm(role: Role, perm: Permission, attached: boolean) {
    try {
      if (attached) await api.detachPermission(role.id, perm.id);
      else await api.attachPermission(role.id, perm.id);
      await load();
    } catch (e) {
      toast.fromError(e, "Permission change failed");
    }
  }

  return (
    <div>
      <SectionTitle eyebrow="Admin · Composition" title="Roles">
        {canWrite && (
          <Button onClick={openCreate}>
            <IconPlus width={16} height={16} /> New role
          </Button>
        )}
      </SectionTitle>

      {loading ? (
        <div className="flex items-center gap-2 py-10 text-muted">
          <Spinner /> loading…
        </div>
      ) : (
        <motion.div variants={listContainer} initial="hidden" animate="show" className="space-y-2.5">
          <AnimatePresence>
            {roles.map((r) => {
              const open = expanded === r.id;
              const attachedIds = new Set(r.permissions.map((p) => p.id));
              const available = perms.filter((p) => !attachedIds.has(p.id));
              return (
                <motion.div key={r.id} variants={listItem} layout exit="exit">
                  <Panel className="overflow-hidden">
                    <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold">{r.name}</span>
                          <span className="stamp text-[10px] text-faint">
                            {r.permissions.length} perms
                          </span>
                        </div>
                        {r.description && (
                          <p className="mt-0.5 text-sm text-muted">{r.description}</p>
                        )}
                        <div className="mt-2.5 flex flex-wrap gap-1.5">
                          {r.permissions.length === 0 && (
                            <span className="text-xs text-faint">
                              empty role — grants nothing
                            </span>
                          )}
                          {r.permissions.map((p) => (
                            <Chip
                              key={p.id}
                              tone="accent"
                              onRemove={canWrite ? () => togglePerm(r, p, true) : undefined}
                            >
                              <code className="font-mono">{p.name}</code>
                            </Chip>
                          ))}
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-1.5">
                        {canWrite && canSeePerms && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setExpanded(open ? null : r.id)}
                          >
                            {open ? "Done" : "Compose"}
                          </Button>
                        )}
                        {canWrite && (
                          <Button variant="outline" size="sm" onClick={() => openEdit(r)}>
                            <IconEdit width={15} height={15} />
                          </Button>
                        )}
                        {canWrite && (
                          <Button variant="danger" size="sm" onClick={() => remove(r)}>
                            <IconTrash width={15} height={15} />
                          </Button>
                        )}
                      </div>
                    </div>

                    {/* Direct composer: click to attach from the catalog. */}
                    <AnimatePresence initial={false}>
                      {open && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.22 }}
                          className="border-t border-line bg-panel-2/40"
                        >
                          <div className="p-4">
                            <div className="stamp mb-2 text-[10px] text-faint">
                              available permissions · click to attach
                            </div>
                            <div className="flex flex-wrap gap-1.5">
                              {available.length === 0 && (
                                <span className="text-xs text-faint">
                                  every permission is already attached
                                </span>
                              )}
                              {available.map((p) => (
                                <button
                                  key={p.id}
                                  onClick={() => togglePerm(r, p, false)}
                                  className="group inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-0.5 text-xs text-muted transition-colors hover:border-accent hover:text-accent"
                                >
                                  <IconPlus width={12} height={12} />
                                  <code className="font-mono">{p.name}</code>
                                </button>
                              ))}
                            </div>
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </Panel>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </motion.div>
      )}

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editing ? `Edit ${editing.name}` : "New role"}
        footer={
          <>
            <Button variant="ghost" onClick={() => setModalOpen(false)}>
              Cancel
            </Button>
            <Button onClick={save} disabled={saving || !draft.name.trim()}>
              {saving ? <Spinner /> : editing ? "Save" : "Create"}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Name">
            <Input
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              placeholder="e.g. User Manager"
            />
          </Field>
          <Field label="Description">
            <Input
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              placeholder="What this bundle is for"
            />
          </Field>
          {!editing && canSeePerms && (
            <Field label="Permissions" hint="Pick the starting set — you can recompose anytime.">
              <div className="flex flex-wrap gap-1.5">
                {perms.map((p) => {
                  const on = draftPerms.has(p.id);
                  return (
                    <button
                      key={p.id}
                      onClick={() =>
                        setDraftPerms((prev) => {
                          const next = new Set(prev);
                          on ? next.delete(p.id) : next.add(p.id);
                          return next;
                        })
                      }
                      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs transition-colors ${
                        on
                          ? "border-accent/40 bg-accent/12 text-accent"
                          : "border-line text-muted hover:text-ink"
                      }`}
                    >
                      {on && <IconCheck width={12} height={12} />}
                      <code className="font-mono">{p.name}</code>
                    </button>
                  );
                })}
              </div>
            </Field>
          )}
        </div>
      </Modal>
    </div>
  );
}
