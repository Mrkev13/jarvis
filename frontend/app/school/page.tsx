"use client";

import { useCallback, useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";
import ConfirmDialog from "@/components/ConfirmDialog";

type Subject = {
  id: number;
  name: string;
  code: string;
  semester: string;
  credits: number;
  active: boolean;
};

type Assignment = {
  id: number;
  title: string;
  description: string;
  due_date: string | null;
  priority: string;
  status: string;
  subject_id: number;
  subject_name: string;
};

type Exam = {
  id: number;
  title: string;
  exam_type: string;
  exam_date: string | null;
  status: string;
  notes: string;
  subject_id: number;
  subject_name: string;
};

type FormKind = "subject" | "assignment" | "exam" | null;

const PRIORITIES = ["low", "medium", "high"];
const ASSIGNMENT_STATUSES = ["todo", "in_progress", "done"];
const EXAM_TYPES = ["exam", "test", "quiz", "midterm", "oral", "other"];
const EXAM_STATUSES = ["upcoming", "passed", "failed"];

function formatDate(value?: string | null) {
  if (!value) return "";
  const d = new Date(value + "T00:00:00");
  if (Number.isNaN(d.getTime())) return value;
  return new Intl.DateTimeFormat("cs-CZ", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(d);
}

function daysUntil(value?: string | null) {
  if (!value) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const d = new Date(value + "T00:00:00");
  if (Number.isNaN(d.getTime())) return null;
  const ms = d.getTime() - today.getTime();
  return Math.ceil(ms / (1000 * 60 * 60 * 24));
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
  const s = status.toLowerCase();
  if (["done", "passed"].includes(s))
    return "bg-green-500/15 text-green-400 border-green-500/30";
  if (["todo", "upcoming"].includes(s))
    return "bg-zinc-500/15 text-zinc-300 border-zinc-500/30";
  if (["in_progress"].includes(s))
    return "bg-blue-500/15 text-blue-400 border-blue-500/30";
  if (["failed"].includes(s))
    return "bg-red-500/15 text-red-400 border-red-500/30";
  return "bg-zinc-500/15 text-zinc-400 border-zinc-500/30";
}

export default function SchoolPage() {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [exams, setExams] = useState<Exam[]>([]);

  const [formKind, setFormKind] = useState<FormKind>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deletingAssignment, setDeletingAssignment] = useState<Assignment | null>(null);
  const [deletingExam, setDeletingExam] = useState<Exam | null>(null);

  const [subjectDraft, setSubjectDraft] = useState({
    name: "",
    code: "",
    semester: "",
    credits: "",
    active: true,
  });
  const [assignmentDraft, setAssignmentDraft] = useState({
    title: "",
    description: "",
    due_date: "",
    priority: "medium",
    status: "todo",
    subject_id: "",
  });
  const [examDraft, setExamDraft] = useState({
    title: "",
    exam_type: "exam",
    exam_date: "",
    status: "upcoming",
    notes: "",
    subject_id: "",
  });

  const loadData = useCallback(async () => {
    try {
      const [subjRes, asRes, examRes] = await Promise.all([
        fetch(apiUrl("/school/subjects")),
        fetch(apiUrl("/school/assignments")),
        fetch(apiUrl("/school/exams")),
      ]);
      if (!subjRes.ok || !asRes.ok || !examRes.ok) {
        throw new Error("Failed to load school data");
      }
      const subj = (await subjRes.json()) as Subject[];
      const asgns = (await asRes.json()) as Assignment[];
      const exs = (await examRes.json()) as Exam[];
      setSubjects(subj);
      setAssignments(asgns);
      setExams(exs);

      if (subj.length > 0) {
        setAssignmentDraft((p) => ({
          ...p,
          subject_id: p.subject_id || String(subj[0].id),
        }));
        setExamDraft((p) => ({
          ...p,
          subject_id: p.subject_id || String(subj[0].id),
        }));
      }

      setError(null);
    } catch {
      setError("Nepodařilo se načíst školní data z backendu.");
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void loadData().catch(() => {});
    });
  }, [loadData]);

  function openForm(kind: "subject" | "assignment" | "exam") {
    setFormKind(kind);
  }

  async function handleSubjectSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!subjectDraft.name.trim()) {
      setError("Vyplň název předmětu.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const body = {
        name: subjectDraft.name.trim(),
        code: subjectDraft.code.trim(),
        semester: subjectDraft.semester.trim(),
        credits: subjectDraft.credits === "" ? 0 : Number(subjectDraft.credits),
        active: subjectDraft.active,
      };
      const res = await fetch(apiUrl("/school/subject"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error("Failed to save subject");

      setFormKind(null);
      setSubjectDraft({
        name: "",
        code: "",
        semester: "",
        credits: "",
        active: true,
      });
      await loadData();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se uložit předmět.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleAssignmentSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!assignmentDraft.title.trim() || !assignmentDraft.subject_id) {
      setError("Vyplň název úkolu a vyber předmět.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const body = {
        title: assignmentDraft.title.trim(),
        description: assignmentDraft.description.trim(),
        due_date:
          assignmentDraft.due_date === "" ? null : assignmentDraft.due_date,
        priority: assignmentDraft.priority,
        status: assignmentDraft.status,
        subject_id: Number(assignmentDraft.subject_id),
      };
      const res = await fetch(apiUrl("/school/assignment"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error("Failed to save assignment");

      setFormKind(null);
      setAssignmentDraft({
        title: "",
        description: "",
        due_date: "",
        priority: "medium",
        status: "todo",
        subject_id: subjects[0] ? String(subjects[0].id) : "",
      });
      await loadData();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se uložit úkol.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleExamSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!examDraft.title.trim() || !examDraft.subject_id) {
      setError("Vyplň název zkoušky a vyber předmět.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const body = {
        title: examDraft.title.trim(),
        exam_type: examDraft.exam_type,
        exam_date: examDraft.exam_date === "" ? null : examDraft.exam_date,
        status: examDraft.status,
        notes: examDraft.notes.trim(),
        subject_id: Number(examDraft.subject_id),
      };
      const res = await fetch(apiUrl("/school/exam"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error("Failed to save exam");

      setFormKind(null);
      setExamDraft({
        title: "",
        exam_type: "exam",
        exam_date: "",
        status: "upcoming",
        notes: "",
        subject_id: subjects[0] ? String(subjects[0].id) : "",
      });
      await loadData();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se uložit zkoušku.");
    } finally {
      setSubmitting(false);
    }
  }

  async function confirmDeleteAssignment() {
    if (!deletingAssignment) return;
    try {
      const res = await fetch(apiUrl(`/school/assignment/${deletingAssignment.id}`), {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Failed to delete assignment");
      await loadData();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se smazat úkol.");
    } finally {
      setDeletingAssignment(null);
    }
  }

  async function confirmDeleteExam() {
    if (!deletingExam) return;
    try {
      const res = await fetch(apiUrl(`/school/exam/${deletingExam.id}`), {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Failed to delete exam");
      await loadData();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se smazat zkoušku.");
    } finally {
      setDeletingExam(null);
    }
  }

  const activeSubjects = subjects.filter((s) => s.active).length;
  const openAssignments = assignments.filter((a) =>
    ["todo", "in_progress"].includes(a.status.toLowerCase()),
  ).length;
  const upcomingExams = exams.filter((e) =>
    ["upcoming"].includes(e.status.toLowerCase()),
  ).length;

  return (
    <main className="p-4 md:p-8 max-w-6xl mx-auto space-y-8 md:space-y-10">
      <header>
        <h1 className="text-2xl md:text-4xl font-bold">School</h1>
        <p className="text-zinc-400 mt-2">
          Subjects, assignments, exams and progress.
        </p>
      </header>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 text-red-400 rounded-xl px-4 py-3">
          {error}
        </div>
      )}

      {/* ===== OVERVIEW ===== */}
      <section id="overview">
        <h2 className="text-2xl font-semibold mb-4">Overview</h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6">
            <div className="text-sm text-zinc-400">Active subjects</div>
            <div className="text-3xl font-semibold mt-1">{activeSubjects}</div>
          </div>
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6">
            <div className="text-sm text-zinc-400">Open assignments</div>
            <div className="text-3xl font-semibold mt-1 text-yellow-400">
              {openAssignments}
            </div>
          </div>
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6">
            <div className="text-sm text-zinc-400">Upcoming exams</div>
            <div className="text-3xl font-semibold mt-1 text-red-400">
              {upcomingExams}
            </div>
          </div>
        </div>
      </section>

      {/* ===== SUBJECTS ===== */}
      <section id="subjects">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-2xl font-semibold">Subjects</h2>
          <button
            type="button"
            onClick={() => openForm("subject")}
            className="bg-white text-black text-sm font-medium px-4 py-2 rounded-lg hover:bg-zinc-200 transition-colors"
          >
            Add subject
          </button>
        </div>

        {subjects.length === 0 ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8 text-center text-zinc-400">
            Zatím žádné předměty.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {subjects.map((s) => (
              <div
                key={s.id}
                className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 flex items-start justify-between gap-4"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <div className="text-lg font-semibold truncate">
                      {s.name}
                    </div>
                    {s.code && (
                      <span className="text-xs text-zinc-400 bg-zinc-800 px-2 py-0.5 rounded">
                        {s.code}
                      </span>
                    )}
                    {!s.active && (
                      <span className="text-xs text-zinc-400 bg-zinc-800 px-2 py-0.5 rounded">
                        inactive
                      </span>
                    )}
                  </div>
                  {(s.semester || s.credits > 0) && (
                    <div className="text-sm text-zinc-400 mt-1 flex gap-3 flex-wrap">
                      {s.semester && <span>{s.semester}</span>}
                      {s.credits > 0 && <span>{s.credits} credits</span>}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {formKind === "subject" && (
          <form
            onSubmit={handleSubjectSubmit}
            className="mt-4 bg-zinc-900 border border-zinc-800 rounded-2xl p-6"
          >
            <h3 className="text-lg font-semibold mb-4">Add subject</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="md:col-span-1">
                <label className="block text-sm text-zinc-400 mb-1">Name *</label>
                <input
                  type="text"
                  value={subjectDraft.name}
                  onChange={(e) =>
                    setSubjectDraft((p) => ({ ...p, name: e.target.value }))
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                  placeholder="např. English in IT"
                />
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1">Code</label>
                <input
                  type="text"
                  value={subjectDraft.code}
                  onChange={(e) =>
                    setSubjectDraft((p) => ({ ...p, code: e.target.value }))
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                  placeholder="volitelné"
                />
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1">Semester</label>
                <input
                  type="text"
                  value={subjectDraft.semester}
                  onChange={(e) =>
                    setSubjectDraft((p) => ({ ...p, semester: e.target.value }))
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                  placeholder="např. LS 2026/27"
                />
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1">Credits</label>
                <input
                  type="number"
                  min="0"
                  value={subjectDraft.credits}
                  onChange={(e) =>
                    setSubjectDraft((p) => ({ ...p, credits: e.target.value }))
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                  placeholder="0"
                />
              </div>
              <div className="md:col-span-2 flex items-center gap-2">
                <input
                  id="subj-active"
                  type="checkbox"
                  checked={subjectDraft.active}
                  onChange={(e) =>
                    setSubjectDraft((p) => ({ ...p, active: e.target.checked }))
                  }
                  className="h-4 w-4 rounded border-zinc-700 bg-zinc-800"
                />
                <label
                  htmlFor="subj-active"
                  className="text-sm text-zinc-300 select-none"
                >
                  Active
                </label>
              </div>
            </div>
            <div className="flex gap-3 mt-5">
              <button
                type="submit"
                disabled={submitting}
                className="bg-white text-black font-medium px-5 py-2 rounded-lg disabled:opacity-50"
              >
                {submitting ? "Ukládám..." : "Uložit"}
              </button>
              <button
                type="button"
                onClick={() => setFormKind(null)}
                className="bg-zinc-800 text-white font-medium px-5 py-2 rounded-lg hover:bg-zinc-700"
              >
                Zrušit
              </button>
            </div>
          </form>
        )}
      </section>

      {/* ===== ASSIGNMENTS ===== */}
      <section id="assignments">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-2xl font-semibold">Upcoming assignments</h2>
          <button
            type="button"
            onClick={() => openForm("assignment")}
            className="bg-white text-black text-sm font-medium px-4 py-2 rounded-lg hover:bg-zinc-200 transition-colors"
          >
            Add assignment
          </button>
        </div>

        {assignments.length === 0 ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8 text-center text-zinc-400">
            Zatím žádné úkoly.
          </div>
        ) : (
          <div className="space-y-3">
            {assignments.map((a) => {
              const days = daysUntil(a.due_date);
              return (
                <div
                  key={a.id}
                  className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5"
                >
                  <div className="flex items-start justify-between gap-4 flex-wrap">
                    <div className="flex-1 min-w-0">
                      <div className="text-zinc-400 text-sm">
                        {a.subject_name || "—"}
                      </div>
                      <div className="text-lg font-semibold mt-0.5 truncate">
                        {a.title}
                      </div>
                      {a.description && (
                        <div className="text-sm text-zinc-400 mt-1 max-w-xl">
                          {a.description}
                        </div>
                      )}
                      <div className="flex flex-wrap gap-2 mt-3">
                        {a.due_date && (
                          <span className="inline-flex text-xs font-medium px-2.5 py-1 rounded-md border bg-zinc-800 text-zinc-300 border-zinc-700">
                            Due: {formatDate(a.due_date)}
                            {days !== null && days >= 0 && (
                              <span className="ml-2 opacity-80">
                                ({days === 0 ? "dnes" : `${days} d`})
                              </span>
                            )}
                            {days !== null && days < 0 && (
                              <span className="ml-2 text-red-400">
                                (po termínu)
                              </span>
                            )}
                          </span>
                        )}
                        <span
                          className={`inline-flex text-xs font-medium px-2.5 py-1 rounded-md border ${priorityClass(
                            a.priority,
                          )}`}
                        >
                          {a.priority}
                        </span>
                        <span
                          className={`inline-flex text-xs font-medium px-2.5 py-1 rounded-md border ${statusClass(
                            a.status,
                          )}`}
                        >
                          {a.status}
                        </span>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setDeletingAssignment(a)}
                      className="text-red-400 hover:text-white text-xs bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 px-2.5 py-1 rounded transition-colors shrink-0"
                    >
                      🗑️
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {formKind === "assignment" && (
          <form
            onSubmit={handleAssignmentSubmit}
            className="mt-4 bg-zinc-900 border border-zinc-800 rounded-2xl p-6"
          >
            <h3 className="text-lg font-semibold mb-4">Add assignment</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="md:col-span-2">
                <label className="block text-sm text-zinc-400 mb-1">Title *</label>
                <input
                  type="text"
                  value={assignmentDraft.title}
                  onChange={(e) =>
                    setAssignmentDraft((p) => ({ ...p, title: e.target.value }))
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                  placeholder="např. Naučit se kapitolu 3"
                />
              </div>
              <div className="md:col-span-2">
                <label className="block text-sm text-zinc-400 mb-1">
                  Description
                </label>
                <textarea
                  value={assignmentDraft.description}
                  onChange={(e) =>
                    setAssignmentDraft((p) => ({
                      ...p,
                      description: e.target.value,
                    }))
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500 resize-none"
                  rows={2}
                  placeholder="volitelný popis"
                />
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1">Subject *</label>
                <select
                  value={assignmentDraft.subject_id}
                  onChange={(e) =>
                    setAssignmentDraft((p) => ({
                      ...p,
                      subject_id: e.target.value,
                    }))
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                >
                  {subjects.map((s) => (
                    <option key={s.id} value={String(s.id)}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1">Due date</label>
                <input
                  type="date"
                  value={assignmentDraft.due_date}
                  onChange={(e) =>
                    setAssignmentDraft((p) => ({
                      ...p,
                      due_date: e.target.value,
                    }))
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                />
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1">Priority</label>
                <select
                  value={assignmentDraft.priority}
                  onChange={(e) =>
                    setAssignmentDraft((p) => ({ ...p, priority: e.target.value }))
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
                <label className="block text-sm text-zinc-400 mb-1">Status</label>
                <select
                  value={assignmentDraft.status}
                  onChange={(e) =>
                    setAssignmentDraft((p) => ({ ...p, status: e.target.value }))
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                >
                  {ASSIGNMENT_STATUSES.map((s) => (
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
                disabled={submitting}
                className="bg-white text-black font-medium px-5 py-2 rounded-lg disabled:opacity-50"
              >
                {submitting ? "Ukládám..." : "Uložit"}
              </button>
              <button
                type="button"
                onClick={() => setFormKind(null)}
                className="bg-zinc-800 text-white font-medium px-5 py-2 rounded-lg hover:bg-zinc-700"
              >
                Zrušit
              </button>
            </div>
          </form>
        )}
      </section>

      {/* ===== EXAMS ===== */}
      <section id="exams">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-2xl font-semibold">Upcoming exams</h2>
          <button
            type="button"
            onClick={() => openForm("exam")}
            className="bg-white text-black text-sm font-medium px-4 py-2 rounded-lg hover:bg-zinc-200 transition-colors"
          >
            Add exam
          </button>
        </div>

        {exams.length === 0 ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8 text-center text-zinc-400">
            Zatím žádné zkoušky / testy.
          </div>
        ) : (
          <div className="space-y-3">
            {exams.map((e) => {
              const days = daysUntil(e.exam_date);
              return (
                <div
                  key={e.id}
                  className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5"
                >
                  <div className="flex items-start justify-between gap-4 flex-wrap">
                    <div className="flex-1 min-w-0">
                      <div className="text-zinc-400 text-sm">
                        {e.subject_name || "—"}
                      </div>
                      <div className="text-lg font-semibold mt-0.5 truncate">
                        {e.title}
                      </div>
                      {e.notes && (
                        <div className="text-sm text-zinc-400 mt-1 max-w-xl">
                          {e.notes}
                        </div>
                      )}
                      <div className="flex flex-wrap gap-2 mt-3">
                        <span className="inline-flex text-xs font-medium px-2.5 py-1 rounded-md border bg-zinc-800 text-zinc-300 border-zinc-700">
                          {e.exam_type}
                        </span>
                        {e.exam_date && (
                          <span className="inline-flex text-xs font-medium px-2.5 py-1 rounded-md border bg-zinc-800 text-zinc-300 border-zinc-700">
                            {formatDate(e.exam_date)}
                            {days !== null && days >= 0 && (
                              <span className="ml-2 opacity-80">
                                ({days === 0 ? "dnes" : `zbývá ${days} d`})
                              </span>
                            )}
                            {days !== null && days < 0 && (
                              <span className="ml-2 text-zinc-500">
                                (proběhlo)
                              </span>
                            )}
                          </span>
                        )}
                        <span
                          className={`inline-flex text-xs font-medium px-2.5 py-1 rounded-md border ${statusClass(
                            e.status,
                          )}`}
                        >
                          {e.status}
                        </span>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => setDeletingExam(e)}
                      className="text-red-400 hover:text-white text-xs bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 px-2.5 py-1 rounded transition-colors shrink-0"
                    >
                      🗑️
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {formKind === "exam" && (
          <form
            onSubmit={handleExamSubmit}
            className="mt-4 bg-zinc-900 border border-zinc-800 rounded-2xl p-6"
          >
            <h3 className="text-lg font-semibold mb-4">Add exam</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="md:col-span-2">
                <label className="block text-sm text-zinc-400 mb-1">Title *</label>
                <input
                  type="text"
                  value={examDraft.title}
                  onChange={(e) =>
                    setExamDraft((p) => ({ ...p, title: e.target.value }))
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                  placeholder="např. Zkouška z práva"
                />
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1">Subject *</label>
                <select
                  value={examDraft.subject_id}
                  onChange={(e) =>
                    setExamDraft((p) => ({ ...p, subject_id: e.target.value }))
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                >
                  {subjects.map((s) => (
                    <option key={s.id} value={String(s.id)}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1">Date</label>
                <input
                  type="date"
                  value={examDraft.exam_date}
                  onChange={(e) =>
                    setExamDraft((p) => ({ ...p, exam_date: e.target.value }))
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                />
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1">Type</label>
                <select
                  value={examDraft.exam_type}
                  onChange={(e) =>
                    setExamDraft((p) => ({ ...p, exam_type: e.target.value }))
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                >
                  {EXAM_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm text-zinc-400 mb-1">Status</label>
                <select
                  value={examDraft.status}
                  onChange={(e) =>
                    setExamDraft((p) => ({ ...p, status: e.target.value }))
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                >
                  {EXAM_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>
              <div className="md:col-span-2">
                <label className="block text-sm text-zinc-400 mb-1">Notes</label>
                <textarea
                  value={examDraft.notes}
                  onChange={(e) =>
                    setExamDraft((p) => ({ ...p, notes: e.target.value }))
                  }
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500 resize-none"
                  rows={2}
                  placeholder="poznámky, témata, lokace..."
                />
              </div>
            </div>
            <div className="flex gap-3 mt-5">
              <button
                type="submit"
                disabled={submitting}
                className="bg-white text-black font-medium px-5 py-2 rounded-lg disabled:opacity-50"
              >
                {submitting ? "Ukládám..." : "Uložit"}
              </button>
              <button
                type="button"
                onClick={() => setFormKind(null)}
                className="bg-zinc-800 text-white font-medium px-5 py-2 rounded-lg hover:bg-zinc-700"
              >
                Zrušit
              </button>
            </div>
          </form>
        )}
      </section>

      <ConfirmDialog
        open={deletingAssignment != null}
        title={`Smazat úkol ${deletingAssignment?.title ?? ""}?`}
        message="Tato akce je nevratná. Úkol bude odstraněn ze Standa Hubu."
        onConfirm={confirmDeleteAssignment}
        onCancel={() => setDeletingAssignment(null)}
      />

      <ConfirmDialog
        open={deletingExam != null}
        title={`Smazat zkoušku ${deletingExam?.title ?? ""}?`}
        message="Tato akce je nevratná. Zkouška bude odstraněna ze Standa Hubu."
        onConfirm={confirmDeleteExam}
        onCancel={() => setDeletingExam(null)}
      />
    </main>
  );
}
