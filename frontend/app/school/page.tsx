"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  ContentContainer,
  EmptyState,
  EntityList,
  EntityRow,
  ErrorState,
  FormField,
  fieldClass,
  HudLabel,
  LoadingState,
  MetricCard,
  PageHeader,
  PageSection,
  StatGrid,
  StatusBadge,
} from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { formatDate, formatRelativeDays } from "@/lib/format";
import { MAX_STAGGER, staggerStyle } from "@/lib/motion";
import {
  assignmentStatusMeta,
  creditsLabel,
  daysUntil,
  deadlineMeta,
  examStatusMeta,
  examTypeLabel,
  isDoneStatus,
  isExamClosed,
  sortByDate,
} from "@/lib/school";
import { cx, priorityTone } from "@/lib/ui";

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

type AgendaItem =
  | { kind: "assignment"; key: string; date: string | null; item: Assignment }
  | { kind: "exam"; key: string; date: string | null; item: Exam };

const PRIORITIES = ["low", "medium", "high"];
const ASSIGNMENT_STATUSES = ["todo", "in_progress", "done"];
const EXAM_TYPES = ["exam", "test", "quiz", "midterm", "oral", "other"];
const EXAM_STATUSES = ["upcoming", "passed", "failed"];

const FORM_IDS = {
  subject: "school-subject-form",
  assignment: "school-assignment-form",
  exam: "school-exam-form",
} as const;

function capitalize(text: string) {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

/** Štítek termínu: „Po termínu · před 2 dny", „Zítra", „Za 5 dní", „Bez termínu". */
function DeadlineBadge({ date, kind, closed }: { date: string | null; kind: "assignment" | "exam"; closed: boolean }) {
  const days = daysUntil(date);
  if (days === null) {
    return closed ? null : <StatusBadge tone="neutral">Bez termínu</StatusBadge>;
  }
  const meta = deadlineMeta(days, kind, closed);
  const rel = formatRelativeDays(days);
  return (
    <StatusBadge tone={meta.tone} dot={meta.overdue}>
      {meta.prefix ? `${meta.prefix} · ${rel}` : capitalize(rel)}
    </StatusBadge>
  );
}

export default function SchoolPage() {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [exams, setExams] = useState<Exam[]>([]);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [retrying, setRetrying] = useState(false);

  const [formKind, setFormKind] = useState<FormKind>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
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
        apiFetch("/school/subjects"),
        apiFetch("/school/assignments"),
        apiFetch("/school/exams"),
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
      setLoadState("ready");
    } catch {
      setError("Nepodařilo se načíst školní data z backendu.");
      setLoadState((s) => (s === "ready" ? s : "error"));
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void loadData().catch(() => {});
    });
  }, [loadData]);

  async function retryLoad() {
    setRetrying(true);
    try {
      await loadData();
    } finally {
      setRetrying(false);
    }
  }

  function toggleForm(kind: "subject" | "assignment" | "exam") {
    setFormError(null);
    setFormKind((k) => (k === kind ? null : kind));
  }

  function closeForm() {
    setFormError(null);
    setFormKind(null);
  }

  async function handleSubjectSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!subjectDraft.name.trim()) {
      setFormError("Vyplň název předmětu.");
      return;
    }
    setSubmitting(true);
    setError(null);
    setFormError(null);
    try {
      const body = {
        name: subjectDraft.name.trim(),
        code: subjectDraft.code.trim(),
        semester: subjectDraft.semester.trim(),
        credits: subjectDraft.credits === "" ? 0 : Number(subjectDraft.credits),
        active: subjectDraft.active,
      };
      const res = await apiFetch("/school/subject", {
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
      setFormError("Vyplň název úkolu a vyber předmět.");
      return;
    }
    setSubmitting(true);
    setError(null);
    setFormError(null);
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
      const res = await apiFetch("/school/assignment", {
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
      setFormError("Vyplň název zkoušky a vyber předmět.");
      return;
    }
    setSubmitting(true);
    setError(null);
    setFormError(null);
    try {
      const body = {
        title: examDraft.title.trim(),
        exam_type: examDraft.exam_type,
        exam_date: examDraft.exam_date === "" ? null : examDraft.exam_date,
        status: examDraft.status,
        notes: examDraft.notes.trim(),
        subject_id: Number(examDraft.subject_id),
      };
      const res = await apiFetch("/school/exam", {
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
      const res = await apiFetch(`/school/assignment/${deletingAssignment.id}`, {
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
      const res = await apiFetch(`/school/exam/${deletingExam.id}`, {
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
  const openAssignmentList = assignments.filter((a) =>
    ["todo", "in_progress"].includes(a.status.toLowerCase()),
  );
  const openAssignments = openAssignmentList.length;
  const overdueAssignments = openAssignmentList.filter((a) => {
    const d = daysUntil(a.due_date);
    return d !== null && d < 0;
  }).length;
  const upcomingExams = exams.filter((e) =>
    ["upcoming"].includes(e.status.toLowerCase()),
  ).length;

  const toAgenda = (closed: boolean): AgendaItem[] => [
    ...assignments
      .filter((a) => isDoneStatus(a.status) === closed)
      .map((a): AgendaItem => ({ kind: "assignment", key: `a-${a.id}`, date: a.due_date, item: a })),
    ...exams
      .filter((e) => isExamClosed(e.status) === closed)
      .map((e): AgendaItem => ({ kind: "exam", key: `e-${e.id}`, date: e.exam_date, item: e })),
  ];
  const openAgenda = sortByDate(toAgenda(false), (x) => x.date);
  const closedAgenda = sortByDate(toAgenda(true), (x) => x.date, true);

  function renderAgendaRow(entry: AgendaItem, idx: number) {
    const stagger = staggerStyle(Math.min(idx, MAX_STAGGER));
    if (entry.kind === "assignment") {
      const a = entry.item;
      const done = isDoneStatus(a.status);
      const days = daysUntil(a.due_date);
      const overdue = deadlineMeta(days, "assignment", done).overdue;
      const status = assignmentStatusMeta(a.status);
      const priority = priorityTone(a.priority);
      return (
        <EntityRow
          key={entry.key}
          searchTarget={`assignment-${a.id}`}
          style={stagger}
          className={cx("motion-card motion-done-transition", done && "motion-done", overdue && "motion-attention")}
          tone={overdue ? "danger" : "neutral"}
          muted={done}
          badges={
            <>
              <DeadlineBadge date={a.due_date} kind="assignment" closed={done} />
              <StatusBadge tone="neutral">Úkol</StatusBadge>
              <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
              <StatusBadge tone={done ? "neutral" : priority.tone}>Priorita: {priority.label.toLowerCase()}</StatusBadge>
            </>
          }
          title={a.title}
          meta={
            <>
              {a.subject_name || "—"}
              {a.due_date ? ` · termín ${formatDate(a.due_date)}` : ""}
            </>
          }
          actions={
            <Button size="sm" variant="ghost" onClick={() => setDeletingAssignment(a)} aria-label={`Smazat úkol ${a.title}`}>
              Smazat
            </Button>
          }
        >
          {a.description ? <p className="mt-1 max-w-prose whitespace-pre-wrap break-words text-sm text-ink-2">{a.description}</p> : null}
        </EntityRow>
      );
    }
    const e = entry.item;
    const closed = isExamClosed(e.status);
    const status = examStatusMeta(e.status);
    return (
      <EntityRow
        key={entry.key}
        searchTarget={`exam-${e.id}`}
        style={stagger}
        className="motion-card"
        muted={closed}
        badges={
          <>
            <DeadlineBadge date={e.exam_date} kind="exam" closed={closed} />
            <StatusBadge tone="neutral">{examTypeLabel(e.exam_type)}</StatusBadge>
            <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
          </>
        }
        title={e.title}
        meta={
          <>
            {e.subject_name || "—"}
            {e.exam_date ? ` · ${formatDate(e.exam_date)}` : ""}
          </>
        }
        actions={
          <Button size="sm" variant="ghost" onClick={() => setDeletingExam(e)} aria-label={`Smazat zkoušku ${e.title}`}>
            Smazat
          </Button>
        }
      >
        {e.notes ? <p className="mt-1 max-w-prose whitespace-pre-wrap break-words text-sm text-ink-2">{e.notes}</p> : null}
      </EntityRow>
    );
  }

  const formActions = (label: string) => (
    <>
      {formError ? (
        <p role="alert" className="text-sm text-danger">
          {formError}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="primary" busy={submitting} busyLabel="Ukládám…">
          {label}
        </Button>
        <Button variant="ghost" onClick={closeForm}>
          Zrušit
        </Button>
      </div>
    </>
  );

  const subjectOptions = subjects.map((s) => (
    <option key={s.id} value={String(s.id)}>
      {s.name}
    </option>
  ));
  const subjectHint = subjects.length === 0 ? "Nejdřív přidej předmět." : undefined;

  return (
    <ContentContainer>
      <PageHeader
        eyebrow={<HudLabel>Modul · škola</HudLabel>}
        title="Škola"
        subtitle="Termíny úkolů a zkoušek, předměty a jejich stav."
      />

      {loadState === "loading" ? (
        <LoadingState lines={5} label="Načítám školní data…" />
      ) : loadState === "error" ? (
        <ErrorState message={error ?? "Nepodařilo se načíst školní data z backendu."} onRetry={() => void retryLoad()} retrying={retrying} />
      ) : (
        <>
          {error ? <ErrorState message={error} /> : null}

          <StatGrid cols={3}>
            <MetricCard
              label="Otevřené úkoly"
              value={openAssignments}
              hint={overdueAssignments > 0 ? undefined : "nic po termínu"}
              trend={overdueAssignments > 0 ? `${overdueAssignments} po termínu` : undefined}
              trendTone="danger"
            />
            <MetricCard label="Nadcházející zkoušky" value={upcomingExams} />
            <MetricCard label="Aktivní předměty" value={activeSubjects} className="col-span-2 md:col-span-1" />
          </StatGrid>

          {/* ===== TERMÍNY ===== */}
          <PageSection
            labelledBy="school-deadlines"
            title="Termíny"
            description="Otevřené úkoly a zkoušky seřazené podle data."
            actions={
              <>
                <Button
                  size="sm"
                  variant="secondary"
                  aria-expanded={formKind === "assignment"}
                  aria-controls={FORM_IDS.assignment}
                  onClick={() => toggleForm("assignment")}
                >
                  Přidat úkol
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  aria-expanded={formKind === "exam"}
                  aria-controls={FORM_IDS.exam}
                  onClick={() => toggleForm("exam")}
                >
                  Přidat zkoušku
                </Button>
              </>
            }
          >
            {formKind === "assignment" && (
              <Card as="div" id={FORM_IDS.assignment}>
                <CardHeader as="h3" title="Nový úkol" />
                <form onSubmit={handleAssignmentSubmit} className="space-y-4">
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <FormField label="Název *" className="md:col-span-2">
                      {(p) => (
                        <input
                          {...p}
                          type="text"
                          value={assignmentDraft.title}
                          onChange={(e) => setAssignmentDraft((d) => ({ ...d, title: e.target.value }))}
                          className={fieldClass}
                          placeholder="např. Naučit se kapitolu 3"
                        />
                      )}
                    </FormField>
                    <FormField label="Popis" hint="Nepovinné" className="md:col-span-2">
                      {(p) => (
                        <textarea
                          {...p}
                          value={assignmentDraft.description}
                          onChange={(e) => setAssignmentDraft((d) => ({ ...d, description: e.target.value }))}
                          className={cx(fieldClass, "resize-none")}
                          rows={2}
                        />
                      )}
                    </FormField>
                    <FormField label="Předmět *" hint={subjectHint}>
                      {(p) => (
                        <select
                          {...p}
                          value={assignmentDraft.subject_id}
                          onChange={(e) => setAssignmentDraft((d) => ({ ...d, subject_id: e.target.value }))}
                          className={fieldClass}
                        >
                          {subjectOptions}
                        </select>
                      )}
                    </FormField>
                    <FormField label="Termín">
                      {(p) => (
                        <input
                          {...p}
                          type="date"
                          value={assignmentDraft.due_date}
                          onChange={(e) => setAssignmentDraft((d) => ({ ...d, due_date: e.target.value }))}
                          className={fieldClass}
                        />
                      )}
                    </FormField>
                    <FormField label="Priorita">
                      {(p) => (
                        <select
                          {...p}
                          value={assignmentDraft.priority}
                          onChange={(e) => setAssignmentDraft((d) => ({ ...d, priority: e.target.value }))}
                          className={fieldClass}
                        >
                          {PRIORITIES.map((v) => (
                            <option key={v} value={v}>
                              {priorityTone(v).label}
                            </option>
                          ))}
                        </select>
                      )}
                    </FormField>
                    <FormField label="Stav">
                      {(p) => (
                        <select
                          {...p}
                          value={assignmentDraft.status}
                          onChange={(e) => setAssignmentDraft((d) => ({ ...d, status: e.target.value }))}
                          className={fieldClass}
                        >
                          {ASSIGNMENT_STATUSES.map((v) => (
                            <option key={v} value={v}>
                              {assignmentStatusMeta(v).label}
                            </option>
                          ))}
                        </select>
                      )}
                    </FormField>
                  </div>
                  {formActions("Uložit úkol")}
                </form>
              </Card>
            )}

            {formKind === "exam" && (
              <Card as="div" id={FORM_IDS.exam}>
                <CardHeader as="h3" title="Nová zkouška" />
                <form onSubmit={handleExamSubmit} className="space-y-4">
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <FormField label="Název *" className="md:col-span-2">
                      {(p) => (
                        <input
                          {...p}
                          type="text"
                          value={examDraft.title}
                          onChange={(e) => setExamDraft((d) => ({ ...d, title: e.target.value }))}
                          className={fieldClass}
                          placeholder="např. Zkouška z práva"
                        />
                      )}
                    </FormField>
                    <FormField label="Předmět *" hint={subjectHint}>
                      {(p) => (
                        <select
                          {...p}
                          value={examDraft.subject_id}
                          onChange={(e) => setExamDraft((d) => ({ ...d, subject_id: e.target.value }))}
                          className={fieldClass}
                        >
                          {subjectOptions}
                        </select>
                      )}
                    </FormField>
                    <FormField label="Datum">
                      {(p) => (
                        <input
                          {...p}
                          type="date"
                          value={examDraft.exam_date}
                          onChange={(e) => setExamDraft((d) => ({ ...d, exam_date: e.target.value }))}
                          className={fieldClass}
                        />
                      )}
                    </FormField>
                    <FormField label="Typ">
                      {(p) => (
                        <select
                          {...p}
                          value={examDraft.exam_type}
                          onChange={(e) => setExamDraft((d) => ({ ...d, exam_type: e.target.value }))}
                          className={fieldClass}
                        >
                          {EXAM_TYPES.map((v) => (
                            <option key={v} value={v}>
                              {examTypeLabel(v)}
                            </option>
                          ))}
                        </select>
                      )}
                    </FormField>
                    <FormField label="Stav">
                      {(p) => (
                        <select
                          {...p}
                          value={examDraft.status}
                          onChange={(e) => setExamDraft((d) => ({ ...d, status: e.target.value }))}
                          className={fieldClass}
                        >
                          {EXAM_STATUSES.map((v) => (
                            <option key={v} value={v}>
                              {examStatusMeta(v).label}
                            </option>
                          ))}
                        </select>
                      )}
                    </FormField>
                    <FormField label="Poznámky" hint="Témata, místo, pomůcky…" className="md:col-span-2">
                      {(p) => (
                        <textarea
                          {...p}
                          value={examDraft.notes}
                          onChange={(e) => setExamDraft((d) => ({ ...d, notes: e.target.value }))}
                          className={cx(fieldClass, "resize-none")}
                          rows={2}
                        />
                      )}
                    </FormField>
                  </div>
                  {formActions("Uložit zkoušku")}
                </form>
              </Card>
            )}

            {openAgenda.length > 0 ? (
              <EntityList label="Otevřené úkoly a zkoušky">{openAgenda.map(renderAgendaRow)}</EntityList>
            ) : (
              <EmptyState compact>
                {assignments.length === 0 && exams.length === 0
                  ? "Zatím žádné úkoly ani zkoušky."
                  : "Žádné otevřené úkoly ani zkoušky."}
              </EmptyState>
            )}
          </PageSection>

          {/* ===== HOTOVÉ A UZAVŘENÉ ===== */}
          {closedAgenda.length > 0 && (
            <PageSection
              labelledBy="school-closed"
              title="Hotové a uzavřené"
              description="Dokončené úkoly a zkoušky s výsledkem, nejnovější nahoře."
            >
              <EntityList label="Hotové úkoly a uzavřené zkoušky">{closedAgenda.map(renderAgendaRow)}</EntityList>
            </PageSection>
          )}

          {/* ===== PŘEDMĚTY ===== */}
          <PageSection
            labelledBy="school-subjects"
            title="Předměty"
            actions={
              <Button
                size="sm"
                variant="secondary"
                aria-expanded={formKind === "subject"}
                aria-controls={FORM_IDS.subject}
                onClick={() => toggleForm("subject")}
              >
                Přidat předmět
              </Button>
            }
          >
            {formKind === "subject" && (
              <Card as="div" id={FORM_IDS.subject}>
                <CardHeader as="h3" title="Nový předmět" />
                <form onSubmit={handleSubjectSubmit} className="space-y-4">
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    <FormField label="Název *">
                      {(p) => (
                        <input
                          {...p}
                          type="text"
                          value={subjectDraft.name}
                          onChange={(e) => setSubjectDraft((d) => ({ ...d, name: e.target.value }))}
                          className={fieldClass}
                          placeholder="např. English in IT"
                        />
                      )}
                    </FormField>
                    <FormField label="Kód" hint="Nepovinné">
                      {(p) => (
                        <input
                          {...p}
                          type="text"
                          value={subjectDraft.code}
                          onChange={(e) => setSubjectDraft((d) => ({ ...d, code: e.target.value }))}
                          className={fieldClass}
                        />
                      )}
                    </FormField>
                    <FormField label="Semestr">
                      {(p) => (
                        <input
                          {...p}
                          type="text"
                          value={subjectDraft.semester}
                          onChange={(e) => setSubjectDraft((d) => ({ ...d, semester: e.target.value }))}
                          className={fieldClass}
                          placeholder="např. LS 2026/27"
                        />
                      )}
                    </FormField>
                    <FormField label="Kredity">
                      {(p) => (
                        <input
                          {...p}
                          type="number"
                          min="0"
                          inputMode="numeric"
                          value={subjectDraft.credits}
                          onChange={(e) => setSubjectDraft((d) => ({ ...d, credits: e.target.value }))}
                          className={fieldClass}
                          placeholder="0"
                        />
                      )}
                    </FormField>
                    <label className="flex min-h-10 cursor-pointer select-none items-center gap-2 text-sm text-ink-2 md:col-span-2">
                      <input
                        type="checkbox"
                        checked={subjectDraft.active}
                        onChange={(e) => setSubjectDraft((d) => ({ ...d, active: e.target.checked }))}
                        className="h-4 w-4 accent-[var(--color-accent)]"
                      />
                      Aktivní předmět
                    </label>
                  </div>
                  {formActions("Uložit předmět")}
                </form>
              </Card>
            )}

            {subjects.length === 0 ? (
              <EmptyState compact>Zatím žádné předměty.</EmptyState>
            ) : (
              <ul aria-label="Předměty" className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
                {subjects.map((s) => (
                  <Card as="li" inset key={s.id} data-search-target={`subject-${s.id}`} className={cx("min-w-0", !s.active && "opacity-70")}>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <h3 className="min-w-0 break-words font-medium text-ink">{s.name}</h3>
                      {s.code ? <span className="font-mono text-xs text-ink-muted">{s.code}</span> : null}
                      {!s.active ? <StatusBadge tone="neutral">Neaktivní</StatusBadge> : null}
                    </div>
                    {s.semester || s.credits > 0 ? (
                      <p className="mt-0.5 text-sm text-ink-muted">
                        {[s.semester, s.credits > 0 ? creditsLabel(s.credits) : ""].filter(Boolean).join(" · ")}
                      </p>
                    ) : null}
                  </Card>
                ))}
              </ul>
            )}
          </PageSection>
        </>
      )}

      <ConfirmDialog
        open={deletingAssignment != null}
        title={`Smazat úkol ${deletingAssignment?.title ?? ""}?`}
        message="Tato akce je nevratná. Úkol bude odstraněn ze Standa Hubu."
        confirmLabel="Smazat úkol"
        busyLabel="Mažu…"
        onConfirm={confirmDeleteAssignment}
        onCancel={() => setDeletingAssignment(null)}
      />

      <ConfirmDialog
        open={deletingExam != null}
        title={`Smazat zkoušku ${deletingExam?.title ?? ""}?`}
        message="Tato akce je nevratná. Zkouška bude odstraněna ze Standa Hubu."
        confirmLabel="Smazat zkoušku"
        busyLabel="Mažu…"
        onConfirm={confirmDeleteExam}
        onCancel={() => setDeletingExam(null)}
      />
    </ContentContainer>
  );
}
