"use client";

import { useCallback, useEffect, useState } from "react";
import { apiUrl } from "@/lib/api";
import ConfirmDialog from "@/components/ConfirmDialog";

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

function formatNumber(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return "-";
  }
  return new Intl.NumberFormat("cs-CZ").format(value);
}

function formatDate(value?: string) {
  if (!value) return "";
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

export default function FinancePage() {
  const [summary, setSummary] = useState<FinanceSummary | null>(null);
  const [transactions, setTransactions] = useState<FinanceTransaction[]>([]);

  const [formType, setFormType] = useState<FormType>(null);
  const [form, setForm] = useState({
    amount: "",
    category: "",
    description: "",
  });

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deletingTx, setDeletingTx] = useState<FinanceTransaction | null>(null);

  const loadData = useCallback(async () => {
    try {
      const [sumRes, txRes] = await Promise.all([
        fetch(apiUrl("/finance/summary")),
        fetch(apiUrl("/finance/transactions")),
      ]);
      if (!sumRes.ok || !txRes.ok) {
        throw new Error("Failed to load finance data");
      }
      const sumJson = (await sumRes.json()) as FinanceSummary;
      const txJson = (await txRes.json()) as FinanceTransaction[];
      setSummary(sumJson);
      setTransactions(txJson);
      setError(null);
    } catch {
      setError("Nepodařilo se načíst finanční data z backendu.");
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void loadData().catch(() => {});
    });
  }, [loadData]);

  function openForm(type: "income" | "expense") {
    setFormType(type);
    setForm({ amount: "", category: "", description: "" });
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!formType) return;
    if (!form.amount || Number(form.amount) <= 0 || !form.category.trim()) {
      setError("Vyplň částku a kategorii.");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const body = {
        amount: Number(form.amount),
        category: form.category.trim(),
        description: form.description.trim(),
        transaction_type: formType,
      };
      const res = await fetch(apiUrl("/finance/transaction"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error("Failed to save transaction");

      setFormType(null);
      setForm({ amount: "", category: "", description: "" });
      await loadData();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se uložit transakci.");
    } finally {
      setSubmitting(false);
    }
  }

  async function confirmDeleteTx() {
    if (!deletingTx) return;
    try {
      const res = await fetch(apiUrl(`/finance/transaction/${deletingTx.id}`), {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Failed to delete transaction");
      await loadData();
    } catch (err) {
      console.error(err);
      setError("Nepodařilo se smazat transakci.");
    } finally {
      setDeletingTx(null);
    }
  }

  return (
    <main className="p-4 md:p-8 max-w-6xl mx-auto space-y-8 md:space-y-10">
      <header>
        <h1 className="text-2xl md:text-4xl font-bold">Finance</h1>
        <p className="text-zinc-400 mt-2">
          Balance, income, expenses and transactions.
        </p>
      </header>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 text-red-400 rounded-xl px-4 py-3">
          {error}
        </div>
      )}

      {/* ===== SUMMARY CARDS ===== */}
      <section id="summary">
        <div className="bg-gradient-to-br from-zinc-900 to-zinc-900/40 border border-zinc-800 rounded-3xl p-5 md:p-8 mb-4 md:mb-6">
          <div className="text-sm text-zinc-400">Current balance</div>
          <div className="text-3xl md:text-5xl font-bold mt-2">
            {formatNumber(summary?.balance)} Kč
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 md:p-6">
            <div className="flex items-center justify-between mb-3">
              <div className="text-sm text-zinc-400">Income</div>
              <span className="inline-flex text-xs font-medium px-2.5 py-1 rounded-md border bg-green-500/15 text-green-400 border-green-500/30">
                +
              </span>
            </div>
            <div className="text-2xl md:text-3xl font-semibold text-green-400">
              {formatNumber(summary?.income)} Kč
            </div>
          </div>

          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 md:p-6">
            <div className="flex items-center justify-between mb-3">
              <div className="text-sm text-zinc-400">Expenses</div>
              <span className="inline-flex text-xs font-medium px-2.5 py-1 rounded-md border bg-red-500/15 text-red-400 border-red-500/30">
                -
              </span>
            </div>
            <div className="text-2xl md:text-3xl font-semibold text-red-400">
              {formatNumber(summary?.expenses)} Kč
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-3 mt-4 md:mt-6">
          <button
            type="button"
            onClick={() => openForm("income")}
            className="bg-green-500 text-white text-sm font-medium px-4 md:px-5 py-2.5 rounded-lg hover:bg-green-600 transition-colors"
          >
            + Add income
          </button>
          <button
            type="button"
            onClick={() => openForm("expense")}
            className="bg-red-500 text-white text-sm font-medium px-4 md:px-5 py-2.5 rounded-lg hover:bg-red-600 transition-colors"
          >
            - Add expense
          </button>
        </div>
      </section>

      {/* ===== TRANSACTION FORM ===== */}
      {formType && (
        <form
          onSubmit={handleSubmit}
          className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 md:p-6"
        >
          <h3 className="text-lg font-semibold mb-4">
            {formType === "income" ? "Add income" : "Add expense"}
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm text-zinc-400 mb-1">
                Amount (Kč)
              </label>
              <input
                type="number"
                step="0.01"
                min="0"
                value={form.amount}
                onChange={(e) => setForm((p) => ({ ...p, amount: e.target.value }))}
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                placeholder="např. 12500"
              />
            </div>
            <div>
              <label className="block text-sm text-zinc-400 mb-1">
                Category
              </label>
              <input
                type="text"
                value={form.category}
                onChange={(e) => setForm((p) => ({ ...p, category: e.target.value }))}
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                placeholder={formType === "income" ? "např. Work / Stipendium" : "např. Food / Transport"}
              />
            </div>
            <div>
              <label className="block text-sm text-zinc-400 mb-1">
                Description (volitelné)
              </label>
              <input
                type="text"
                value={form.description}
                onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))}
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 outline-none focus:border-zinc-500"
                placeholder="poznámka"
              />
            </div>
          </div>
          <div className="flex gap-3 mt-5">
            <button
              type="submit"
              disabled={submitting}
              className={`font-medium px-5 py-2 rounded-lg disabled:opacity-50 ${
                formType === "income"
                  ? "bg-green-500 hover:bg-green-600 text-white"
                  : "bg-red-500 hover:bg-red-600 text-white"
              }`}
            >
              {submitting ? "Ukládám..." : "Uložit"}
            </button>
            <button
              type="button"
              onClick={() => setFormType(null)}
              className="bg-zinc-800 text-white font-medium px-5 py-2 rounded-lg hover:bg-zinc-700"
            >
              Zrušit
            </button>
          </div>
        </form>
      )}

      {/* ===== RECENT TRANSACTIONS ===== */}
      <section id="transactions">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl md:text-2xl font-semibold">Recent transactions</h2>
          <span className="text-sm text-zinc-400">
            {transactions.length} celkem
          </span>
        </div>

        {transactions.length === 0 ? (
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8 text-center text-zinc-400">
            Zatím žádné transakce.
          </div>
        ) : (
          <>
            {/* === Mobil: karty === */}
            <div className="md:hidden space-y-3">
              {transactions.map((tx) => {
                const isIncome = tx.transaction_type === "income";
                return (
                  <div
                    key={tx.id}
                    className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4"
                  >
                    <div className="flex items-start justify-between gap-3 mb-2">
                      <div className="min-w-0 flex-1">
                        <div className="font-medium truncate">
                          {tx.description || tx.category}
                        </div>
                        <div className="text-xs text-zinc-400 mt-0.5">
                          {tx.category}
                        </div>
                      </div>
                      <div className="flex flex-col items-end gap-1.5 shrink-0">
                        <span
                          className={`inline-flex text-xs font-medium px-2.5 py-1 rounded-md border ${
                            isIncome
                              ? "bg-green-500/15 text-green-400 border-green-500/30"
                              : "bg-red-500/15 text-red-400 border-red-500/30"
                          }`}
                        >
                          {isIncome ? "Income" : "Expense"}
                        </span>
                        <button
                          type="button"
                          onClick={() => setDeletingTx(tx)}
                          className="text-red-400 hover:text-white text-xs bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 px-2 py-1 rounded transition-colors"
                        >
                          🗑️
                        </button>
                      </div>
                    </div>
                    <div className="flex items-center justify-between">
                      <div className="text-xs text-zinc-400">
                        {formatDate(tx.created_at)}
                      </div>
                      <div
                        className={`text-lg font-semibold ${
                          isIncome ? "text-green-400" : "text-red-400"
                        }`}
                      >
                        {isIncome ? "+" : "-"} {formatNumber(tx.amount)} Kč
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* === Desktop: tabulka === */}
            <div className="hidden md:block bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-zinc-800 text-zinc-400 text-sm">
                      <th className="px-5 py-3 font-medium">Popis / Kategorie</th>
                      <th className="px-5 py-3 font-medium">Typ</th>
                      <th className="px-5 py-3 font-medium text-right">Částka</th>
                      <th className="px-5 py-3 font-medium text-right">
                        Datum
                      </th>
                      <th className="px-5 py-3 font-medium text-right">Akce</th>
                    </tr>
                  </thead>
                  <tbody>
                    {transactions.map((tx) => {
                      const isIncome = tx.transaction_type === "income";
                      return (
                        <tr
                          key={tx.id}
                          className="border-b border-zinc-800/70 last:border-0 hover:bg-zinc-800/30"
                        >
                          <td className="px-5 py-4">
                            <div className="font-medium">
                              {tx.description || tx.category}
                            </div>
                            <div className="text-sm text-zinc-400 mt-0.5">
                              {tx.category}
                            </div>
                          </td>
                          <td className="px-5 py-4">
                            <span
                              className={`inline-flex text-xs font-medium px-2.5 py-1 rounded-md border ${
                                isIncome
                                  ? "bg-green-500/15 text-green-400 border-green-500/30"
                                  : "bg-red-500/15 text-red-400 border-red-500/30"
                              }`}
                            >
                              {isIncome ? "Income" : "Expense"}
                            </span>
                          </td>
                          <td
                            className={`px-5 py-4 text-right font-semibold ${
                              isIncome ? "text-green-400" : "text-red-400"
                            }`}
                          >
                            {isIncome ? "+" : "-"} {formatNumber(tx.amount)} Kč
                          </td>
                          <td className="px-5 py-4 text-right text-sm text-zinc-400">
                            {formatDate(tx.created_at)}
                          </td>
                          <td className="px-5 py-4 text-right">
                            <button
                              type="button"
                              onClick={() => setDeletingTx(tx)}
                              className="text-red-400 hover:text-white text-xs bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 px-2.5 py-1 rounded-md transition-colors"
                            >
                              🗑️
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </section>

      <ConfirmDialog
        open={deletingTx != null}
        title={`Smazat transakci ${deletingTx?.description || deletingTx?.category || ""}?`}
        message="Tato akce je nevratná. Transakce bude odstraněna a balance se přepočítá."
        onConfirm={confirmDeleteTx}
        onCancel={() => setDeletingTx(null)}
      />
    </main>
  );
}
