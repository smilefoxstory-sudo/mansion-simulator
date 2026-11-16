"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import FeeForm from "@/components/FeeForm";
import PlanForm, { InitialPlan } from "@/components/PlanForm";
import { AuthError, ForbiddenError, User, fetchCompare, fetchResult } from "@/lib/api";
import { USER_KEY, clearAuth, getToken } from "@/lib/auth";

type CostItem = { name: string; amount: number };
type Row = {
  year: number;
  fee: number;
  cost: number;
  balance: number;
  reserve: number;
  status: "red" | "yellow" | "blue";
  cost_items?: CostItem[];
};
type Result = {
  name: string;
  judge: "red" | "yellow" | "blue";
  deficit_year: number | null;
  reserve_break_year: number | null;
  shortage: number;
  rows: Row[];
  input: Record<string, unknown>;
};
type PlanWork = { year: number; amount_gross: number; note: string | null };
type CaseFee = { from_year: number; fee: number };
type ViewMode = "sim" | "plan";

// compare のレスポンスのうち、この画面で使う部分
type CompareExt = {
  fees?: CaseFee[];
  base?: { rows?: Row[] };
  plan?: {
    title: string | null;
    works?: PlanWork[];
  } | null;
};

const yen = (n: number) => `${Math.round(n).toLocaleString()} 円`;
const man = (n: number) => `${Math.round(n / 10000).toLocaleString()}万`;

// 全体判定（最初の10年を中心に判定）
const JUDGE_VIEW = {
  red: { label: "要確認", color: "#d32f2f", text: "早い段階で積立金不足が見込まれます。修繕時に資金不足リスクがあるため、詳細な見積もり取得を推奨します。" },
  yellow: { label: "注意", color: "#f9a825", text: "準備金の目安を下回る時期があります。余裕を持った計画か確認してください。" },
  blue: { label: "問題なし", color: "#1976d2", text: "シミュレーション期間を通じて、積立金は目安を満たしています。" },
} as const;

// 年ごとの状態（各年の期末残高だけで決まる）
const ROW_VIEW = {
  red: { label: "マイナス", color: "#d32f2f" },
  yellow: { label: "不十分", color: "#f9a825" },
  blue: { label: "十分", color: "#1976d2" },
} as const;

const ITEM_COLORS: Record<string, string> = {
  足場: "#90caf9",
  外壁: "#1976d2",
  防水: "#26a69a",
  鉄部塗装: "#8d6e63",
  電気設備: "#fbc02d",
  給排水: "#66bb6a",
  建具: "#ab47bc",
  現場管理: "#b0bec5",
  その他: "#78909c",
};
const colorOf = (name: string) => ITEM_COLORS[name] ?? "#78909c";

function itemsOf(r: Row): CostItem[] {
  if (r.cost_items && r.cost_items.length > 0) return r.cost_items;
  return r.cost > 0 ? [{ name: "その他", amount: r.cost }] : [];
}

function CostChart({ rows }: { rows: Row[] }) {
  const W = 960, H = 340, L = 64, R = 64, T = 16, B = 40;
  const iw = W - L - R, ih = H - T - B;
  const n = rows.length;
  if (n === 0) return null;

  const maxCost = Math.max(1, ...rows.map((r) => r.cost));
  const maxBal = Math.max(1, ...rows.map((r) => r.balance));
  const minBal = Math.min(0, ...rows.map((r) => r.balance));
  const step = iw / n;
  const bw = Math.max(2, step * 0.6);
  const yCost = (v: number) => T + ih - (v / maxCost) * ih;
  const yBal = (v: number) => T + ih - ((v - minBal) / (maxBal - minBal || 1)) * ih;
  const x = (i: number) => L + step * i + step / 2;

  const line = rows.map((r, i) => `${i === 0 ? "M" : "L"}${x(i)},${yBal(r.balance)}`).join(" ");
  const names = Array.from(new Set(rows.flatMap((r) => itemsOf(r).map((c) => c.name))));
  const ticks = [0, 0.25, 0.5, 0.75, 1];

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }} role="img"
        aria-label="将来の工事概算支出と積立金残高のグラフ">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={T + ih - t * ih} y2={T + ih - t * ih} stroke="#e0e0e0" />
            <text x={L - 6} y={T + ih - t * ih + 4} fontSize="11" textAnchor="end" fill="#555">
              {man(maxCost * t)}
            </text>
            <text x={W - R + 6} y={T + ih - t * ih + 4} fontSize="11" fill="#d84315">
              {man(minBal + (maxBal - minBal) * t)}
            </text>
          </g>
        ))}
        {rows.map((r, i) => {
          let acc = 0;
          return (
            <g key={r.year}>
              {itemsOf(r).map((c) => {
                const y0 = yCost(acc);
                acc += c.amount;
                const y1 = yCost(acc);
                return (
                  <rect key={c.name} x={x(i) - bw / 2} y={y1} width={bw} height={Math.max(0, y0 - y1)}
                    fill={colorOf(c.name)}>
                    <title>{`${r.year}年 ${c.name}: ${yen(c.amount)}`}</title>
                  </rect>
                );
              })}
              {i % 5 === 0 && (
                <text x={x(i)} y={H - 16} fontSize="11" textAnchor="middle" fill="#555">
                  {r.year}
                </text>
              )}
            </g>
          );
        })}
        <path d={line} fill="none" stroke="#d84315" strokeWidth="2" />
        <text x={L} y={10} fontSize="11" fill="#555">工事概算支出（税込）</text>
        <text x={W - R} y={10} fontSize="11" textAnchor="end" fill="#d84315">積立金残高</text>
      </svg>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12, fontSize: 12 }}>
        {names.map((nm) => (
          <span key={nm}>
            <span style={{ display: "inline-block", width: 10, height: 10, background: colorOf(nm), marginRight: 4 }} />
            {nm}
          </span>
        ))}
        <span style={{ color: "#d84315" }}>― 積立金残高（右軸）</span>
      </div>
    </div>
  );
}

// useParams() を使うため、下の CaseDetail から Suspense で包んで呼び出す
function CaseDetailInner() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const caseId = Number(params.id);

  const [user, setUser] = useState<User | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [planWorks, setPlanWorks] = useState<PlanWork[]>([]);
  const [planTitle, setPlanTitle] = useState<string | null>(null);
  const [caseFees, setCaseFees] = useState<CaseFee[]>([]);
  const [baseRows, setBaseRows] = useState<Row[] | null>(null);
  const [hasPlan, setHasPlan] = useState(false);
  const [initialPlan, setInitialPlan] = useState<InitialPlan>(null);
  const [view, setView] = useState<ViewMode>("plan");
  const [error, setError] = useState("");
  const [status, setStatus] = useState<"loading" | "ok" | "denied">("loading");

  const load = useCallback(async () => {
    const token = getToken();
    const savedUser = sessionStorage.getItem(USER_KEY);
    if (!token || !savedUser) {
      clearAuth();
      router.replace("/");
      return;
    }
    try {
      const [r, c] = await Promise.all([
        fetchResult(token, caseId),
        fetchCompare(token, caseId),
      ]);
      const ext = c as unknown as CompareExt;
      const p = ext.plan ?? null;
      setUser(JSON.parse(savedUser) as User);
      setResult(r as unknown as Result);
      setPlanWorks(p?.works ?? []);
      setPlanTitle(p?.title ?? null);
      setCaseFees(ext.fees ?? []);
      setHasPlan(p != null);
      setBaseRows(ext.base?.rows ?? null);
      setInitialPlan(p ? { title: p.title, works: p.works ?? [] } : null);
      setError("");
      setStatus("ok");
    } catch (e) {
      if (e instanceof AuthError) {
        clearAuth();
        router.replace("/");
        return;
      }
      // 権限なし・取得失敗のときは、データを一切残さない
      setResult(null);
      setPlanWorks([]);
      setPlanTitle(null);
      setCaseFees([]);
      setBaseRows(null);
      setHasPlan(false);
      setInitialPlan(null);
      setError(
        e instanceof ForbiddenError
          ? "この案件を表示する権限がありません"
          : (e as Error).message
      );
      setStatus("denied");
    }
  }, [caseId, router]);

  useEffect(() => {
    load();
  }, [load]);

  if (status === "loading") return <main className="container">読み込み中…</main>;
  if (status === "denied" || !user || !result) {
    return (
      <main className="container">
        {error && <p className="error">{error}</p>}
        <Link href="/">案件一覧へ戻る</Link>
      </main>
    );
  }

  const isManager = user.role === "manager";
  const jv = JUDGE_VIEW[result.judge];
  const rows = result.rows; // 積立金・計画込み（計画なしなら積立金のみ反映）
  const simRows = baseRows ?? rows; // 計画なしのシミュレーション（積立金は反映）

  // 既存計画がないときは、常にシミュレーション表示
  const mode: ViewMode = hasPlan ? view : "sim";
  const displayRows = mode === "plan" ? rows : simRows;
  const modeLabel = mode === "plan" ? "既存計画" : "シミュレーション";

  // 比較表：シミュレーションの工事年 ＋ 手投入の工事年
  const simByYear = new Map(simRows.filter((r) => r.cost > 0).map((r) => [r.year, r]));
  const planByYear = new Map<number, PlanWork[]>();
  for (const w of planWorks) planByYear.set(w.year, [...(planByYear.get(w.year) ?? []), w]);
  const compareYears = Array.from(new Set([...simByYear.keys(), ...planByYear.keys()])).sort((a, b) => a - b);

  return (
    <AppShell role={user.role}>
      <div className="container">
        <header className="header">
          <div>
            <h1>{result.name}</h1>
            <p className="sub">案件ID {caseId}</p>
          </div>
          <div className="actions">
            <Link className="linkbtn" href="/">案件一覧へ</Link>
          </div>
        </header>

        {error && <p className="error">{error}</p>}

        <section className="card">
          <h2>判定結果のサマリ{hasPlan ? "（既存計画込み）" : ""}</h2>
          <p style={{ fontSize: 22, fontWeight: 700, color: jv.color, margin: "4px 0" }}>● {jv.label}</p>
          <p>{jv.text}</p>
          <p className="sub">
            全体判定は、最初の10年間の状況を中心に判定しています。11年目以降は、赤字になっても「注意」までの判定です。年ごとの表は各年の期末残高の状態を示しており、全体判定とは基準が異なります。
          </p>
          <ul>
            <li>赤字転落年：{result.deficit_year ?? "なし"}</li>
            <li>準備金割れ年：{result.reserve_break_year ?? "なし"}</li>
            <li>最大不足額：{yen(result.shortage)}</li>
          </ul>
        </section>

        <section className="card">
          <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
            <strong>表示：{modeLabel}</strong>
            <button
              type="button"
              className="small secondary"
              disabled={!hasPlan}
              onClick={() => setView(mode === "sim" ? "plan" : "sim")}
            >
              {mode === "sim" ? "既存計画に切り替え" : "シミュレーションに切り替え"}
            </button>
            {!hasPlan && (
              <span className="sub">既存計画が未登録のため、シミュレーションのみ表示しています。</span>
            )}
          </div>
          <p className="sub">
            下のグラフと「年ごとの収支」の表が、同時に切り替わります。積立金の増額予定は、どちらの表示にも反映されます。
          </p>
        </section>

        <section className="card">
          <h2>
            将来の工事概算支出予定（
            {mode === "plan"
              ? "既存計画・税込"
              : "建物情報から算出・税込・計画なし"}
            ）
          </h2>
          <CostChart rows={displayRows} />
          {mode === "plan" && (
            <p className="sub">
              既存計画の工事は、項目の内訳がないため「その他」として表示されます。
            </p>
          )}
        </section>

        <section className="card">
          <h2>年ごとの収支（{modeLabel}）</h2>
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>年</th>
                  <th className="num">積立金収入</th>
                  <th className="num">工事支出</th>
                  <th className="num">期末残高</th>
                  <th className="num">準備金目安</th>
                  <th>期末残高の状態</th>
                </tr>
              </thead>
              <tbody>
                {displayRows.map((r) => (
                  <tr key={r.year}>
                    <td>{r.year}</td>
                    <td className="num">{yen(r.fee)}</td>
                    <td className="num">{r.cost > 0 ? yen(r.cost) : "-"}</td>
                    <td className="num" style={{ color: r.balance < 0 ? "#d32f2f" : undefined }}>
                      {yen(r.balance)}
                    </td>
                    <td className="num">{yen(r.reserve)}</td>
                    <td style={{ color: ROW_VIEW[r.status].color }}>
                      ■ {ROW_VIEW[r.status].label}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="card">
          <h2>修繕計画の比較（シミュレーション工事 と 手投入の既存計画）</h2>
          {planWorks.length === 0 && (
            <p className="sub">既存計画が未登録のため、シミュレーション側のみ表示しています。</p>
          )}
          {planTitle && <p className="sub">既存計画：{planTitle}</p>}
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>年</th>
                  <th>シミュレーション工事（項目・金額）</th>
                  <th className="num">シミュレーション合計</th>
                  <th>既存計画の工事（項目・金額）</th>
                  <th className="num">既存計画合計</th>
                  <th className="num">差額（既存計画 − シミュレーション）</th>
                </tr>
              </thead>
              <tbody>
                {compareYears.length === 0 && (
                  <tr>
                    <td colSpan={6} className="empty">比較できる工事がありません</td>
                  </tr>
                )}
                {compareYears.map((y) => {
                  const sim = simByYear.get(y);
                  const simItems = sim ? itemsOf(sim) : [];
                  const simTotal = sim?.cost ?? 0;
                  const works = planByYear.get(y) ?? [];
                  const planTotal = works.reduce((s, w) => s + w.amount_gross, 0);
                  const diff = planTotal - simTotal;
                  return (
                    <tr key={y}>
                      <td>{y}</td>
                      <td>
                        {simItems.length === 0
                          ? "-"
                          : simItems.map((c) => (
                              <div key={c.name}>{c.name}：{yen(c.amount)}</div>
                            ))}
                      </td>
                      <td className="num">{simTotal > 0 ? yen(simTotal) : "-"}</td>
                      <td>
                        {works.length === 0
                          ? "-"
                          : works.map((w, i) => (
                              <div key={i}>{w.note || "（メモなし）"}：{yen(w.amount_gross)}</div>
                            ))}
                      </td>
                      <td className="num">{planTotal > 0 ? yen(planTotal) : "-"}</td>
                      <td className="num" style={{ color: diff > 0 ? "#d32f2f" : undefined }}>
                        {planWorks.length === 0 ? "-" : `${diff > 0 ? "+" : ""}${diff.toLocaleString()} 円`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        {isManager && (
          <>
            <FeeForm
              caseId={caseId}
              years={rows.map((r) => r.year)}
              initialFees={caseFees}
              onSaved={load}
            />
            <PlanForm
              caseId={caseId}
              years={rows.map((r) => r.year)}
              initialPlan={initialPlan}
              onSaved={load}
            />
          </>
        )}
      </div>
    </AppShell>
  );
}

export default function CaseDetail() {
  return (
    <Suspense fallback={<p>読み込み中…</p>}>
      <CaseDetailInner />
    </Suspense>
  );
}