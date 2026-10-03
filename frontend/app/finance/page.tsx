"use client";

import { useState } from "react";
import { AnimatedNumber } from "@/components/motion/AnimatedNumber";
import {
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  ContentContainer,
  EmptyState,
  ErrorState,
  FormField,
  fieldClass,
  HudLabel,
  LoadingState,
  MetricCard,
  PageHeader,
  PageSection,
  StatGrid,
} from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { apiJson, jsonBody } from "@/lib/api";
import { formatCzk, formatDate, formatSigned, plural } from "@/lib/format";
import { staggerStyle, useNewIds } from "@/lib/motion";
import { cx, type Tone } from "@/lib/ui";

type FinanceSummary = {
  income: number;
  expenses: number;
  balance: number;
  transactions_count: number;
};

type FinanceTransaction = {
  id: number;
  amount: number;
  category: string;
  description: string;
  transaction_type: "income" | "expense" | string;
  created_at: string;
};

type FormType = "income" | "expense" | null;
type FieldErrors = { amount?: string; category?: string };

const FORM_ID = "finance-form";
const LOAD_ERROR = "Nepodařilo se načíst finanční data z backendu.";
const EMPTY_FORM = { amount: "", category: "", description: "" };

/** Zůstatek: záporný se skutečným minus, kladný bez „+". */
function formatBalance(value: number): string {
  return value < 0 ? formatSigned(value, formatCzk(value)) : formatCzk(value);
}

function balanceTone(value: number | undefined): Tone {
  if (value === undefined || value === 0) return "neutral";
  return value > 0 ? "success" : "danger";
}

export default function FinancePage() {
  const summary = useApiResource<FinanceSummary>("/finance/summary");
  const txs = useApiResource<FinanceTransaction[]>("/finance/transactions");
  const transactions = txs.data ?? [];
  // Nově přidané transakce krátce zvýraznit (první načtený seznam se nezvýrazňuje).
  const newTxIds = useNewIds(
    transactions.map((tx) => tx.id),
    txs.data !== null,
  );

  const [formType, setFormType] = useState<FormType>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [deletingTx, setDeletingTx] = useState<FinanceTransaction | null>(null);

  const loading = summary.loading || txs.loading;
  const loadFailed = summary.status === "error" || txs.status === "error";
  const refreshFailed = !loadFailed && Boolean(summary.error || txs.error);
  const refreshing = summary.refreshing || txs.refreshing;

  async function loadData() {
    await Promise.all([summary.reload(), txs.reload()]);
  }

  function openForm(type: "income" | "expense") {
    setFormType(type);
    setForm(EMPTY_FORM);
    setFieldErrors({});
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!formType || submitting) return;
    const amountBad = !form.amount || Number(form.amount) <= 0;
    const categoryBad = !form.category.trim();
    if (amountBad || categoryBad) {
      setFieldErrors({
        amount: amountBad ? "Zadej kladnou částku." : undefined,
        category: categoryBad ? "Vyplň kategorii." : undefined,
      });
      return;
    }

    setFieldErrors({});
    setSubmitting(true);
    setActionError(null);
    try {
      const body = {
        amount: Number(form.amount),
        category: form.category.trim(),
        description: form.description.trim(),
        transaction_type: formType,
      };
      await apiJson("/finance/transaction", jsonBody("POST", body));

      setFormType(null);
      setForm(EMPTY_FORM);
      await loadData();
    } catch (err) {
      console.error(err);
      setActionError("Nepodařilo se uložit transakci.");
    } finally {
      setSubmitting(false);
    }
  }

  async function confirmDeleteTx() {
    if (!deletingTx) return;
    setActionError(null);
    try {
      await apiJson(`/finance/transaction/${deletingTx.id}`, { method: "DELETE" });
      await loadData();
    } catch (err) {
      console.error(err);
      setActionError("Nepodařilo se smazat transakci.");
    } finally {
      setDeletingTx(null);
    }
  }

  const s = summary.data;
  const count = transactions.length;

  return (
    <ContentContainer>
      <PageHeader
        eyebrow={<HudLabel>Modul · finance</HudLabel>}
        title="Finance"
        subtitle="Zůstatek, příjmy, výdaje a transakce."
        actions={
          <>
            <Button
              variant="secondary"
              onClick={() => openForm("income")}
              aria-expanded={formType === "income"}
              aria-controls={formType ? FORM_ID : undefined}
            >
              + Přidat příjem
            </Button>
            <Button
              variant="secondary"
              onClick={() => openForm("expense")}
              aria-expanded={formType === "expense"}
              aria-controls={formType ? FORM_ID : undefined}
            >
              − Přidat výdaj
            </Button>
          </>
        }
      />

      {actionError ? <ErrorState message={actionError} /> : null}

      {formType && (
        <Card as="section" id={FORM_ID} aria-labelledby="finance-form-title" index={0}>
          <CardHeader
            title={<span id="finance-form-title">{formType === "income" ? "Nový příjem" : "Nový výdaj"}</span>}
          />
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <FormField label="Částka (Kč)" error={fieldErrors.amount}>
                {(p) => (
                  <input
                    {...p}
                    type="number"
                    inputMode="decimal"
                    step="0.01"
                    min="0"
                    value={form.amount}
                    onChange={(e) => setForm((prev) => ({ ...prev, amount: e.target.value }))}
                    className={cx(fieldClass, "tabular-nums")}
                    placeholder="např. 12500"
                  />
                )}
              </FormField>
              <FormField label="Kategorie" error={fieldErrors.category}>
                {(p) => (
                  <input
                    {...p}
                    type="text"
                    value={form.category}
                    onChange={(e) => setForm((prev) => ({ ...prev, category: e.target.value }))}
                    className={fieldClass}
                    placeholder={formType === "income" ? "např. Práce / Stipendium" : "např. Jídlo / Doprava"}
                  />
                )}
              </FormField>
              <FormField label="Poznámka" hint="Nepovinné">
                {(p) => (
                  <input
                    {...p}
                    type="text"
                    value={form.description}
                    onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))}
                    className={fieldClass}
                  />
                )}
              </FormField>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="submit" variant="primary" busy={submitting} busyLabel="Ukládám…">
                {formType === "income" ? "Uložit příjem" : "Uložit výdaj"}
              </Button>
              <Button variant="ghost" onClick={() => setFormType(null)} disabled={submitting}>
                Zrušit
              </Button>
            </div>
          </form>
        </Card>
      )}

      {loading ? (
        <LoadingState lines={5} label="Načítám finance…" />
      ) : loadFailed ? (
        <ErrorState message={LOAD_ERROR} onRetry={() => void loadData()} retrying={refreshing} />
      ) : (
        <>
          {refreshFailed ? <ErrorState message={`Obnovení selhalo. ${LOAD_ERROR}`} onRetry={() => void loadData()} /> : null}

          <section aria-label="Souhrn" aria-busy={summary.refreshing || undefined}>
            <StatGrid cols={3}>
              <MetricCard
                className="col-span-2 md:col-span-1"
                label="Zůstatek"
                tone={balanceTone(s?.balance)}
                value={<AnimatedNumber value={s?.balance} format={formatBalance} fallback="–" />}
              />
              <MetricCard
                label="Příjmy"
                tone="success"
                value={<AnimatedNumber value={s?.income} format={formatCzk} fallback="–" />}
              />
              <MetricCard
                label="Výdaje"
                value={<AnimatedNumber value={s?.expenses} format={formatCzk} fallback="–" />}
              />
            </StatGrid>
          </section>

          <PageSection
            labelledBy="finance-transactions"
            title="Poslední transakce"
            actions={
              <span className="text-sm text-ink-muted tabular-nums">
                {count} {plural(count, "transakce", "transakce", "transakcí")}
              </span>
            }
          >
            {count === 0 ? (
              <EmptyState
                action={
                  <Button size="sm" variant="secondary" onClick={() => openForm("expense")}>
                    Přidat výdaj
                  </Button>
                }
              >
                Zatím žádné transakce.
              </EmptyState>
            ) : (
              <Card flush as="div" aria-busy={txs.refreshing || undefined}>
                <ul aria-label="Transakce" className="divide-y divide-line-subtle">
                  {transactions.map((tx, idx) => (
                    <TransactionRow
                      key={tx.id}
                      tx={tx}
                      index={idx}
                      highlight={newTxIds.has(String(tx.id))}
                      onDelete={() => setDeletingTx(tx)}
                    />
                  ))}
                </ul>
              </Card>
            )}
          </PageSection>
        </>
      )}

      <ConfirmDialog
        open={deletingTx != null}
        title={`Smazat transakci ${deletingTx?.description || deletingTx?.category || ""}?`}
        message="Tato akce je nevratná. Transakce bude odstraněna a zůstatek se přepočítá."
        confirmLabel="Smazat"
        busyLabel="Mažu…"
        onConfirm={confirmDeleteTx}
        onCancel={() => setDeletingTx(null)}
      />
    </ContentContainer>
  );
}

function TransactionRow({
  tx,
  index,
  highlight,
  onDelete,
}: {
  tx: FinanceTransaction;
  index: number;
  highlight: boolean;
  onDelete: () => void;
}) {
  const isIncome = tx.transaction_type === "income";
  // Výdaj se zobrazí jako záporná částka (skutečné minus); příjem zeleně s „+".
  const signed = isIncome ? tx.amount : -tx.amount;
  const title = tx.description || tx.category;
  return (
    <li
      style={highlight ? undefined : staggerStyle(index)}
      className={cx(
        "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 px-3 py-2.5 md:px-4",
        highlight ? "motion-highlight" : "motion-card",
      )}
    >
      <div className="min-w-0">
        <div className="break-words font-medium text-ink">{title}</div>
        <div className="mt-0.5 flex flex-wrap gap-x-1.5 text-xs text-ink-muted">
          <span className="tabular-nums">{formatDate(tx.created_at)}</span>
          {tx.description ? (
            <>
              <span aria-hidden="true">·</span>
              <span className="break-words">{tx.category}</span>
            </>
          ) : null}
          <span aria-hidden="true">·</span>
          <span>{isIncome ? "Příjem" : "Výdaj"}</span>
        </div>
      </div>
      <div className="flex items-center gap-1 sm:gap-2">
        <span
          className={cx(
            "whitespace-nowrap text-right font-semibold tabular-nums",
            isIncome ? "text-success" : "text-ink",
          )}
        >
          {formatSigned(signed, formatCzk(tx.amount))}
        </span>
        <Button size="sm" variant="ghost" onClick={onDelete} aria-label={`Smazat transakci ${title}`}>
          Smazat
        </Button>
      </div>
    </li>
  );
}
