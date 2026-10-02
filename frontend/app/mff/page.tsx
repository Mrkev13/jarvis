"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import ConfirmDialog from "@/components/ConfirmDialog";

const ROLE_OPTIONS = ["ABX", "ABL", "GBR", "World Boss", "PvP", "Dispatch", "Other"] as const;

type RoleOption = (typeof ROLE_OPTIONS)[number];

const TIER_OPTIONS = ["T1", "T2", "T2.5", "T3", "T4", "Transcendent"];
const PRIORITY_OPTIONS = ["high", "medium", "low"];
const STATUS_OPTIONS = ["built", "building", "planned", "inactive"];
const BUILD_BUCKET_OPTIONS = ["all", "100", "80-99", "50-79", "under-50"] as const;
type BuildBucket = (typeof BUILD_BUCKET_OPTIONS)[number];
const BUILD_BUCKET_LABELS: Record<BuildBucket, string> = {
  all: "Vše",
  "100": "100 %",
  "80-99": "80–99 %",
  "50-79": "50–79 %",
  "under-50": "< 50 %",
};

const SORT_OPTIONS = [
  { id: "default", label: "Výchozí (priorita → build asc → jméno)" },
  { id: "priority", label: "Priority" },
  { id: "build_asc", label: "Build completeness (sestupně)" },
  { id: "build_desc", label: "Build completeness (vzestupně)" },
  { id: "tier", label: "Tier" },
  { id: "name", label: "Jméno (A–Z)" },
] as const;
type SortId = (typeof SORT_OPTIONS)[number]["id"];

type MffSummary = {
  tracked_characters: number;
  t4_count: number;
  t3_count: number;
  priority_count: number;
  built_count: number;
  fully_built_t4_count: number;
  average_build_completeness: number;
};

type MffCharacterItem = {
  id: number;
  name: string;
  tier: string;
  level: number;
  uniform: string;
  ctp: string;
  artifact: string;
  priority: string;
  status: string;
  notes: string;
  role: string;
  team: string;
  uru_state: string;
  iso8_set: string;
  build_completeness: number;
  updated_at?: string | null;
  roles: string[];
  team_supports: string;
  uru_slots_total: number;
  uru_slots_filled: number;
  odin_blessings_count: number;
};

function tierClass(tier: string) {
  const t = tier.trim().toLowerCase();
  if (t.includes("t4") || t.includes("transcendent")) {
    return "bg-gradient-to-br from-amber-500 to-yellow-300 text-amber-950 border border-amber-500";
  }
  if (t.includes("t3")) {
    return "bg-gradient-to-br from-indigo-500 to-sky-500 text-white border border-indigo-400";
  }
  if (t.includes("t2.5") || t.includes("t25")) {
    return "bg-purple-900/60 border border-purple-700 text-purple-200";
  }
  if (t.includes("t2")) {
    return "bg-sky-900/60 border border-sky-700 text-sky-200";
  }
  return "bg-zinc-800 border border-zinc-700 text-zinc-200";
}

function priorityClass(priority: string) {
  const p = priority.trim().toLowerCase();
  if (p === "high") {
    return "px-2 py-0.5 text-xs rounded-full bg-red-950/80 border border-red-800 text-red-300";
  }
  if (p === "medium") {
    return "px-2 py-0.5 text-xs rounded-full bg-yellow-950/70 border border-yellow-800 text-yellow-300";
  }
  if (p === "low") {
    return "px-2 py-0.5 text-xs rounded-full bg-sky-950/70 border border-sky-800 text-sky-300";
  }
  return "px-2 py-0.5 text-xs rounded-full bg-zinc-800 border border-zinc-700 text-zinc-300";
}

function statusClass(status: string) {
  const s = status.trim().toLowerCase();
  if (s === "built") {
    return "px-2 py-0.5 text-xs rounded-full bg-green-500/15 border border-green-500/40 text-green-300 font-semibold";
  }
  if (s === "building") {
    return "px-2 py-0.5 text-xs rounded-full bg-indigo-950/70 border border-indigo-800 text-indigo-300";
  }
  if (s === "planned") {
    return "px-2 py-0.5 text-xs rounded-full bg-yellow-950/70 border border-yellow-800 text-yellow-300";
  }
  if (s === "inactive") {
    return "px-2 py-0.5 text-xs rounded-full bg-zinc-800 border border-zinc-700 text-zinc-400";
  }
  return "px-2 py-0.5 text-xs rounded-full bg-zinc-800 border border-zinc-700 text-zinc-300";
}

function roleBadgeClass(role: string) {
  const r = role.trim();
  const map: Record<string, string> = {
    ABX: "bg-pink-500/15 border border-pink-500/40 text-pink-300",
    ABL: "bg-purple-500/15 border border-purple-500/40 text-purple-300",
    GBR: "bg-emerald-500/15 border border-emerald-500/40 text-emerald-300",
    "World Boss": "bg-indigo-500/15 border border-indigo-500/40 text-indigo-300",
    PvP: "bg-red-500/15 border border-red-500/40 text-red-300",
    Dispatch: "bg-sky-500/15 border border-sky-500/40 text-sky-300",
    Other: "bg-zinc-700/60 border border-zinc-600 text-zinc-300",
  };
  return map[r] ?? "bg-zinc-800 border border-zinc-700 text-zinc-300";
}

function isTierT4(tier: string | undefined | null) {
  const t = (tier || "").trim().toLowerCase().replace(/\s+/g, "");
  return t === "t4" || t === "transcendent" || t === "tier4";
}

function computeBuildCompleteness(input: {
  tier: string;
  level: number;
  uniform: string;
  ctp: string;
  artifact: string;
  uru_slots_total: number;
  uru_slots_filled: number;
  iso8_set: string;
  team_supports: string;
}): number {
  let completed = 0;
  if (isTierT4(input.tier)) completed++;
  if ((input.level || 0) >= 80) completed++;
  if ((input.uniform || "").trim()) completed++;
  if ((input.ctp || "").trim()) completed++;
  if ((input.artifact || "").trim()) completed++;
  const ut = Number(input.uru_slots_total) || 0;
  const uf = Number(input.uru_slots_filled) || 0;
  if (ut > 0 && uf >= ut) completed++;
  if ((input.iso8_set || "").trim()) completed++;
  if ((input.team_supports || "").trim()) completed++;
  return Math.round((completed / 8) * 100);
}

function buildBucketMatches(bc: number, bucket: BuildBucket) {
  switch (bucket) {
    case "all":
      return true;
    case "100":
      return bc >= 100;
    case "80-99":
      return bc >= 80 && bc < 100;
    case "50-79":
      return bc >= 50 && bc < 80;
    case "under-50":
      return bc < 50;
  }
}

function progressColor(bc: number) {
  if (bc >= 100) return "bg-emerald-500";
  if (bc >= 80) return "bg-lime-500";
  if (bc >= 50) return "bg-amber-500";
  return "bg-red-500";
}

export default function MffPage() {
  const [summary, setSummary] = useState<MffSummary | null>(null);
  const [characters, setCharacters] = useState<MffCharacterItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [deletingChar, setDeletingChar] = useState<MffCharacterItem | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});

  const [name, setName] = useState("");
  const [tier, setTier] = useState("T3");
  const [level, setLevel] = useState("80");
  const [uniform, setUniform] = useState("");
  const [ctp, setCtp] = useState("");
  const [artifact, setArtifact] = useState("");
  const [teamSupports, setTeamSupports] = useState("");
  const [roles, setRoles] = useState<RoleOption[]>([]);
  const [uruSlotsFilled, setUruSlotsFilled] = useState("0");
  const [uruSlotsTotal, setUruSlotsTotal] = useState("20");
  const [odinBlessings, setOdinBlessings] = useState("0");
  const [iso8Set, setIso8Set] = useState("");
  const [priority, setPriority] = useState("medium");
  const [status, setStatus] = useState("planned");
  const [notes, setNotes] = useState("");

  const [filterTier, setFilterTier] = useState<string>("all");
  const [filterPriority, setFilterPriority] = useState<string>("all");
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [filterRoles, setFilterRoles] = useState<string[]>([]);
  const [filterBuild, setFilterBuild] = useState<BuildBucket>("all");
  const [sortMode, setSortMode] = useState<SortId>("default");

  const liveBuild = useMemo(
    () =>
      computeBuildCompleteness({
        tier,
        level: Math.max(1, parseInt(level || "0", 10) || 0),
        uniform,
        ctp,
        artifact,
        uru_slots_total: Math.max(0, parseInt(uruSlotsTotal || "0", 10) || 0),
        uru_slots_filled: Math.max(0, parseInt(uruSlotsFilled || "0", 10) || 0),
        iso8_set: iso8Set,
        team_supports: teamSupports,
      }),
    [tier, level, uniform, ctp, artifact, uruSlotsTotal, uruSlotsFilled, iso8Set, teamSupports],
  );

  const availableTierFilters = useMemo(() => {
    const tiers = new Set<string>();
    for (const c of characters) if (c.tier) tiers.add(c.tier);
    return ["all", ...Array.from(tiers).sort()];
  }, [characters]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [sumRes, charsRes] = await Promise.all([
        apiFetch("/mff/summary"),
        apiFetch("/mff/characters"),
      ]);
      if (!sumRes.ok || !charsRes.ok) throw new Error();
      setSummary((await sumRes.json()) as MffSummary);
      const raw = (await charsRes.json()) as MffCharacterItem[];
      const normalized: MffCharacterItem[] = raw.map((c) => ({
        ...c,
        roles: Array.isArray(c.roles) ? c.roles : [],
        team_supports: c.team_supports || c.team || "",
        uru_slots_total: Number(c.uru_slots_total) || 20,
        uru_slots_filled: Number(c.uru_slots_filled) || 0,
        odin_blessings_count: Number(c.odin_blessings_count) || 0,
        build_completeness: Math.max(0, Math.min(100, Number(c.build_completeness) || 0)),
      }));
      setCharacters(normalized);
    } catch {
      setError("Nepodařilo se načíst MFF data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void loadData().catch(() => {});
    });
  }, [loadData]);

  function toggleRole(r: RoleOption) {
    setRoles((prev) => (prev.includes(r) ? prev.filter((x) => x !== r) : [...prev, r]));
  }

  function toggleFilterRole(r: string) {
    setFilterRoles((prev) => (prev.includes(r) ? prev.filter((x) => x !== r) : [...prev, r]));
  }

  function resetForm() {
    setName("");
    setTier("T3");
    setLevel("80");
    setUniform("");
    setCtp("");
    setArtifact("");
    setRoles([]);
    setTeamSupports("");
    setUruSlotsFilled("0");
    setUruSlotsTotal("20");
    setOdinBlessings("0");
    setIso8Set("");
    setPriority("medium");
    setStatus("planned");
    setNotes("");
    setFormErrors({});
  }

  function validate(): boolean {
    const errs: Record<string, string> = {};
    if (!name.trim()) errs.name = "Zadej jméno postavy.";
    const lv = parseInt(level || "0", 10);
    if (!isFinite(lv) || lv < 1) errs.level = "Level musí být alespoň 1.";
    const ut = parseInt(uruSlotsTotal || "0", 10);
    const uf = parseInt(uruSlotsFilled || "0", 10);
    if (!isFinite(ut) || ut < 0) errs.uruSlotsTotal = "Uru slots total musí být >= 0.";
    if (!isFinite(uf) || uf < 0) errs.uruSlotsFilled = "Uru slots filled musí být >= 0.";
    if (isFinite(ut) && isFinite(uf) && uf > ut) {
      errs.uruSlotsFilled = "Filled nesmí být větší než total.";
    }
    const ob = parseInt(odinBlessings || "0", 10);
    if (!isFinite(ob) || ob < 0) errs.odinBlessings = "Odin's Blessings musí být >= 0.";
    setFormErrors(errs);
    return Object.keys(errs).length === 0;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!validate()) {
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const levelNum = parseInt(level, 10);
      const ut = parseInt(uruSlotsTotal || "20", 10) || 0;
      const uf = parseInt(uruSlotsFilled || "0", 10) || 0;
      const ob = parseInt(odinBlessings || "0", 10) || 0;
      const payload = {
        name: name.trim(),
        tier,
        level: isFinite(levelNum) ? Math.max(1, levelNum) : 80,
        uniform: uniform.trim(),
        ctp: ctp.trim(),
        artifact: artifact.trim(),
        priority,
        status,
        notes: notes.trim(),
        role: roles.join(" · "),
        team: teamSupports.trim(),
        uru_state: ut > 0 ? `${uf}/${ut}` : "",
        iso8_set: iso8Set.trim(),
        build_completeness: liveBuild,
        roles,
        team_supports: teamSupports.trim(),
        uru_slots_total: ut,
        uru_slots_filled: uf,
        odin_blessings_count: ob,
      };
      const res = await apiFetch("/mff/character", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        let msg = "Nepodařilo se uložit postavu.";
        try {
          const err = await res.json();
          if (err?.detail) msg = String(err.detail);
        } catch {
          // ignore
        }
        throw new Error(msg);
      }
      resetForm();
      setShowForm(false);
      await loadData();
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Nepodařilo se uložit postavu.");
    } finally {
      setSubmitting(false);
    }
  }

  async function confirmDeleteChar() {
    if (!deletingChar) return;
    try {
      const res = await apiFetch(`/mff/character/${deletingChar.id}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Failed to delete character");
      await loadData();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se smazat postavu.");
    } finally {
      setDeletingChar(null);
    }
  }

  const filteredAndSorted = useMemo(() => {
    let list = [...characters];
    if (filterTier !== "all") {
      list = list.filter((c) => c.tier === filterTier);
    }
    if (filterPriority !== "all") {
      list = list.filter((c) => (c.priority || "").toLowerCase() === filterPriority);
    }
    if (filterStatus !== "all") {
      list = list.filter((c) => (c.status || "").toLowerCase() === filterStatus);
    }
    if (filterRoles.length > 0) {
      list = list.filter((c) => {
        const charRoles = Array.isArray(c.roles) ? c.roles.map((r) => String(r)) : [];
        return filterRoles.every((r) => charRoles.includes(r));
      });
    }
    if (filterBuild !== "all") {
      list = list.filter((c) => buildBucketMatches(c.build_completeness, filterBuild));
    }
    const prioOrder: Record<string, number> = { high: 0, medium: 1, low: 2 };
    const tierOrder: Record<string, number> = {
      transcendent: 6,
      t4: 5,
      t3: 4,
      "t2.5": 3,
      t25: 3,
      t2: 2,
      t1: 1,
    };
    list.sort((a, b) => {
      switch (sortMode) {
        case "priority": {
          const pa = prioOrder[(a.priority || "").toLowerCase()] ?? 9;
          const pb = prioOrder[(b.priority || "").toLowerCase()] ?? 9;
          if (pa !== pb) return pa - pb;
          return a.name.localeCompare(b.name);
        }
        case "build_asc": {
          return a.build_completeness - b.build_completeness || a.name.localeCompare(b.name);
        }
        case "build_desc": {
          return b.build_completeness - a.build_completeness || a.name.localeCompare(b.name);
        }
        case "tier": {
          const ta = tierOrder[(a.tier || "").toLowerCase().replace(/\s+/g, "")] ?? 0;
          const tb = tierOrder[(b.tier || "").toLowerCase().replace(/\s+/g, "")] ?? 0;
          if (tb !== ta) return tb - ta;
          return a.name.localeCompare(b.name);
        }
        case "name": {
          return a.name.localeCompare(b.name);
        }
        case "default":
        default: {
          const pa = prioOrder[(a.priority || "").toLowerCase()] ?? 9;
          const pb = prioOrder[(b.priority || "").toLowerCase()] ?? 9;
          if (pa !== pb) return pa - pb;
          if (a.build_completeness !== b.build_completeness) {
            return a.build_completeness - b.build_completeness;
          }
          return a.name.localeCompare(b.name);
        }
      }
    });
    return list;
  }, [characters, filterTier, filterPriority, filterStatus, filterRoles, filterBuild, sortMode]);

  return (
    <main className="p-4 md:p-8 max-w-6xl mx-auto">
      <header className="mb-6 md:mb-8">
        <h1 className="text-2xl md:text-4xl font-bold">Marvel Future Fight</h1>
        <p className="text-zinc-400 mt-2">Sledování postav, CTP, artifactů a upgrade plánů.</p>
      </header>

      {error && (
        <div className="mb-6 bg-red-950/50 border border-red-900 text-red-200 rounded-xl px-4 py-3">
          {error}
        </div>
      )}

      <section className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 mb-8">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-4">
          <h2 className="text-xl font-semibold">Summary</h2>
          <div className="flex items-center gap-2">
            {!showForm ? (
              <button
                type="button"
                onClick={() => {
                  resetForm();
                  setShowForm(true);
                }}
                className="bg-white text-black font-medium px-5 py-2.5 rounded-xl hover:bg-zinc-200 transition-colors"
              >
                + Add character
              </button>
            ) : (
              <button
                type="button"
                onClick={() => {
                  setShowForm(false);
                  resetForm();
                }}
                className="text-sm text-zinc-400 hover:text-zinc-200"
              >
                Zavřít
              </button>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-7 gap-3 mb-5">
          <div className="bg-zinc-800/60 border border-zinc-800 rounded-xl p-4">
            <div className="text-sm text-zinc-400 mb-1">Tracked</div>
            <div className="text-2xl font-bold">
              {loading && !summary ? "…" : summary?.tracked_characters ?? 0}
            </div>
          </div>
          <div className="bg-zinc-800/60 border border-zinc-800 rounded-xl p-4">
            <div className="text-sm text-zinc-400 mb-1">T4</div>
            <div className="text-2xl font-bold text-amber-300">
              {loading && !summary ? "…" : summary?.t4_count ?? 0}
            </div>
          </div>
          <div className="bg-zinc-800/60 border border-zinc-800 rounded-xl p-4">
            <div className="text-sm text-zinc-400 mb-1">T3</div>
            <div className="text-2xl font-bold text-indigo-300">
              {loading && !summary ? "…" : summary?.t3_count ?? 0}
            </div>
          </div>
          <div className="bg-zinc-800/60 border border-zinc-800 rounded-xl p-4">
            <div className="text-sm text-zinc-400 mb-1">Priority builds</div>
            <div className="text-2xl font-bold text-red-300">
              {loading && !summary ? "…" : summary?.priority_count ?? 0}
            </div>
          </div>
          <div className="bg-zinc-800/60 border border-zinc-800 rounded-xl p-4">
            <div className="text-sm text-zinc-400 mb-1">Built</div>
            <div className="text-2xl font-bold text-green-300">
              {loading && !summary ? "…" : summary?.built_count ?? 0}
            </div>
          </div>
          <div className="bg-zinc-800/60 border border-zinc-800 rounded-xl p-4">
            <div className="text-sm text-zinc-400 mb-1">Fully built T4</div>
            <div className="text-2xl font-bold text-emerald-300">
              {loading && !summary ? "…" : summary?.fully_built_t4_count ?? 0}
            </div>
          </div>
          <div className="bg-zinc-800/60 border border-zinc-800 rounded-xl p-4">
            <div className="text-sm text-zinc-400 mb-1">Avg build</div>
            <div className="text-2xl font-bold text-zinc-200">
              {loading && !summary ? "…" : `${summary?.average_build_completeness ?? 0} %`}
            </div>
          </div>
        </div>

        {showForm && (
          <form onSubmit={handleSubmit} className="border-t border-zinc-800 pt-5">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">
                  Name <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="např. Black Bolt"
                  className={`w-full bg-zinc-800 border rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500 ${
                    formErrors.name ? "border-red-600" : "border-zinc-700"
                  }`}
                />
                {formErrors.name && (
                  <div className="text-xs text-red-400 mt-1">{formErrors.name}</div>
                )}
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">Tier</label>
                <select
                  value={tier}
                  onChange={(e) => setTier(e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                >
                  {TIER_OPTIONS.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">Level</label>
                <input
                  type="number"
                  min={1}
                  max={80}
                  value={level}
                  onChange={(e) => setLevel(e.target.value)}
                  className={`w-full bg-zinc-800 border rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500 ${
                    formErrors.level ? "border-red-600" : "border-zinc-700"
                  }`}
                />
                {formErrors.level && (
                  <div className="text-xs text-red-400 mt-1">{formErrors.level}</div>
                )}
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">Uniform</label>
                <input
                  type="text"
                  value={uniform}
                  onChange={(e) => setUniform(e.target.value)}
                  placeholder="např. Hellfire Club"
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                />
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">CTP</label>
                <input
                  type="text"
                  value={ctp}
                  onChange={(e) => setCtp(e.target.value)}
                  placeholder="např. Rage / Regeneration / -"
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                />
              </div>
              <div className="md:col-span-2 lg:col-span-3">
                <label className="block text-sm text-zinc-400 mb-1.5">Roles</label>
                <div className="flex flex-wrap gap-2 p-2 bg-zinc-800/60 border border-zinc-700 rounded-xl">
                  {ROLE_OPTIONS.map((r) => {
                    const active = roles.includes(r);
                    return (
                      <button
                        type="button"
                        key={r}
                        onClick={() => toggleRole(r)}
                        className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                          active
                            ? roleBadgeClass(r)
                            : "bg-zinc-900/40 border-zinc-700 text-zinc-400 hover:text-zinc-200"
                        }`}
                      >
                        {r}
                      </button>
                    );
                  })}
                </div>
              </div>
              <div className="md:col-span-2 lg:col-span-3">
                <label className="block text-sm text-zinc-400 mb-1.5">Team / supports</label>
                <input
                  type="text"
                  value={teamSupports}
                  onChange={(e) => setTeamSupports(e.target.value)}
                  placeholder="např. White Fox + Shuri"
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                />
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">Uru slots filled</label>
                <input
                  type="number"
                  min={0}
                  value={uruSlotsFilled}
                  onChange={(e) => setUruSlotsFilled(e.target.value)}
                  className={`w-full bg-zinc-800 border rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500 ${
                    formErrors.uruSlotsFilled ? "border-red-600" : "border-zinc-700"
                  }`}
                />
                {formErrors.uruSlotsFilled && (
                  <div className="text-xs text-red-400 mt-1">{formErrors.uruSlotsFilled}</div>
                )}
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">Uru slots total</label>
                <input
                  type="number"
                  min={0}
                  value={uruSlotsTotal}
                  onChange={(e) => setUruSlotsTotal(e.target.value)}
                  className={`w-full bg-zinc-800 border rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500 ${
                    formErrors.uruSlotsTotal ? "border-red-600" : "border-zinc-700"
                  }`}
                />
                {formErrors.uruSlotsTotal && (
                  <div className="text-xs text-red-400 mt-1">{formErrors.uruSlotsTotal}</div>
                )}
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">
                  Odin&apos;s Blessings
                </label>
                <input
                  type="number"
                  min={0}
                  value={odinBlessings}
                  onChange={(e) => setOdinBlessings(e.target.value)}
                  className={`w-full bg-zinc-800 border rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500 ${
                    formErrors.odinBlessings ? "border-red-600" : "border-zinc-700"
                  }`}
                />
                {formErrors.odinBlessings && (
                  <div className="text-xs text-red-400 mt-1">{formErrors.odinBlessings}</div>
                )}
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">ISO-8 set</label>
                <input
                  type="text"
                  value={iso8Set}
                  onChange={(e) => setIso8Set(e.target.value)}
                  placeholder="např. Power of Angry Hulk"
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                />
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">Artifact</label>
                <input
                  type="text"
                  value={artifact}
                  onChange={(e) => setArtifact(e.target.value)}
                  placeholder="např. Arachne 6*"
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                />
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">Priority</label>
                <select
                  value={priority}
                  onChange={(e) => setPriority(e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                >
                  {PRIORITY_OPTIONS.map((p) => (
                    <option key={p} value={p}>
                      {p[0].toUpperCase() + p.slice(1)}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1.5">Status</label>
                <select
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none focus:border-zinc-500"
                >
                  {STATUS_OPTIONS.map((s) => (
                    <option key={s} value={s}>
                      {s[0].toUpperCase() + s.slice(1)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="md:col-span-2 lg:col-span-3">
                <label className="block text-sm text-zinc-400 mb-1.5">
                  Build completeness <span className="text-zinc-500">(automatický)</span>
                </label>
                <div className="p-3 bg-zinc-800 border border-zinc-700 rounded-xl flex items-center justify-between gap-3">
                  <div className="flex-1">
                    <div className="h-2 bg-zinc-900 rounded-full overflow-hidden">
                      <div
                        className={`h-full ${progressColor(liveBuild)}`}
                        style={{ width: `${liveBuild}%` }}
                      />
                    </div>
                  </div>
                  <div className="text-sm font-semibold min-w-[56px] text-right">
                    {liveBuild} %
                  </div>
                </div>
                <div className="text-[11px] text-zinc-500 mt-1">
                  Sledovaných 8 komponent: T4, Level 80, Uniform, CTP, Artifact, Uru plné,
                  ISO-8 set, Team supports.
                </div>
              </div>
              <div className="md:col-span-2 lg:col-span-3">
                <label className="block text-sm text-zinc-400 mb-1.5">Notes</label>
                <textarea
                  rows={2}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Poznámky k buildovi…"
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-2.5 outline-none resize-none focus:border-zinc-500"
                />
              </div>
            </div>

            <div className="mt-4 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setShowForm(false);
                  resetForm();
                }}
                className="px-4 py-2.5 rounded-xl border border-zinc-800 text-zinc-300 hover:bg-zinc-800 transition-colors"
              >
                Storno
              </button>
              <button
                type="submit"
                disabled={submitting || loading}
                className="bg-white text-black font-medium px-5 py-2.5 rounded-xl disabled:opacity-50 hover:bg-zinc-200 transition-colors"
              >
                {submitting ? "Ukládám…" : "Uložit"}
              </button>
            </div>
          </form>
        )}
      </section>

      <section className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 mb-6">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-3">
          <h2 className="text-lg font-semibold">Filtry &amp; řazení</h2>
          <button
            type="button"
            onClick={() => setShowFilters((s) => !s)}
            className="text-sm px-3 py-1.5 rounded-xl border border-zinc-700 text-zinc-300 hover:bg-zinc-800 transition-colors self-start"
          >
            {showFilters ? "Skrýt filtry" : "Zobrazit filtry"}
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
          <div>
            <label className="block text-xs text-zinc-400 mb-1.5">Řazení</label>
            <select
              value={sortMode}
              onChange={(e) => setSortMode(e.target.value as SortId)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2 text-sm outline-none focus:border-zinc-500"
            >
              {SORT_OPTIONS.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-zinc-400 mb-1.5">Tier</label>
            <select
              value={filterTier}
              onChange={(e) => setFilterTier(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2 text-sm outline-none focus:border-zinc-500"
            >
              <option value="all">Vše</option>
              {availableTierFilters
                .filter((t) => t !== "all")
                .map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-zinc-400 mb-1.5">Priority</label>
            <select
              value={filterPriority}
              onChange={(e) => setFilterPriority(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2 text-sm outline-none focus:border-zinc-500"
            >
              <option value="all">Vše</option>
              {PRIORITY_OPTIONS.map((p) => (
                <option key={p} value={p}>
                  {p[0].toUpperCase() + p.slice(1)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-zinc-400 mb-1.5">Status</label>
            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2 text-sm outline-none focus:border-zinc-500"
            >
              <option value="all">Vše</option>
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s[0].toUpperCase() + s.slice(1)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-zinc-400 mb-1.5">Build completeness</label>
            <select
              value={filterBuild}
              onChange={(e) => setFilterBuild(e.target.value as BuildBucket)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2 text-sm outline-none focus:border-zinc-500"
            >
              {BUILD_BUCKET_OPTIONS.map((b) => (
                <option key={b} value={b}>
                  {BUILD_BUCKET_LABELS[b]}
                </option>
              ))}
            </select>
          </div>
        </div>

        {showFilters && (
          <div className="mt-4 pt-4 border-t border-zinc-800">
            <label className="block text-xs text-zinc-400 mb-1.5">
              Role <span className="text-zinc-500">(zobrazit postavy, které mají VŠECHNY vybrané role)</span>
            </label>
            <div className="flex flex-wrap gap-2 p-2 bg-zinc-800/60 border border-zinc-700 rounded-xl">
              {ROLE_OPTIONS.map((r) => {
                const active = filterRoles.includes(r);
                return (
                  <button
                    type="button"
                    key={r}
                    onClick={() => toggleFilterRole(r)}
                    className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                      active
                        ? roleBadgeClass(r)
                        : "bg-zinc-900/40 border-zinc-700 text-zinc-400 hover:text-zinc-200"
                    }`}
                  >
                    {r}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </section>

      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold">Characters</h2>
          <div className="text-sm text-zinc-400">
            {filteredAndSorted.length} / {characters.length}
          </div>
        </div>

        {loading && characters.length === 0 ? (
          <div className="text-zinc-500 bg-zinc-900 border border-zinc-800 rounded-2xl p-6">
            Načítám…
          </div>
        ) : filteredAndSorted.length === 0 ? (
          <div className="text-zinc-400 bg-zinc-900 border border-zinc-800 rounded-2xl p-6">
            {characters.length === 0
              ? "Zatím žádné sledované postavy. Přidej první!"
              : "Žádné postavy neodpovídají aktuálním filtrům."}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {filteredAndSorted.map((c) => {
              const bc = Math.max(0, Math.min(100, Number(c.build_completeness) || 0));
              const tierStr = (c.tier || "").trim() || "—";
              const levelStr = c.level != null ? `Lv. ${c.level}` : "";
              const uruTotal = Number(c.uru_slots_total) || 0;
              const uruFilled = Number(c.uru_slots_filled) || 0;
              const ob = Number(c.odin_blessings_count) || 0;
              const teamStr = c.team_supports || c.team || "";
              return (
                <div
                  key={c.id}
                  className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 hover:border-zinc-700 transition-colors"
                >
                  <div className="flex items-start justify-between gap-3 mb-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span
                          className={`px-2.5 py-1 text-xs rounded-lg font-semibold ${tierClass(
                            c.tier,
                          )}`}
                        >
                          {tierStr}
                        </span>
                        <span className="text-xs text-zinc-400">{levelStr}</span>
                      </div>
                      <h3 className="text-lg font-semibold break-words mt-1">{c.name}</h3>
                      {c.uniform && (
                        <p className="text-xs text-zinc-400 mt-0.5 break-words">
                          Uniform: <span className="text-zinc-300">{c.uniform}</span>
                        </p>
                      )}
                    </div>
                    <div className="flex flex-col items-end gap-1.5 shrink-0">
                      <button
                        type="button"
                        onClick={() => setDeletingChar(c)}
                        className="text-red-400 hover:text-white text-xs bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 px-2 py-0.5 rounded transition-colors"
                        aria-label={`Smazat ${c.name}`}
                      >
                        🗑️
                      </button>
                    </div>
                  </div>

                  {(c.roles && c.roles.length > 0) || c.role ? (
                    <div className="flex flex-wrap gap-1.5 mb-3">
                      {(Array.isArray(c.roles) && c.roles.length > 0
                        ? c.roles
                        : c.role
                          ? [c.role]
                          : []
                      ).map((r, i) => (
                        <span
                          key={`${r}-${i}`}
                          className={`px-2 py-0.5 text-xs rounded-full border ${roleBadgeClass(String(r))}`}
                        >
                          {String(r)}
                        </span>
                      ))}
                    </div>
                  ) : null}

                  <div className="space-y-1.5 mb-3 text-sm">
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                      {c.ctp && (
                        <div className="min-w-0">
                          <span className="text-zinc-500 text-xs">CTP: </span>
                          <span className="text-purple-300 break-words">{c.ctp}</span>
                        </div>
                      )}
                      {c.artifact && (
                        <div className="min-w-0">
                          <span className="text-zinc-500 text-xs">Artifact: </span>
                          <span className="text-amber-300 break-words">{c.artifact}</span>
                        </div>
                      )}
                      {c.iso8_set && (
                        <div className="min-w-0">
                          <span className="text-zinc-500 text-xs">ISO-8: </span>
                          <span className="text-zinc-200 break-words">{c.iso8_set}</span>
                        </div>
                      )}
                      {teamStr && (
                        <div className="min-w-0">
                          <span className="text-zinc-500 text-xs">Team: </span>
                          <span className="text-zinc-200 break-words">{teamStr}</span>
                        </div>
                      )}
                    </div>
                    {(uruTotal > 0 || ob > 0 || c.uru_state) && (
                      <div className="text-xs text-zinc-400">
                        {uruTotal > 0 || c.uru_state ? (
                          <span>
                            Uru{" "}
                            <span className="text-zinc-200">
                              {uruTotal > 0
                                ? `${uruFilled} / ${uruTotal}`
                                : c.uru_state}
                            </span>
                          </span>
                        ) : null}
                        {ob > 0 ? (
                          <span className="ml-2">
                            · <span className="text-zinc-200">{ob} OB</span>
                          </span>
                        ) : null}
                      </div>
                    )}
                  </div>

                  <div className="mb-3">
                    <div className="flex items-center justify-between text-xs mb-1.5">
                      <span className="text-zinc-400">Build completeness</span>
                      <span className="font-semibold text-zinc-200">{bc} %</span>
                    </div>
                    <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
                      <div
                        className={`h-full ${progressColor(bc)} transition-all`}
                        style={{ width: `${bc}%` }}
                      />
                    </div>
                    {bc >= 100 && (c.status || "").toLowerCase() !== "built" && (
                      <div className="text-[11px] text-emerald-400 mt-1">
                        100 % Complete – doporučený status Built.
                      </div>
                    )}
                  </div>

                  <div className="flex flex-wrap gap-2 mb-3">
                    <span className={priorityClass(c.priority)}>
                      Priority: {c.priority}
                    </span>
                    <span className={statusClass(c.status)}>{c.status}</span>
                    {bc >= 100 && (
                      <span className="px-2 py-0.5 text-xs rounded-full bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 font-semibold">
                        100 % Complete
                      </span>
                    )}
                  </div>

                  {c.notes && (
                    <div className="border-t border-zinc-800 pt-3">
                      <div className="text-[11px] uppercase tracking-wider text-zinc-500 font-semibold mb-1">
                        Build notes
                      </div>
                      <p className="text-xs text-zinc-400 leading-relaxed whitespace-pre-wrap break-words">
                        {c.notes}
                      </p>
                    </div>
                  )}

                  {c.updated_at && (
                    <div className="text-[11px] text-zinc-500 mt-3">
                      Last updated:{" "}
                      {(() => {
                        const d = new Date(c.updated_at);
                        if (Number.isNaN(d.getTime())) return String(c.updated_at);
                        return d.toLocaleString("cs-CZ", {
                          day: "2-digit",
                          month: "2-digit",
                          year: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        });
                      })()}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      <ConfirmDialog
        open={deletingChar != null}
        title={`Smazat postavu ${deletingChar?.name ?? ""}?`}
        message="Tato akce je nevratná. Postava bude odstraněna ze Standa Hubu."
        onConfirm={confirmDeleteChar}
        onCancel={() => setDeletingChar(null)}
      />
    </main>
  );
}
