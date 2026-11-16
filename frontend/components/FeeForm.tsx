"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AuthError, FeeInput, ForbiddenError, putFees } from "@/lib/api";
import { clearAuth, getToken } from "@/lib/auth";
import YearSelect from "@/components/YearSelect";

type FeeRow = { from_year: number | ""; fee: string };

function toRows(fees: FeeInput[]): FeeRow[] {
  return fees.map((f) => ({ from_year: f.from_year, fee: String(f.fee) }));
}

export default function FeeForm({
  caseId,
  years,
  initialFees,
  onSaved,
}: {
  caseId: number;
  years: number[];
  initialFees: FeeInput[];
  onSaved: () => void;
}) {
  const router = useRouter();
  const [fees, setFees] = useState<FeeRow[]>(toRows(initialFees));
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setFees(toRows(initialFees));
  }, [initialFees]);

  const updateFee = (i: number, patch: Partial<FeeRow>) =>
    setFees(fees.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));

  const selectedYears = fees
    .map((f) => f.from_year)
    .filter((y): y is number => y !== "");

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setMessage("");

    const items: FeeInput[] = [];
    for (const f of fees) {
      if (f.from_year === "" && f.fee === "") continue;
      if (f.from_year === "") return setError("年を選択してください");
      const fee = Number(f.fee);
      if (f.fee === "" || !Number.isInteger(fee) || fee < 0)
        return setError("積立金の年額は0以上の整数で入力してください");
      items.push({ from_year: f.from_year, fee });
    }

    const token = getToken();
    if (!token) {
      clearAuth();
      router.replace("/");
      return;
    }

    setSaving(true);
    try {
      await putFees(token, caseId, items);
      setMessage("積立金の増額予定を保存しました");
      onSaved();
    } catch (err) {
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
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="card form-card" onSubmit={save}>
      <h2>積立金の増額予定</h2>
      <p className="sub">
        開始年と年額を登録します。保存すると、既存の予定は置き換わります。空にして保存すると全て削除されます。
      </p>

      {fees.map((f, i) => (
        <div className="grid2" key={i}>
          <YearSelect
            value={f.from_year}
            years={years}
            disabled={selectedYears}
            onChange={(v) => updateFee(i, { from_year: v })}
          />
          <input
            type="number"
            placeholder="年額（円）"
            value={f.fee}
            onChange={(e) => updateFee(i, { fee: e.target.value })}
          />
        </div>
      ))}
      <button
        type="button"
        className="small secondary"
        onClick={() => setFees([...fees, { from_year: "", fee: "" }])}
      >
        積立金の段階を追加
      </button>

      {error && <p className="error">{error}</p>}
      {message && <p className="success">{message}</p>}

      <div className="actions">
        <button type="submit" disabled={saving}>
          {saving ? "保存中…" : "積立金を保存"}
        </button>
      </div>
    </form>
  );
}