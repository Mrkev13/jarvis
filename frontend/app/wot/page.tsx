"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import ConfirmDialog from "@/components/ConfirmDialog";

type Resources = {
  credits?: number;
  gold?: number;
  bonds?: number;
  free_xp?: number;
};

type Grind = {
  id?: number;
  tank: string;
  xp_remaining: number;
  priority: string;
  status: string;
};

const RESOURCE_LABELS: Record<string, string> = {
  credits: "Credits",
  gold: "Gold",
  bonds: "Bonds",
  free_xp: "Free XP",
};

const RESOURCE_KEYS = ["credits", "gold", "bonds", "free_xp"] as const;
const PRIORITIES = ["low", "medium", "high"];
const STATUSES = ["active", "paused", "completed"];

function formatNumber(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return "-";
  }
  return new Intl.NumberFormat("cs-CZ").format(value);
}

function priorityClass(priority: string) {
  switch (priority.toLowerCase()) {
    case "high":
      return "bg-red-500/15 text-red-400 border-red-500/30";
    case "low":
      return "bg-blue-500/15 text-blue-400 border-blue-500/30";
    case "medium":
    default:
      return "bg-yellow-500/15 text-yellow-400 border-yellow-500/30";
  }
}

function statusClass(status: string) {
  switch (status.toLowerCase()) {
    case "completed":
      return "bg-green-500/15 text-green-400 border-green-500/30";
    case "paused":
      return "bg-zinc-500/15 text-zinc-400 border-zinc-500/30";
    case "active":
    default:
      return "bg-emerald-500/15 text-emerald-400 border-emerald-500/30";
  }
}

export default function WotPage() {
  const [resources, setResources] = useState<Resources>({});
  const [grinds, setGrinds] = useState<Grind[]>([]);

  const [showResourceForm, setShowResourceForm] = useState(false);
  const [resourceDraft, setResourceDraft] = useState<Resources>({});

  const [showGrindForm, setShowGrindForm] = useState(false);
  const [grindDraft, setGrindDraft] = useState<{
    tank: string;
    xp_remaining: string;
    priority: string;
    status: string;
  }>({
    tank: "",
    xp_remaining: "",
    priority: "medium",
    status: "active",
  });

  const [submitting, setSubmitting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deletingGrind, setDeletingGrind] = useState<Grind | null>(null);

  const loadData = useCallback(async () => {
    try {
      const [resRes, grindsRes] = await Promise.all([
        apiFetch("/wot/resources"),
        apiFetch("/wot/grinds"),
      ]);
      if (!resRes.ok || !grindsRes.ok) {
        throw new Error("Failed to load WoT data");
      }
      const resJson = (await resRes.json()) as Resources;
      const grindsJson = (await grindsRes.json()) as Grind[];
      setResources(resJson);
      setGrinds(grindsJson);
      setResourceDraft(resJson);
      setError(null);
    } catch {
      setError("Nepodařilo se načíst data z backendu.");
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void loadData().catch(() => {});
    });
  }, [loadData]);

  function openResourceForm() {
    setResourceDraft(resources);
    setShowResourceForm(true);
  }

  async function handleResourceSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting("resources");
    setError(null);
    try {
      const entries = RESOURCE_KEYS
        .filter((k) => resourceDraft[k] !== undefined && resourceDraft[k] !== null)
        .map((k) => ({ resource: k, amount: Number(resourceDraft[k]) }));

      await Promise.all(
        entries.map((body) =>
          apiFetch("/wot/resource", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }).then((r) => {
            if (!r.ok) throw new Error(`POST ${body.resource} failed`);
          }),
        ),
      );

      setShowResourceForm(false);
      await loadData();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se uložit resources.");
    } finally {
      setSubmitting(null);
    }
  }

  async function handleGrindSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!grindDraft.tank.trim() || grindDraft.xp_remaining === "") {
      setError("Vyplň název tanku a XP remaining.");
      return;
    }
    setSubmitting("grind");
    setError(null);
    try {
      const body = {
        tank: grindDraft.tank.trim(),
        xp_remaining: Number(grindDraft.xp_remaining),
        priority: grindDraft.priority,
        status: grindDraft.status,
      };
      const res = await apiFetch("/wot/grind", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error("Failed to save grind");

      setShowGrindForm(false);
      setGrindDraft({
        tank: "",
        xp_remaining: "",
        priority: "medium",
        status: "active",
      });
      await loadData();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se uložit grind.");
    } finally {
      setSubmitting(null);
    }
  }

  function editGrind(g: Grind) {
    setGrindDraft({
      tank: g.tank,
      xp_remaining: String(g.xp_remaining),
      priority: g.priority,
      status: g.status,
    });
    setShowGrindForm(true);
  }

  async function confirmDeleteGrind() {
    if (!deletingGrind || deletingGrind.id == null) return;
    try {
      const res = await apiFetch(`/wot/grind/${deletingGrind.id}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Failed to delete grind");
      await loadData();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se smazat grind.");
    } finally {
      setDeletingGrind(null);
    }
  }

  return (
    <main className="p-4 md:p-8 max-w-6xl mx-auto space-y-8 md:space-y-10">
      <header>
        <h1 className="text-2xl md:text-4xl font-bold">World of Tanks</h1>
        <p className="text-zinc-400 mt-2">
          Resources, grinds, statistics and progression.
        </p>
      </header>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 text-red-400 rounded-xl px-4 py-3">
          {error}
        </div>
      )}

      {/* ===== RESOURCES ===== */}
      <section id="resources">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-2xl font-semibold">Resources</h2>
          <button
            type="button"
            onClick={openResourceForm}
            className="bg-white text-black text-sm font-medium px-4 py-2 rounded-lg hover:bg-zinc-200 transition-colors"
          >
            Update resources
          </button>
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {RESOURCE_KEYS.map((key) => (
            <div
              key={key}
              className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5"
            >
              <div className="text-sm text-zinc-400">
                {RESOURCE_LABELS[key]}
              </div>
              <div className="text-2xl font-semibold mt-1">
                {formatNumber(resources[key])}
              </div>
            </div>
          ))}
        </div>

        {showResourceForm && (
          <form
            onSubmit={handleResourceSubmit}
            className="mt-4 bg-zinc-900 border border-zinc-800 rounded-2xl p-6"
          >
            <h3 className="text-lg font-semibold mb-4">Update resources</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {RESOURCE_KEYS.map((key) => (
                <div key={key}>
                  <label className="block text-sm text-zinc-400 mb-1">
                    {RESOURCE_LABELS[key]}
                  </label>
                  <input
                    type="number"
                    value={resourceDraft[key] ?? ""}
                    onChange={(e) =>
                      setResourceDraft((prev) => ({
                        ...prev,
                        [key]: e.target.value === "" ? undefined : Number(e.target.value),
                      }))
                    }
                    className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                    placeholder="0"
                  />
                </div>
              ))}
            </div>
            <div className="flex gap-3 mt-5">
              <button
                type="submit"
                disabled={submitting === "resources"}
                className="bg-white text-black font-medium px-5 py-2 rounded-lg disabled:opacity-50"
              >
                {submitting === "resources" ? "Ukládám..." : "Uložit"}
              </button>
              <button
                type="button"
                onClick={() => setShowResourceForm(false)}
                className="bg-zinc-800 text-white font-medium px-5 py-2 rounded-lg hover:bg-zinc-700"
              >
                Zrušit
              </button>
            </div>
          </form>
        )}
      </section>

      {/* ===== ACTIVE GRINDS ===== */}
      <section id="grinds">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-2xl font-semibold">Active grinds</h2>
          <button
            type="button"
            onClick={() => {
              setGrindDraft({
                tank: "",
                xp_remaining: "",
                priority: "medium",
                status: "active",
              });
              setShowGrindForm(true);
            }}
            className="bg-white text-black text-sm font-medium px-4 py-2 rounded-lg hover:bg-zinc-200 transition-colors"
          >
            Add grind
          </button>
        </div>

        {grinds.length === 0 ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8 text-center text-zinc-400">
            No active grinds yet.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {grinds.map((g) => (
              <div
                key={g.tank}
                className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 flex items-start justify-between gap-4"
              >
                <div className="flex-1 min-w-0">
                  <div className="text-lg font-semibold truncate">
                    {g.tank}
                  </div>
                  <div className="text-zinc-400 text-sm mt-1">
                    {formatNumber(g.xp_remaining)} XP remaining
                  </div>
                  <div className="flex gap-2 mt-3">
                    <span
                      className={`inline-flex text-xs font-medium px-2.5 py-1 rounded-md border ${priorityClass(
                        g.priority,
                      )}`}
                    >
                      {g.priority}
                    </span>
                    <span
                      className={`inline-flex text-xs font-medium px-2.5 py-1 rounded-md border ${statusClass(
                        g.status,
                      )}`}
                    >
                      {g.status}
                    </span>
                  </div>
                </div>
                <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 shrink-0">
                  <button
                    type="button"
                    onClick={() => editGrind(g)}
                    className="text-zinc-400 hover:text-white text-sm bg-zinc-800 hover:bg-zinc-700 px-3 py-1.5 rounded-md"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => setDeletingGrind(g)}
                    className="text-red-400 hover:text-white text-sm bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 px-3 py-1.5 rounded-md transition-colors"
                  >
                    🗑️
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {showGrindForm && (
          <form
            onSubmit={handleGrindSubmit}
            className="mt-4 bg-zinc-900 border border-zinc-800 rounded-2xl p-6"
          >
            <h3 className="text-lg font-semibold mb-4">
              {grindDraft.tank ? "Edit grind" : "Add grind"}
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="md:col-span-1">
                <label className="block text-sm text-zinc-400 mb-1">
                  Tank
                </label>
                <input
                  type="text"
                  value={grindDraft.tank}
                  onChange={(e) =>
                    setGrindDraft((p) => ({ ...p, tank: e.target.value }))
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                  placeholder="např. VZ.55"
                />
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1">
                  XP remaining
                </label>
                <input
                  type="number"
                  value={grindDraft.xp_remaining}
                  onChange={(e) =>
                    setGrindDraft((p) => ({ ...p, xp_remaining: e.target.value }))
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                  placeholder="0"
                />
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1">
                  Priority
                </label>
                <select
                  value={grindDraft.priority}
                  onChange={(e) =>
                    setGrindDraft((p) => ({ ...p, priority: e.target.value }))
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                >
                  {PRIORITIES.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1">
                  Status
                </label>
                <select
                  value={grindDraft.status}
                  onChange={(e) =>
                    setGrindDraft((p) => ({ ...p, status: e.target.value }))
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                >
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="flex gap-3 mt-5">
              <button
                type="submit"
                disabled={submitting === "grind"}
                className="bg-white text-black font-medium px-5 py-2 rounded-lg disabled:opacity-50"
              >
                {submitting === "grind" ? "Ukládám..." : "Uložit"}
              </button>
              <button
                type="button"
                onClick={() => setShowGrindForm(false)}
                className="bg-zinc-800 text-white font-medium px-5 py-2 rounded-lg hover:bg-zinc-700"
              >
                Zrušit
              </button>
            </div>
          </form>
        )}
      </section>

      {/* ===== PLACEHOLDER SECTIONS ===== */}
      <section id="statistics" className="opacity-60">
        <h2 className="text-2xl font-semibold mb-4">Statistics</h2>
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8 text-center text-zinc-400 border-dashed">
          Battles · WR · WN8 · DPG (coming soon)
        </div>
      </section>

      <section id="tanks" className="opacity-60">
        <h2 className="text-2xl font-semibold mb-4">Tanks</h2>
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8 text-center text-zinc-400 border-dashed">
          Garage tank list and details (coming soon)
        </div>
      </section>

      <section id="equipment" className="opacity-60">
        <h2 className="text-2xl font-semibold mb-4">Equipment</h2>
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8 text-center text-zinc-400 border-dashed">
          Equipment &amp; consumables (coming soon)
        </div>
      </section>

      <section id="sessions" className="opacity-60">
        <h2 className="text-2xl font-semibold mb-4">Sessions</h2>
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8 text-center text-zinc-400 border-dashed">
          Session history &amp; per-session stats (coming soon)
        </div>
      </section>

      <section id="progress-history" className="opacity-60">
        <h2 className="text-2xl font-semibold mb-4">Progress history</h2>
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8 text-center text-zinc-400 border-dashed">
          Resource progression over time &amp; charts (coming soon)
        </div>
      </section>

      <ConfirmDialog
        open={deletingGrind != null}
        title={`Smazat grind ${deletingGrind?.tank ?? ""}?`}
        message="Tato akce je nevratná. Grind bude odstraněn ze Standa Hubu."
        onConfirm={confirmDeleteGrind}
        onCancel={() => setDeletingGrind(null)}
      />
    </main>
  );
}
