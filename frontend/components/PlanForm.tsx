"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AuthError,
  ForbiddenError,
  PlanInput,
  deletePlan,
  putPlan,
} from "@/lib/api";
import { clearAuth, getToken } from "@/lib/auth";
import YearSelect from "@/components/YearSelect";

type WorkRow = { year: number | ""; amount: string; note: string };

export type InitialPlan = {
  title: string | null;
  works: { year: number; amount_gross: number; note: string | null }[];
} | null;

const emptyWork = (): WorkRow => ({ year: "", amount: "", note: "" });

function toWorkRows(plan: InitialPlan): WorkRow[] {
  if (!plan || plan.works.length === 0) return [emptyWork()];
  return plan.works.map((w) => ({
    year: w.year,
    amount: String(w.amount_gross),
    note: w.note ?? "",
  }));
}

export default function PlanForm({
  caseId,
  years,
  initialPlan,
  onSaved,
}: {
  caseId: number;
  years: number[];
  initialPlan: InitialPlan;
  onSaved: () => void;
}) {
  const router = useRouter();
  const [title, setTitle] = useState(initialPlan?.title ?? "");
  const [works, setWorks] = useState<WorkRow[]>(toWorkRows(initialPlan));
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);

  // 保存・削除後などに最新の計画でフォームを更新する
  useEffect(() => {
    setTitle(initialPlan?.title ?? "");
    setWorks(toWorkRows(initialPlan));
  }, [initialPlan]);

  const updateWork = (i: number, patch: Partial<WorkRow>) =>
    setWorks(works.map((w, idx) => (idx === i ? { ...w, ...patch } : w)));

  // 401 は再ログイン、403/404 は権限メッセージ、それ以外はそのまま表示
  function handleError(err: unknown) {
    if (err instanceof AuthError) {
      clearAuth();
      router.replace("/");
      return;
    }
    setError(
      err instanceof ForbiddenError
        ? "この操作を行う権限がありません"
        : (err as Error).message
    );
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setMessage("");

    const workItems: PlanInput["works"] = [];
    for (const w of works) {
      // 何も入力されていない行は無視する
      if (w.year === "" && w.amount === "" && w.note.trim() === "") continue;
      if (w.year === "") return setError("年を選択してください");
      const amount = Number(w.amount);
      if (w.amount === "" || !Number.isInteger(amount) || amount < 0)
        return setError("工事の金額は0以上の整数で入力してください");
      workItems.push({ year: w.year, amount_gross: amount, note: w.note.trim() || null });
    }

    if (workItems.length === 0)
      return setError("工事を1件以上入力してください");

    const token = getToken();
    if (!token) {
      clearAuth();
      router.replace("/");
      return;
    }

    setSaving(true);
    try {
      await putPlan(token, caseId, {
        title: title.trim() || null,
        works: workItems,
      });
      setMessage("計画を保存しました");
      onSaved();
    } catch (err) {
      handleError(err);
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!window.confirm("登録済みの修繕計画を削除します。よろしいですか？")) return;
    const token = getToken();
    if (!token) {
      clearAuth();
      router.replace("/");
      return;
    }
    setError("");
    setMessage("");
    setSaving(true);
    try {
      await deletePlan(token, caseId);
      setMessage("計画を削除しました");
      onSaved();
    } catch (err) {
      handleError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="card form-card" onSubmit={save}>
      <h2>修繕計画の登録</h2>
      <p className="sub">
        登録済みの計画が入力欄に表示されます。保存すると、既存の計画は置き換わります。積立金の増額予定は、別のフォームで登録します。
      </p>

      <label htmlFor="plan-title">計画名</label>
      <input id="plan-title" value={title} onChange={(e) => setTitle(e.target.value)} />

      <h3>工事（年・金額）</h3>
      {works.map((w, i) => (
        <div className="grid3" key={i}>
          <YearSelect
            value={w.year}
            years={years}
            onChange={(v) => updateWork(i, { year: v })}
          />
          <input
            type="number"
            placeholder="金額（円）"
            value={w.amount}
            onChange={(e) => updateWork(i, { amount: e.target.value })}
          />
          <input
            placeholder="メモ（任意）"
            value={w.note}
            onChange={(e) => updateWork(i, { note: e.target.value })}
          />
        </div>
      ))}
      <button
        type="button"
        className="small secondary"
        onClick={() => setWorks([...works, emptyWork()])}
      >
        工事を追加
      </button>

      {error && <p className="error">{error}</p>}
      {message && <p className="success">{message}</p>}

      <div className="actions">
        <button type="submit" disabled={saving}>
          {saving ? "保存中…" : "計画を保存"}
        </button>
        <button type="button" className="small danger" onClick={remove} disabled={saving}>
          計画を削除
        </button>
      </div>
    </form>
  );
}