"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import ConfirmDialog from "@/components/ConfirmDialog";

type MemoryItem = {
  id: number;
  area: string;
  category: string;
  content: string;
  importance: number;
  active: boolean;
  created_at: string | null;
  updated_at: string | null;
};

function formatDateTime(value?: string | null) {
  if (!value) return "–";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString("cs-CZ", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function MemoryPage() {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [q, setQ] = useState("");
  const [area, setArea] = useState<string>("all");
  const [category, setCategory] = useState<string>("all");
  const [includeInactive, setIncludeInactive] = useState(false);

  const [creating, setCreating] = useState(false);
  const [createForm, setCreateForm] = useState({
    area: "general",
    category: "context",
    content: "",
    importance: 5,
    active: true,
  });

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState({
    area: "",
    category: "",
    content: "",
    importance: 5,
    active: true,
  });

  const [deleteTarget, setDeleteTarget] = useState<MemoryItem | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (q.trim()) params.set("q", q.trim());
      if (area !== "all") params.set("area", area);
      if (category !== "all") params.set("category", category);
      if (includeInactive) params.set("include_inactive", "true");

      const res = await apiFetch(`/memories?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as MemoryItem[];
      setItems(Array.isArray(data) ? data : []);
    } catch {
      setError("Nepodařilo se načíst memory z backendu.");
    } finally {
      setLoading(false);
    }
  }, [q, area, category, includeInactive]);

  useEffect(() => {
    queueMicrotask(() => {
      void load().catch(() => {});
    });
  }, [load]);

  const areaOptions = useMemo(() => {
    const set = new Set<string>();
    for (const it of items) set.add(it.area);
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [items]);

  const categoryOptions = useMemo(() => {
    const set = new Set<string>();
    for (const it of items) set.add(it.category);
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [items]);

  async function createMemory(e: React.FormEvent) {
    e.preventDefault();
    const content = createForm.content.trim();
    if (!content) {
      setError("Vyplň obsah memory.");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const res = await apiFetch("/memory", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          area: createForm.area.trim() || "general",
          category: createForm.category.trim() || "context",
          content,
          importance: createForm.importance,
          active: createForm.active,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setCreateForm((f) => ({ ...f, content: "" }));
      await load();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se uložit memory.");
    } finally {
      setCreating(false);
    }
  }

  function startEdit(item: MemoryItem) {
    setEditingId(item.id);
    setEditForm({
      area: item.area,
      category: item.category,
      content: item.content,
      importance: item.importance,
      active: item.active,
    });
  }

  async function saveEdit() {
    if (editingId == null) return;
    const content = editForm.content.trim();
    if (!content) {
      setError("Obsah memory nesmí být prázdný.");
      return;
    }
    setError(null);
    try {
      const res = await apiFetch(`/memory/${editingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          area: editForm.area.trim() || "general",
          category: editForm.category.trim() || "context",
          content,
          importance: editForm.importance,
          active: editForm.active,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setEditingId(null);
      await load();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se upravit memory.");
    }
  }

  async function toggleActive(item: MemoryItem, next: boolean) {
    try {
      const res = await apiFetch(`/memory/${item.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ active: next }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await load();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se změnit stav memory.");
    }
  }

  async function confirmHardDelete() {
    if (!deleteTarget) return;
    try {
      const res = await apiFetch(`/memory/${deleteTarget.id}/hard`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await load();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se smazat memory.");
    } finally {
      setDeleteTarget(null);
    }
  }

  return (
    <main className="p-4 md:p-8 max-w-6xl mx-auto space-y-8 md:space-y-10">
      <header>
        <h1 className="text-2xl md:text-4xl font-bold">Memory</h1>
        <p className="text-zinc-400 mt-2">
          Long-term paměť pro AI. Nepleť si to s aktuálními databázovými fakty.
        </p>
      </header>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 text-red-400 rounded-xl px-4 py-3">
          {error}
        </div>
      )}

      <section className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 md:p-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="min-w-[240px] flex-1">
            <div className="text-sm text-zinc-400 mb-1">Search</div>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Hledej v area/category/obsahu…"
              className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2.5 outline-none focus:border-zinc-500"
            />
          </div>

          <div className="min-w-[180px]">
            <div className="text-sm text-zinc-400 mb-1">Area</div>
            <select
              value={area}
              onChange={(e) => setArea(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2.5 outline-none focus:border-zinc-500"
            >
              <option value="all">All</option>
              {areaOptions.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>
          </div>

          <div className="min-w-[180px]">
            <div className="text-sm text-zinc-400 mb-1">Category</div>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2.5 outline-none focus:border-zinc-500"
            >
              <option value="all">All</option>
              {categoryOptions.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-3 pt-7">
            <label className="flex items-center gap-2 text-sm text-zinc-300 select-none">
              <input
                type="checkbox"
                checked={includeInactive}
                onChange={(e) => setIncludeInactive(e.target.checked)}
                className="accent-indigo-500"
              />
              show inactive
            </label>
            <button
              type="button"
              onClick={load}
              disabled={loading}
              className="text-sm px-4 py-2 rounded-xl border border-zinc-800 hover:border-zinc-700 hover:bg-zinc-800 transition-colors disabled:opacity-50"
            >
              Obnovit
            </button>
          </div>
        </div>
      </section>

      <section className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 md:p-6">
        <h2 className="text-lg font-semibold mb-4">Přidat memory</h2>
        <form onSubmit={createMemory} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <div className="text-sm text-zinc-400 mb-1">Area</div>
              <input
                value={createForm.area}
                onChange={(e) =>
                  setCreateForm((f) => ({ ...f, area: e.target.value }))
                }
                className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2.5 outline-none focus:border-zinc-500"
              />
            </div>
            <div>
              <div className="text-sm text-zinc-400 mb-1">Category</div>
              <input
                value={createForm.category}
                onChange={(e) =>
                  setCreateForm((f) => ({ ...f, category: e.target.value }))
                }
                className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2.5 outline-none focus:border-zinc-500"
              />
            </div>
            <div>
              <div className="text-sm text-zinc-400 mb-1">
                Importance: {createForm.importance}/10
              </div>
              <input
                type="range"
                min={1}
                max={10}
                value={createForm.importance}
                onChange={(e) =>
                  setCreateForm((f) => ({
                    ...f,
                    importance: Number(e.target.value),
                  }))
                }
                className="w-full"
              />
              <label className="mt-2 flex items-center gap-2 text-sm text-zinc-300 select-none">
                <input
                  type="checkbox"
                  checked={createForm.active}
                  onChange={(e) =>
                    setCreateForm((f) => ({ ...f, active: e.target.checked }))
                  }
                  className="accent-indigo-500"
                />
                active
              </label>
            </div>
          </div>

          <div>
            <div className="text-sm text-zinc-400 mb-1">Content</div>
            <textarea
              value={createForm.content}
              onChange={(e) =>
                setCreateForm((f) => ({ ...f, content: e.target.value }))
              }
              rows={4}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2.5 outline-none focus:border-zinc-500 resize-y"
            />
          </div>

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={creating}
              className="bg-white text-black font-medium px-5 py-2.5 rounded-xl disabled:opacity-50 hover:bg-zinc-200 transition-colors"
            >
              {creating ? "Ukládám…" : "Uložit"}
            </button>
          </div>
        </form>
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Seznam</h2>
          <div className="text-sm text-zinc-500">
            {loading ? "Načítám…" : `${items.length} položek`}
          </div>
        </div>

        {items.map((it) => {
          const isEditing = editingId === it.id;
          return (
            <div
              key={it.id}
              className={`border rounded-2xl p-4 md:p-5 ${
                it.active
                  ? "bg-zinc-900 border-zinc-800"
                  : "bg-zinc-900/40 border-zinc-800/60"
              }`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
                      {it.area}
                    </span>
                    <span className="text-xs text-zinc-600">/</span>
                    <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
                      {it.category}
                    </span>
                    {!it.active && (
                      <span className="text-xs px-2 py-0.5 rounded-md border border-zinc-700 text-zinc-400">
                        inactive
                      </span>
                    )}
                    <span className="text-xs text-zinc-500">
                      Importance: {it.importance}/10
                    </span>
                  </div>

                  {!isEditing ? (
                    <p className="whitespace-pre-wrap leading-7 text-zinc-200 mt-3">
                      {it.content}
                    </p>
                  ) : (
                    <div className="mt-3 space-y-3">
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                        <input
                          value={editForm.area}
                          onChange={(e) =>
                            setEditForm((f) => ({ ...f, area: e.target.value }))
                          }
                          className="bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2.5 outline-none focus:border-zinc-500"
                        />
                        <input
                          value={editForm.category}
                          onChange={(e) =>
                            setEditForm((f) => ({
                              ...f,
                              category: e.target.value,
                            }))
                          }
                          className="bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2.5 outline-none focus:border-zinc-500"
                        />
                        <div>
                          <div className="text-xs text-zinc-400 mb-1">
                            Importance: {editForm.importance}/10
                          </div>
                          <input
                            type="range"
                            min={1}
                            max={10}
                            value={editForm.importance}
                            onChange={(e) =>
                              setEditForm((f) => ({
                                ...f,
                                importance: Number(e.target.value),
                              }))
                            }
                            className="w-full"
                          />
                          <label className="mt-2 flex items-center gap-2 text-sm text-zinc-300 select-none">
                            <input
                              type="checkbox"
                              checked={editForm.active}
                              onChange={(e) =>
                                setEditForm((f) => ({
                                  ...f,
                                  active: e.target.checked,
                                }))
                              }
                              className="accent-indigo-500"
                            />
                            active
                          </label>
                        </div>
                      </div>

                      <textarea
                        value={editForm.content}
                        onChange={(e) =>
                          setEditForm((f) => ({
                            ...f,
                            content: e.target.value,
                          }))
                        }
                        rows={4}
                        className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2.5 outline-none focus:border-zinc-500 resize-y"
                      />
                    </div>
                  )}

                  <div className="text-xs text-zinc-500 mt-3">
                    Created: {formatDateTime(it.created_at)} · Updated:{" "}
                    {formatDateTime(it.updated_at)}
                  </div>
                </div>

                <div className="shrink-0 flex flex-col gap-2">
                  {!isEditing ? (
                    <>
                      <button
                        type="button"
                        onClick={() => startEdit(it)}
                        className="text-sm px-4 py-2 rounded-xl border border-zinc-800 hover:border-zinc-700 hover:bg-zinc-800 transition-colors"
                      >
                        Edit
                      </button>
                      {it.active ? (
                        <button
                          type="button"
                          onClick={() => toggleActive(it, false)}
                          className="text-sm px-4 py-2 rounded-xl border border-zinc-800 hover:border-zinc-700 hover:bg-zinc-800 transition-colors"
                        >
                          Deactivate
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => toggleActive(it, true)}
                          className="text-sm px-4 py-2 rounded-xl border border-zinc-800 hover:border-zinc-700 hover:bg-zinc-800 transition-colors"
                        >
                          Activate
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => setDeleteTarget(it)}
                        className="text-sm px-4 py-2 rounded-xl bg-red-500/15 text-red-400 border border-red-500/30 hover:bg-red-500/25 transition-colors"
                      >
                        Delete
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={saveEdit}
                        className="text-sm px-4 py-2 rounded-xl bg-white text-black hover:bg-zinc-200 transition-colors"
                      >
                        Uložit
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingId(null)}
                        className="text-sm px-4 py-2 rounded-xl border border-zinc-800 hover:border-zinc-700 hover:bg-zinc-800 transition-colors"
                      >
                        Zrušit
                      </button>
                    </>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </section>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Smazat memory?"
        message={
          deleteTarget
            ? `Opravdu smazat memory #${deleteTarget.id}? Tohle je nevratné.`
            : ""
        }
        confirmLabel="Smazat"
        cancelLabel="Zrušit"
        danger={true}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={confirmHardDelete}
      />
    </main>
  );
}

