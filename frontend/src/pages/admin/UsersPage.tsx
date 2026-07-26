import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "../../api/client";
import type { AdminUser, Level, Role } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { useToast } from "../../components/Toast";
import {
  Button,
  Chip,
  Field,
  Input,
  Panel,
  SectionTitle,
  Select,
  Spinner,
} from "../../components/primitives";
import { LevelBadge } from "../../components/LevelBadge";
import { Modal } from "../../components/Modal";
import { IconEdit, IconKey, IconPlus, IconTrash } from "../../components/icons";
import { listContainer, listItem } from "../../lib/motion";

type Draft = {
  username: string;
  password: string;
  email: string;
  level: Level;
  tenant_id: string;
  acl_groups: string;
};

const emptyDraft: Draft = {
  username: "",
  password: "",
  email: "",
  level: "user",
  tenant_id: "",
  acl_groups: "",
};

export default function UsersPage() {
  const { me, can, refreshMe } = useAuth();
  const toast = useToast();
  const isCreator = me?.level === "creator";
  const canWrite = can("users.write");
  const canDelete = can("users.delete");

  const [users, setUsers] = useState<AdminUser[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);

  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [saving, setSaving] = useState(false);

  const allowedLevels: Level[] = isCreator
    ? ["user", "admin", "creator"]
    : ["user"];

  async function load() {
    setLoading(true);
    try {
      const [u, r] = await Promise.all([
        api.listUsers(),
        can("roles.read") ? api.listRoles() : Promise.resolve<Role[]>([]),
      ]);
      setUsers(u);
      setRoles(r);
    } catch (e) {
      toast.fromError(e, "Could not load users");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function openCreate() {
    setEditingId(null);
    setDraft(emptyDraft);
    setModalOpen(true);
  }
  function openEdit(u: AdminUser) {
    setEditingId(u.id);
    setDraft({
      username: u.username,
      password: "",
      email: u.email ?? "",
      level: u.level,
      tenant_id: u.tenant_id,
      acl_groups: u.acl_groups.join(", "),
    });
    setModalOpen(true);
  }

  async function save() {
    setSaving(true);
    const acl = draft.acl_groups
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    try {
      if (editingId == null) {
        await api.createUser({
          username: draft.username,
          password: draft.password,
          email: draft.email || null,
          level: draft.level,
          tenant_id: draft.tenant_id || undefined,
          acl_groups: acl,
        });
        toast.push({ tone: "success", title: `Created ${draft.username}` });
      } else {
        await api.updateUser(editingId, {
          ...(draft.password ? { password: draft.password } : {}),
          email: draft.email || null,
          level: draft.level,
          tenant_id: draft.tenant_id,
          acl_groups: acl,
        });
        toast.push({ tone: "success", title: "User updated" });
      }
      setModalOpen(false);
      await load();
    } catch (e) {
      toast.fromError(e, "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function remove(u: AdminUser) {
    if (!confirm(`Delete ${u.username}? This cannot be undone.`)) return;
    try {
      await api.deleteUser(u.id);
      toast.push({ tone: "success", title: `Deleted ${u.username}` });
      await load();
    } catch (e) {
      toast.fromError(e, "Delete failed");
    }
  }

  async function toggleRole(u: AdminUser, roleId: number, has: boolean) {
    try {
      if (has) await api.unassignRole(u.id, roleId);
      else await api.assignRole(u.id, roleId);
      await load();
      if (u.username === me?.username) await refreshMe();
    } catch (e) {
      toast.fromError(e, "Role change failed");
    }
  }

  return (
    <div>
      <SectionTitle eyebrow="Admin · Directory" title="Users">
        {canWrite && (
          <Button onClick={openCreate}>
            <IconPlus width={16} height={16} /> New user
          </Button>
        )}
      </SectionTitle>

      {!canWrite && (
        <p className="mb-4 text-sm text-muted">
          You have read access. Create, edit, delete and role affordances are
          hidden because your roles don't include them.
        </p>
      )}

      {loading ? (
        <div className="flex items-center gap-2 py-10 text-muted">
          <Spinner /> loading…
        </div>
      ) : (
        <motion.div variants={listContainer} initial="hidden" animate="show" className="space-y-2.5">
          <AnimatePresence>
            {users.map((u) => {
              const isSelf = u.username === me?.username;
              const open = expanded === u.id;
              return (
                <motion.div key={u.id} variants={listItem} layout exit="exit">
                  <Panel className="overflow-hidden">
                    <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-start sm:justify-between">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-semibold">{u.username}</span>
                          {isSelf && <span className="stamp text-[10px] text-accent">you</span>}
                          <LevelBadge level={u.level} size="sm" />
                          <Chip tone="accent">{u.tenant_id}</Chip>
                          {u.acl_groups.map((g) => (
                            <Chip key={g}>{g}</Chip>
                          ))}
                        </div>
                        {u.email && (
                          <div className="mt-1 text-xs text-muted">{u.email}</div>
                        )}
                        {/* Roles */}
                        <div className="mt-3 flex flex-wrap items-center gap-1.5">
                          <span className="stamp text-[10px] text-faint">roles</span>
                          {u.roles.length === 0 && (
                            <span className="text-xs text-faint">none</span>
                          )}
                          {u.roles.map((r) => (
                            <Chip
                              key={r.id}
                              tone="ok"
                              onRemove={canWrite ? () => toggleRole(u, r.id, true) : undefined}
                            >
                              {r.name}
                            </Chip>
                          ))}
                          {canWrite && can("roles.read") && (
                            <RoleAdder
                              roles={roles.filter(
                                (r) => !u.roles.some((ur) => ur.id === r.id),
                              )}
                              onAdd={(rid) => toggleRole(u, rid, false)}
                            />
                          )}
                        </div>
                      </div>

                      <div className="flex shrink-0 items-center gap-1.5">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setExpanded(open ? null : u.id)}
                        >
                          <IconKey width={15} height={15} />
                          {u.permissions.length} effective
                        </Button>
                        {canWrite && (
                          <Button variant="outline" size="sm" onClick={() => openEdit(u)}>
                            <IconEdit width={15} height={15} />
                          </Button>
                        )}
                        {canDelete && !isSelf && (
                          <Button variant="danger" size="sm" onClick={() => remove(u)}>
                            <IconTrash width={15} height={15} />
                          </Button>
                        )}
                      </div>
                    </div>

                    {/* Effective permissions — the "what can this person do?" answer */}
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
                              effective permissions · union across roles
                            </div>
                            {u.permissions.length === 0 ? (
                              <p className="text-sm text-muted">
                                {u.level === "creator"
                                  ? "Creator — bypasses every permission check regardless of roles."
                                  : "No effective permissions. This account can do nothing in the panel."}
                              </p>
                            ) : (
                              <div className="flex flex-wrap gap-1.5">
                                {u.permissions.map((p) => (
                                  <Chip key={p} tone="accent">
                                    <code className="font-mono">{p}</code>
                                  </Chip>
                                ))}
                              </div>
                            )}
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
        title={editingId == null ? "New user" : `Edit ${draft.username}`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setModalOpen(false)}>
              Cancel
            </Button>
            <Button onClick={save} disabled={saving}>
              {saving ? <Spinner /> : editingId == null ? "Create" : "Save"}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Username">
            <Input
              value={draft.username}
              disabled={editingId != null}
              onChange={(e) => setDraft({ ...draft, username: e.target.value })}
            />
          </Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label={editingId == null ? "Password" : "New password"} hint={editingId == null ? undefined : "Leave blank to keep"}>
              <Input
                type="password"
                value={draft.password}
                onChange={(e) => setDraft({ ...draft, password: e.target.value })}
              />
            </Field>
            <Field label="Email" hint="Optional">
              <Input
                value={draft.email}
                onChange={(e) => setDraft({ ...draft, email: e.target.value })}
              />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Level" hint={isCreator ? undefined : "Only a creator can set admin/creator"}>
              <Select
                value={draft.level}
                onChange={(e) => setDraft({ ...draft, level: e.target.value as Level })}
              >
                {allowedLevels.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Tenant (ACL)">
              <Input
                value={draft.tenant_id}
                placeholder="default"
                onChange={(e) => setDraft({ ...draft, tenant_id: e.target.value })}
              />
            </Field>
          </div>
          <Field label="ACL groups" hint="Comma-separated. Controls document access, not features.">
            <Input
              value={draft.acl_groups}
              placeholder="billing, security"
              onChange={(e) => setDraft({ ...draft, acl_groups: e.target.value })}
            />
          </Field>
        </div>
      </Modal>
    </div>
  );
}

function RoleAdder({
  roles,
  onAdd,
}: {
  roles: Role[];
  onAdd: (roleId: number) => void;
}) {
  const [value, setValue] = useState("");
  const options = useMemo(() => roles, [roles]);
  if (options.length === 0) return null;
  return (
    <select
      value={value}
      onChange={(e) => {
        const id = Number(e.target.value);
        if (id) onAdd(id);
        setValue("");
      }}
      className="rounded-full border border-dashed border-line-strong bg-transparent px-2 py-0.5 text-xs text-muted hover:text-ink focus:outline-none"
    >
      <option value="">+ role</option>
      {options.map((r) => (
        <option key={r.id} value={r.id}>
          {r.name}
        </option>
      ))}
    </select>
  );
}
