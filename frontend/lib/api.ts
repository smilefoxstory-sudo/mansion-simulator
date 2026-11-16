const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export type Role = "manager" | "bank";

export type User = {
  display_name: string;
  role: Role;
};

export type LoginResult = User & {
  access_token: string;
  token_type: string;
};

export type Judge = "red" | "yellow" | "blue";

export type CaseRow = {
  id: number;
  name: string;
  shared: number;
  company_id: number;
  company_name: string;
  judge: Judge | null;
  shortage: number | null;
  status: string | null;
};

export type BuildingInput = {
  pref: string;
  units: number;
  built_year: number;
  floors: number;
  building_area: number;
  total_exclusive_area: number;
  wall: "tile" | "paint";
  corridor: "single" | "center" | "stairhall";
  base_year: number;
  wall_cycle: number;
  start_year: number;
  has_tank: boolean;
  all_electric: boolean;
  elevators: number;
  parking: number;
};

export type CaseInput = {
  name: string;
  opening_balance: number;
  annual_fee: number;
  shared?: boolean;
  options?: Partial<BuildingInput>;
};

export type ResultRow = {
  year: number;
  fee: number;
  cost: number;
  balance: number;
  reserve: number;
  status: Judge;
};

export type CaseResult = {
  name: string;
  input: Partial<BuildingInput> & {
    opening_balance: number;
    annual_fee: number;
  };
  judge: Judge;
  shortage: number;
  deficit_year: number | null;
  reserve_break_year: number | null;
  rows: ResultRow[];
};

export type Summary = {
  judge: Judge;
  deficit_year: number | null;
  reserve_break_year: number | null;
  shortage: number;
  rows: ResultRow[];
};

export type WorkRow = {
  year: number;
  amount_gross: number;
  note: string | null;
};

export type FeeInput = { from_year: number; fee: number };

export type CompareResult = {
  case_id: number;
  name: string;
  fees: FeeInput[];
  base: Summary;
  plan:
    | (Summary & { title: string | null; works: WorkRow[] })
    | null;
  diff: { shortage: number; judge_changed: boolean } | null;
};

export type PlanInput = {
  title: string | null;
  works: { year: number; amount_gross: number; note?: string | null }[];
};

// 401 のときに画面側でログアウト処理をするための専用エラー
export class AuthError extends Error {}
// 403/404（権限なし・管理対象外の案件）のときの専用エラー
export class ForbiddenError extends Error {}

async function request<T>(
  path: string,
  token: string,
  method: "GET" | "POST" | "PUT" | "DELETE" = "GET",
  body?: unknown
): Promise<T> {
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    let message = `エラーが発生しました（${res.status}）`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") message = data.detail;
    } catch {
      // JSON でないレスポンスは既定メッセージのまま
    }
    if (res.status === 401) throw new AuthError(message);
    if (res.status === 403 || res.status === 404) throw new ForbiddenError(message);
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

// ログインだけは form 形式で、トークンなしで呼ぶ
export async function login(
  loginCode: string,
  password: string
): Promise<LoginResult> {
  const res = await fetch(`${BASE}/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ login_code: loginCode, password }),
    cache: "no-store",
  });
  if (!res.ok) {
    let message = `エラーが発生しました（${res.status}）`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") message = data.detail;
    } catch {
      // 既定メッセージのまま
    }
    throw new Error(message);
  }
  return res.json() as Promise<LoginResult>;
}

export const fetchCases = (token: string) => request<CaseRow[]>("/cases", token);
export const createCase = (token: string, input: CaseInput) =>
  request<{ case_id: number }>("/cases", token, "POST", input);
export const updateCase = (token: string, id: number, input: CaseInput) =>
  request<{ case_id: number }>(`/cases/${id}`, token, "PUT", input);
export const deleteCase = (token: string, id: number) =>
  request<{ case_id: number; deleted: boolean }>(`/cases/${id}`, token, "DELETE");
export const fetchResult = (token: string, id: number) =>
  request<CaseResult>(`/cases/${id}/result`, token);
export const fetchCompare = (token: string, id: number) =>
  request<CompareResult>(`/cases/${id}/compare`, token);

export const putPlan = (token: string, id: number, plan: PlanInput) =>
  request<{ case_id: number; plan_id: number }>(`/cases/${id}/plan`, token, "PUT", plan);

export const deletePlan = (token: string, id: number) =>
  request<{ case_id: number; deleted: boolean }>(`/cases/${id}/plan`, token, "DELETE");

export const putFees = (token: string, id: number, fees: FeeInput[]) =>
  request<{ case_id: number; count: number }>(`/cases/${id}/fees`, token, "PUT", { fees });