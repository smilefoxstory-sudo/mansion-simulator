"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import AppShell from "@/components/AppShell";
import JudgeBadge from "@/components/JudgeBadge";
import {
  AuthError,
  BuildingInput,
  CaseRow,
  User,
  createCase,
  deleteCase,
  fetchCases,
  fetchResult,
  login,
  updateCase,
} from "@/lib/api";

const STORAGE_KEY = "access_token";
const USER_KEY = "login_user";

const PREFECTURES = [
  "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
  "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
  "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
  "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
  "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
  "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
  "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
];

// 既存データの「東京」などを「東京都」に直す。直せなければ空（未選択）
function normalizePref(v: string): string {
  const p = v.trim();
  if (PREFECTURES.includes(p)) return p;
  const hit = PREFECTURES.find((x) => x !== "北海道" && x.slice(0, -1) === p);
  return hit ?? "";
}

type FieldDef = {
  key: keyof BuildingInput;
  label: string;
  type: "text" | "number" | "select" | "pref" | "bool";
  options?: { value: string; label: string }[];
};

const BUILDING_FIELDS: FieldDef[] = [
  { key: "pref", label: "都道府県（必須）", type: "pref" },
  { key: "units", label: "戸数", type: "number" },
  { key: "built_year", label: "築年（西暦）", type: "number" },
  { key: "floors", label: "階数", type: "number" },
  { key: "building_area", label: "建築面積（㎡）", type: "number" },
  { key: "total_exclusive_area", label: "専有面積の合計（㎡）", type: "number" },
  {
    key: "wall",
    label: "外壁",
    type: "select",
    options: [
      { value: "tile", label: "タイル" },
      { value: "paint", label: "塗装" },
    ],
  },
  {
    key: "corridor",
    label: "廊下型",
    type: "select",
    options: [
      { value: "single", label: "片廊下" },
      { value: "center", label: "中廊下" },
      { value: "stairhall", label: "階段室" },
    ],
  },
  { key: "base_year", label: "外壁工事の基準年（西暦）", type: "number" },
  { key: "wall_cycle", label: "外壁工事の周期（12〜15年）", type: "number" },
  { key: "start_year", label: "シミュレーション開始年（西暦）", type: "number" },
  { key: "has_tank", label: "貯水槽", type: "bool" },
  { key: "all_electric", label: "オール電化", type: "bool" },
  { key: "elevators", label: "EV台数", type: "number" },
  { key: "parking", label: "機械式駐車場の台数", type: "number" },
];

const BOOL_OPTIONS = [
  { value: "true", label: "あり" },
  { value: "false", label: "なし" },
];

type BuildingForm = Record<keyof BuildingInput, string>;

const emptyBuilding = (): BuildingForm =>
  Object.fromEntries(BUILDING_FIELDS.map((f) => [f.key, ""])) as BuildingForm;

type FormState = {
  id: number | null; // null なら新規登録
  name: string;
  opening_balance: string;
  annual_fee: string;
  shared: boolean;
  building: BuildingForm;
};

const emptyForm = (): FormState => ({
  id: null,
  name: "",
  opening_balance: "",
  annual_fee: "",
  shared: false,
  building: emptyBuilding(),
});

type SortKey = "id" | "company_name" | "name" | "judge" | "shortage";
const JUDGE_RANK: Record<string, number> = { red: 0, yellow: 1, blue: 2 };

export default function Home() {
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [user, setUser] = useState<User | null>(null);
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [ready, setReady] = useState(false);
  const [form, setForm] = useState<FormState | null>(null);
  const [saving, setSaving] = useState(false);

  // 絞り込み・並び替え
  const [keyword, setKeyword] = useState("");
  const [companyFilter, setCompanyFilter] = useState("all");
  const [judgeFilter, setJudgeFilter] = useState("all");
  const [sharedFilter, setSharedFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("id");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  // 早期 return より前に置くこと（フックの呼び出し順を一定にするため）
  const companies = useMemo(
    () =>
      Array.from(
        new Set(cases.map((c) => c.company_name).filter(Boolean))
      ).sort((a, b) => a.localeCompare(b, "ja")),
    [cases]
  );

  const visibleCases = useMemo(() => {
    const kw = keyword.trim();
    const list = cases.filter(
      (c) =>
        c.name.includes(kw) &&
        (companyFilter === "all" || c.company_name === companyFilter) &&
        (judgeFilter === "all" || c.judge?.toLowerCase() === judgeFilter) &&
        (sharedFilter === "all" || (sharedFilter === "shared") === (c.shared === 1))
    );
    const val = (c: CaseRow): number | string | null | undefined =>
      sortKey === "judge"
        ? JUDGE_RANK[c.judge?.toLowerCase() ?? ""]
        : (c as unknown as Record<string, number | string | null>)[sortKey];
    const dir = sortDir === "asc" ? 1 : -1;
    return [...list].sort((a, b) => {
      const x = val(a);
      const y = val(b);
      if (x == null && y == null) return 0;
      if (x == null) return 1; // 未計算は常に末尾
      if (y == null) return -1;
      return (x < y ? -1 : x > y ? 1 : 0) * dir;
    });
  }, [cases, keyword, companyFilter, judgeFilter, sharedFilter, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else {
      setSortKey(key);
      setSortDir("asc");
    }
  }
  const arrow = (key: SortKey) =>
    key === sortKey ? (sortDir === "asc" ? " ▲" : " ▼") : "";

  // 401 のときはログイン画面に戻す
  function handleError(e: unknown) {
    if (e instanceof AuthError) {
      logout();
      setError(e.message);
    } else {
      setError((e as Error).message);
    }
  }

  async function start(loginCode: string, pw: string) {
    setLoading(true);
    setError("");
    try {
      const r = await login(loginCode, pw);
      const list = await fetchCases(r.access_token);
      sessionStorage.setItem(STORAGE_KEY, r.access_token);
      sessionStorage.setItem(
        USER_KEY,
        JSON.stringify({ display_name: r.display_name, role: r.role })
      );
      setToken(r.access_token);
      setUser({ display_name: r.display_name, role: r.role });
      setCases(list);
      setPassword("");
    } catch (e) {
      setUser(null);
      setError(
        e instanceof TypeError
          ? "サーバーに接続できません。バックエンドが起動しているか確認してください。"
          : (e as Error).message
      );
    } finally {
      setLoading(false);
      setReady(true);
    }
  }

  // リロード時はトークンで復元する
  async function restore(savedToken: string, savedUser: User) {
    try {
      const list = await fetchCases(savedToken);
      setToken(savedToken);
      setUser(savedUser);
      setCases(list);
    } catch {
      sessionStorage.removeItem(STORAGE_KEY);
      sessionStorage.removeItem(USER_KEY);
    } finally {
      setReady(true);
    }
  }

  useEffect(() => {
    const savedToken = sessionStorage.getItem(STORAGE_KEY);
    const savedUser = sessionStorage.getItem(USER_KEY);
    if (savedToken && savedUser) {
      restore(savedToken, JSON.parse(savedUser) as User);
    } else {
      setReady(true);
    }
  }, []);

  function logout() {
    sessionStorage.removeItem(STORAGE_KEY);
    sessionStorage.removeItem(USER_KEY);
    setUser(null);
    setToken("");
    setCases([]);
    setCode("");
    setPassword("");
    setForm(null);
    setError("");
    setMessage("");
    setCompanyFilter("all");
  }

  async function reload() {
    setCases(await fetchCases(token));
  }

  function openCreate() {
    setError("");
    setMessage("");
    setForm(emptyForm());
  }

  async function openEdit(c: CaseRow) {
    setError("");
    setMessage("");
    try {
      const r = await fetchResult(token, c.id);
      const building = emptyBuilding();
      for (const f of BUILDING_FIELDS) {
        const v = (r.input as Record<string, unknown>)[f.key];
        if (v !== undefined && v !== null) building[f.key] = String(v);
      }
      // 既存の「東京」などを正式名称に直す（直せなければ未選択）
      building.pref = normalizePref(building.pref);
      setForm({
        id: c.id,
        name: c.name,
        opening_balance: String(r.input.opening_balance ?? ""),
        annual_fee: String(r.input.annual_fee ?? ""),
        shared: c.shared === 1,
        building,
      });
    } catch (e) {
      handleError(e);
    }
  }

  async function submitForm(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    setError("");
    setMessage("");

    const opening = Number(form.opening_balance);
    const fee = Number(form.annual_fee);
    if (!form.name.trim()) return setError("案件名を入力してください");
    if (form.opening_balance === "" || !Number.isInteger(opening) || opening < 0)
      return setError("期首残高は 0 以上の整数で入力してください");
    if (form.annual_fee === "" || !Number.isInteger(fee) || fee < 0)
      return setError("年間修繕積立金は 0 以上の整数で入力してください");
    if (!PREFECTURES.includes(form.building.pref))
      return setError("都道府県を選択してください");

    // 空欄の項目は送らず、バックエンドの既定値に任せる
    const options: Record<string, string | number | boolean> = {};
    for (const f of BUILDING_FIELDS) {
      const raw = form.building[f.key].trim();
      if (raw === "") continue;
      if (f.type === "number") {
        const n = Number(raw);
        if (!Number.isFinite(n)) return setError(`${f.label}は数値で入力してください`);
        options[f.key] = n;
      } else if (f.type === "bool") {
        options[f.key] = raw === "true";
      } else {
        options[f.key] = raw;
      }
    }

    const input = {
      name: form.name.trim(),
      opening_balance: opening,
      annual_fee: fee,
      shared: form.shared,
      options: options as Partial<BuildingInput>,
    };

    setSaving(true);
    try {
      if (form.id === null) {
        await createCase(token, input);
        setMessage("案件を登録しました");
      } else {
        await updateCase(token, form.id, input);
        setMessage("案件を更新しました");
      }
      await reload();
      setForm(null);
    } catch (e) {
      handleError(e);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(c: CaseRow) {
    if (!window.confirm(`「${c.name}」（ID ${c.id}）を削除します。よろしいですか？`)) return;
    setError("");
    setMessage("");
    try {
      await deleteCase(token, c.id);
      await reload();
      setMessage("案件を削除しました");
    } catch (e) {
      handleError(e);
    }
  }

  if (!ready) return <main className="container">読み込み中…</main>;

  if (!user) {
    return (
      <main className="login-wrap">
        <div className="login-card">
          <div className="login-logo">
            <div>
              <span className="brand-star">★</span>
              <span className="brand-star">★</span>
            </div>
            <span className="brand-logo">はかろうもん</span>
            <p>修繕積立金 見える化ツール</p>
          </div>
          <form
            className="card"
            onSubmit={(e) => {
              e.preventDefault();
              if (code.trim() && password) start(code.trim(), password);
            }}
          >
            <label htmlFor="code">ログインコード</label>
            <input
              id="code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="例: KANRI-A"
              autoFocus
            />
            <label htmlFor="password">パスワード</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
            <button type="submit" disabled={loading || !code.trim() || !password}>
              {loading ? "確認中…" : "ログイン"}
            </button>
            {error && <p className="error">{error}</p>}
          </form>
        </div>
      </main>
    );
  }

  const isManager = user.role === "manager";
  const isBank = user.role === "bank";
  const colCount = isBank ? 8 : 7;

  function setBuilding(key: keyof BuildingInput, value: string) {
    setForm((prev) =>
      prev ? { ...prev, building: { ...prev.building, [key]: value } } : prev
    );
  }

  function selectOptions(f: FieldDef): { value: string; label: string }[] {
    if (f.type === "pref") return PREFECTURES.map((p) => ({ value: p, label: p }));
    if (f.type === "bool") return BOOL_OPTIONS;
    return f.options ?? [];
  }

  return (
    <AppShell role={user.role}>
      <div className="container">
        <header className="header">
          <div>
            <h1>案件一覧</h1>
            <p className="sub">
              {user.display_name}（{isManager ? "管理会社" : "銀行"}）
            </p>
          </div>
          <div className="actions">
            {isManager && !form && <button onClick={openCreate}>新規登録</button>}
            <button className="secondary" onClick={logout}>
              ログアウト
            </button>
          </div>
        </header>

        {message && <p className="success">{message}</p>}
        {error && <p className="error">{error}</p>}

        {form && (
          <form className="card form-card" onSubmit={submitForm}>
            <h2>{form.id === null ? "案件の新規登録" : `案件の編集（ID ${form.id}）`}</h2>

            <label htmlFor="f-name">案件名</label>
            <input
              id="f-name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />

            <div className="grid2">
              <div>
                <label htmlFor="f-open">期首残高（円）</label>
                <input
                  id="f-open"
                  type="number"
                  min={0}
                  value={form.opening_balance}
                  onChange={(e) => setForm({ ...form, opening_balance: e.target.value })}
                  placeholder="例: 30000000"
                />
              </div>
              <div>
                <label htmlFor="f-fee">年間修繕積立金（円）</label>
                <input
                  id="f-fee"
                  type="number"
                  min={0}
                  value={form.annual_fee}
                  onChange={(e) => setForm({ ...form, annual_fee: e.target.value })}
                  placeholder="例: 15000000"
                />
              </div>
            </div>

            <h3>建物情報（都道府県以外は空欄なら既定値で計算）</h3>
            <div className="grid2">
              {BUILDING_FIELDS.map((f) => (
                <div key={f.key}>
                  <label htmlFor={`b-${f.key}`}>{f.label}</label>
                  {f.type === "number" || f.type === "text" ? (
                    <input
                      id={`b-${f.key}`}
                      type={f.type}
                      value={form.building[f.key]}
                      onChange={(e) => setBuilding(f.key, e.target.value)}
                    />
                  ) : (
                    <select
                      id={`b-${f.key}`}
                      value={form.building[f.key]}
                      onChange={(e) => setBuilding(f.key, e.target.value)}
                      required={f.type === "pref"}
                    >
                      <option value="">
                        {f.type === "pref" ? "選択してください" : "（既定値）"}
                      </option>
                      {selectOptions(f).map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              ))}
            </div>

            <label className="check">
              <input
                type="checkbox"
                checked={form.shared}
                onChange={(e) => setForm({ ...form, shared: e.target.checked })}
              />
              銀行に共有する
            </label>

            <div className="actions">
              <button type="submit" disabled={saving}>
                {saving ? "保存中…" : form.id === null ? "登録" : "更新"}
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => setForm(null)}
                disabled={saving}
              >
                キャンセル
              </button>
            </div>
          </form>
        )}

        <div className="card">
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", margin: "8px 0" }}>
            <input
              placeholder="案件名で検索"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
            />
            {isBank && (
              <select
                value={companyFilter}
                onChange={(e) => setCompanyFilter(e.target.value)}
              >
                <option value="all">管理会社：すべて</option>
                {companies.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            )}
            <select value={judgeFilter} onChange={(e) => setJudgeFilter(e.target.value)}>
              <option value="all">判定：すべて</option>
              <option value="red">要確認（赤）</option>
              <option value="yellow">注意（黄）</option>
              <option value="blue">問題なし（青）</option>
            </select>
            <select value={sharedFilter} onChange={(e) => setSharedFilter(e.target.value)}>
              <option value="all">共有：すべて</option>
              <option value="shared">共有中</option>
              <option value="private">非共有</option>
            </select>
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ cursor: "pointer" }} onClick={() => toggleSort("id")}>
                    ID{arrow("id")}
                  </th>
                  {isBank && (
                    <th
                      style={{ cursor: "pointer" }}
                      onClick={() => toggleSort("company_name")}
                    >
                      管理会社{arrow("company_name")}
                    </th>
                  )}
                  <th style={{ cursor: "pointer" }} onClick={() => toggleSort("name")}>
                    案件名{arrow("name")}
                  </th>
                  <th style={{ cursor: "pointer" }} onClick={() => toggleSort("judge")}>
                    判定{arrow("judge")}
                  </th>
                  <th
                    className="num"
                    style={{ cursor: "pointer" }}
                    onClick={() => toggleSort("shortage")}
                  >
                    最大不足額{arrow("shortage")}
                  </th>
                  <th>共有</th>
                  <th>ステータス</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {visibleCases.length === 0 && (
                  <tr>
                    <td
                      colSpan={colCount}
                      className="empty"
                      style={{ position: "static" }}
                    >
                      {cases.length === 0
                        ? "表示できる案件がありません"
                        : "条件に合う案件がありません"}
                    </td>
                  </tr>
                )}
                {visibleCases.map((c) => (
                  <tr key={c.id}>
                    <td>{c.id}</td>
                    {isBank && <td>{c.company_name}</td>}
                    <td>{c.name}</td>
                    <td>
                      <JudgeBadge judge={c.judge} />
                    </td>
                    <td
                      className={
                        c.shortage != null && c.shortage > 0 ? "num shortage-cell" : "num"
                      }
                    >
                      {c.shortage == null ? "-" : `${c.shortage.toLocaleString()} 円`}
                    </td>
                    <td>{c.shared ? "共有中" : "非共有"}</td>
                    <td>{c.status ?? "-"}</td>
                    <td className="row-actions">
                      <Link className="linkbtn" href={`/cases/${c.id}`}>
                        結果を見る
                      </Link>
                      {isManager && (
                        <>
                          <button
                            className="secondary small"
                            onClick={() => openEdit(c)}
                          >
                            編集
                          </button>
                          <button
                            className="danger small"
                            onClick={() => handleDelete(c)}
                          >
                            削除
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </AppShell>
  );
}