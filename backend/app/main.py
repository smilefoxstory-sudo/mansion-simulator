import json
from dataclasses import asdict, fields
from typing import List

from fastapi import Depends, FastAPI, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pymysql

from app.auth import create_access_token, current_user, verify_password
from app.db.client import get_conn, init_db
from app.compare import (
    compare_case, load_case, load_input, run_and_save_prediction,
    simulate_with_plan,
)
from app.engine.engine import Input, simulate
from app.engine.params import PLAN_YEARS
from tests.demo import base

app = FastAPI(title="mansion-simulator")

# Next.js（localhost:3000）からのアクセスを許可
# Authorization ヘッダーは allow_headers=["*"] で通る
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


def check_access(user: dict, case: dict, write: bool = False):
    role = user["role"]
    if role == "manager":
        ok = case["company_id"] == user["company_id"]
    elif role == "bank":
        ok = (case["shared"] == 1) and not write
    else:
        ok = False
    if not ok:
        raise HTTPException(403, "この案件にはアクセスできません")


def build_input_and_simulate(name: str, opening_balance: int, annual_fee: int, options: dict):
    """登録・更新で共通の入力チェック → Input 生成 → simulate。"""
    name = name.strip()
    if not name:
        raise HTTPException(422, "案件名を入力してください")

    valid = {f.name for f in fields(Input)}
    unknown = set(options) - valid
    if unknown:
        raise HTTPException(422, f"不明な入力項目です: {sorted(unknown)}")
    if {"name", "opening_balance", "annual_fee"} & set(options):
        raise HTTPException(
            422, "name / opening_balance / annual_fee は options ではなく直接指定してください"
        )

    try:
        inp = base(
            name=name,
            opening_balance=opening_balance,
            annual_fee=annual_fee,
            **options,
        )
        r = simulate(inp)
    except Exception as e:
        raise HTTPException(422, f"入力値でシミュレーションできませんでした: {e}")
    return name, inp, r


@app.post("/login")
def login(login_code: str = Form(...), password: str = Form(...)):
    conn = get_conn()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                "SELECT id, role, display_name, password_hash "
                "FROM users WHERE login_code=%s",
                (login_code,),
            )
            u = cur.fetchone()
    finally:
        conn.close()

    # IDが無い場合もパスワード違いの場合も、同じメッセージにする
    if not u or not u["password_hash"] or not verify_password(password, u["password_hash"]):
        raise HTTPException(401, "IDまたはパスワードが違います")

    return {
        "access_token": create_access_token(u["id"], u["role"]),
        "token_type": "bearer",
        "display_name": u["display_name"],
        "role": u["role"],
    }


@app.get("/me")
def me(u: dict = Depends(current_user)):
    """トークンの有効確認用。画面の再読み込み時にログイン状態を復元するのに使う。"""
    return {"display_name": u["display_name"], "role": u["role"]}


@app.get("/cases")
def list_cases(u: dict = Depends(current_user)):
    sql = (
        "SELECT c.id, c.name, c.shared, c.company_id, "
        "co.name AS company_name, "
        "p.judge, p.shortage, s.status "
        "FROM cases c "
        "JOIN companies co ON co.id = c.company_id "
        "LEFT JOIN predictions p ON p.id = "
        "  (SELECT MAX(id) FROM predictions WHERE case_id=c.id) "
        "LEFT JOIN case_status s ON s.case_id=c.id "
    )
    if u["role"] == "manager":
        sql += "WHERE c.company_id=%s ORDER BY c.id"
        args = (u["company_id"],)
    else:
        sql += "WHERE c.shared=1 ORDER BY c.id"
        args = ()
    conn = get_conn()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(sql, args)
            return cur.fetchall()
    finally:
        conn.close()


class CaseCreateBody(BaseModel):
    name: str
    opening_balance: int
    annual_fee: int
    shared: bool = False
    # Input のその他の項目を上書きしたい場合に指定（任意）
    options: dict = {}


@app.post("/cases", status_code=201)
def create_case(body: CaseCreateBody, u: dict = Depends(current_user)):
    if u["role"] != "manager":
        raise HTTPException(403, "案件を登録できるのは管理会社ユーザーのみです")

    # 入力チェック（ここでは検証のみ。保存する予測は commit 後に再計算する）
    name, inp, _ = build_input_and_simulate(
        body.name, body.opening_balance, body.annual_fee, body.options
    )

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO cases(company_id, shared, name, input_json) "
                "VALUES (%s,%s,%s,%s)",
                (
                    u["company_id"],
                    1 if body.shared else 0,
                    name,
                    json.dumps(asdict(inp), ensure_ascii=False),
                ),
            )
            case_id = cur.lastrowid
            cur.execute("INSERT INTO case_status(case_id) VALUES (%s)", (case_id,))
        conn.commit()

        # run_and_save_prediction は別接続で cases を読むため、commit 後に呼ぶ
        r = run_and_save_prediction(case_id)
        if r is None:
            raise HTTPException(500, "予測の保存に失敗しました")

        return {
            "case_id": case_id,
            "name": name,
            "shared": body.shared,
            "judge": r["judge"],
            "shortage": r["shortage"],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class CaseUpdateBody(BaseModel):
    name: str
    opening_balance: int
    annual_fee: int
    # 省略すると共有設定は変更しない
    shared: bool | None = None
    options: dict = {}


@app.put("/cases/{case_id}")
def update_case(case_id: int, body: CaseUpdateBody, u: dict = Depends(current_user)):
    conn = get_conn()
    try:
        case = load_case(conn, case_id)
        if not case:
            raise HTTPException(404, "案件が見つかりません")
        check_access(u, case, write=True)

        # 入力チェック（ここでは検証のみ。保存する予測は積立金・計画込みで再計算する）
        name, inp, _ = build_input_and_simulate(
            body.name, body.opening_balance, body.annual_fee, body.options
        )
        shared = case["shared"] if body.shared is None else (1 if body.shared else 0)

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE cases SET name=%s, shared=%s, input_json=%s WHERE id=%s",
                (name, shared, json.dumps(asdict(inp), ensure_ascii=False), case_id),
            )
        conn.commit()

        # 更新後の入力で、積立金・計画込みの予測を新しく追加（過去の予測は履歴として残す）
        r2 = run_and_save_prediction(case_id)
        if r2 is None:
            raise HTTPException(500, "予測の再計算に失敗しました")
        return {
            "case_id": case_id,
            "name": name,
            "shared": bool(shared),
            "judge": r2["judge"],
            "shortage": r2["shortage"],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.delete("/cases/{case_id}")
def delete_case(case_id: int, u: dict = Depends(current_user)):
    conn = get_conn()
    try:
        case = load_case(conn, case_id)
        if not case:
            raise HTTPException(404, "案件が見つかりません")
        check_access(u, case, write=True)
        with conn.cursor() as cur:
            # 子テーブルから順に削除（plan_works / plan_fees は plan_headers の CASCADE）
            cur.execute("DELETE FROM predictions WHERE case_id=%s", (case_id,))
            cur.execute("DELETE FROM case_status WHERE case_id=%s", (case_id,))
            cur.execute("DELETE FROM case_fees WHERE case_id=%s", (case_id,))
            cur.execute("DELETE FROM plan_headers WHERE case_id=%s", (case_id,))
            cur.execute("DELETE FROM cases WHERE id=%s", (case_id,))
        conn.commit()
        return {"case_id": case_id, "deleted": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.get("/cases/{case_id}/result")
def case_result(case_id: int, u: dict = Depends(current_user)):
    """保存済みの入力から、積立金・計画込み（なければ現状入力）で simulate をやり直し、
    年ごとの表つきで返す。rows の各行には cost_items（8工種・税込）が入っている。"""
    conn = get_conn()
    try:
        case = load_case(conn, case_id)
        if not case:
            raise HTTPException(404, "案件が見つかりません")
        check_access(u, case)

        raw = case["input_json"]
        data = json.loads(raw) if isinstance(raw, (str, bytes)) else dict(raw)
        valid = {f.name for f in fields(Input)}
        data = {k: v for k, v in data.items() if k in valid}

        try:
            r = simulate_with_plan(conn, case)
        except Exception as e:
            raise HTTPException(422, f"シミュレーションできませんでした: {e}")
    finally:
        conn.close()
    return {"name": case["name"], "input": data, **r}


@app.post("/cases/{case_id}/simulate")
def simulate_case(case_id: int, u: dict = Depends(current_user)):
    conn = get_conn()
    try:
        case = load_case(conn, case_id)
    finally:
        conn.close()
    if not case:
        raise HTTPException(404, "案件が見つかりません")
    check_access(u, case, write=True)
    return run_and_save_prediction(case_id)


@app.get("/cases/{case_id}/compare")
def compare(case_id: int, u: dict = Depends(current_user)):
    conn = get_conn()
    try:
        case = load_case(conn, case_id)
    finally:
        conn.close()
    if not case:
        raise HTTPException(404, "案件が見つかりません")
    check_access(u, case)
    # fees（積立金の増額予定）と plan.works が含まれて返る
    return compare_case(case_id)


class ShareBody(BaseModel):
    shared: bool


@app.put("/cases/{case_id}/share")
def set_share(case_id: int, body: ShareBody, u: dict = Depends(current_user)):
    conn = get_conn()
    try:
        case = load_case(conn, case_id)
        if not case:
            raise HTTPException(404, "案件が見つかりません")
        check_access(u, case, write=True)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE cases SET shared=%s WHERE id=%s",
                (1 if body.shared else 0, case_id),
            )
        conn.commit()
        return {"case_id": case_id, "shared": body.shared}
    finally:
        conn.close()


class StatusBody(BaseModel):
    status: str
    memo: str | None = None


@app.put("/cases/{case_id}/status")
def set_status(case_id: int, body: StatusBody, u: dict = Depends(current_user)):
    conn = get_conn()
    try:
        case = load_case(conn, case_id)
        if not case:
            raise HTTPException(404, "案件が見つかりません")
        if u["role"] != "bank" or case["shared"] != 1:
            raise HTTPException(403, "銀行ユーザーのみ、共有済み案件で更新できます")
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO case_status (case_id, status, memo) VALUES (%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE status=VALUES(status), memo=VALUES(memo)",
                (case_id, body.status, body.memo),
            )
        conn.commit()
        return {"case_id": case_id, "status": body.status}
    finally:
        conn.close()


class WorkItem(BaseModel):
    year: int
    amount_gross: int
    note: str | None = None


class FeeItem(BaseModel):
    from_year: int
    fee: int


class PlanBody(BaseModel):
    title: str | None = None
    works: List[WorkItem] = []


class FeesBody(BaseModel):
    fees: List[FeeItem] = []


def validate_plan(case: dict, body: PlanBody) -> None:
    """計画（工事）の年・金額をチェックする。問題があれば 422 を返す。
    年の範囲は、シミュレーションの計算範囲（start_year から PLAN_YEARS 年分）。"""
    if not body.works:
        raise HTTPException(422, "工事を1件以上登録してください")

    inp = load_input(case)
    first_year = inp.start_year
    last_year = inp.start_year + PLAN_YEARS - 1

    for w in body.works:
        if not (first_year <= w.year <= last_year):
            raise HTTPException(
                422,
                f"工事の年 {w.year} は範囲外です（{first_year}〜{last_year}年で指定してください）",
            )
        if w.amount_gross < 0:
            raise HTTPException(422, "工事の金額は0以上で指定してください")


def validate_fees(case: dict, fees: List[FeeItem]) -> None:
    """積立金の増額予定の年・金額・重複をチェックする。"""
    inp = load_input(case)
    first_year = inp.start_year
    last_year = inp.start_year + PLAN_YEARS - 1

    seen: set[int] = set()
    for f in fees:
        if not (first_year <= f.from_year <= last_year):
            raise HTTPException(
                422,
                f"積立金の開始年 {f.from_year} は範囲外です（{first_year}〜{last_year}年で指定してください）",
            )
        if f.fee < 0:
            raise HTTPException(422, "積立金の年額は0以上で指定してください")
        if f.from_year in seen:
            raise HTTPException(
                422, f"積立金の開始年 {f.from_year} が重複しています"
            )
        seen.add(f.from_year)


@app.put("/cases/{case_id}/plan")
def put_plan(case_id: int, body: PlanBody, u: dict = Depends(current_user)):
    conn = get_conn()
    try:
        case = load_case(conn, case_id)
        if not case:
            raise HTTPException(404, "案件が見つかりません")
        check_access(u, case, write=True)

        # DB を書き換える前に検証する
        validate_plan(case, body)

        with conn.cursor() as cur:
            # 既存の計画を削除（子テーブルは ON DELETE CASCADE）
            cur.execute("DELETE FROM plan_headers WHERE case_id=%s", (case_id,))
            cur.execute(
                "INSERT INTO plan_headers(case_id, title) VALUES (%s,%s)",
                (case_id, body.title),
            )
            plan_id = cur.lastrowid
            for w in body.works:
                cur.execute(
                    "INSERT INTO plan_works(plan_id, year, amount_gross, note) "
                    "VALUES (%s,%s,%s,%s)",
                    (plan_id, w.year, w.amount_gross, w.note),
                )
        conn.commit()
        # 積立金・計画込みで再計算し、一覧の判定も揃える
        run_and_save_prediction(case_id)
        return {"case_id": case_id, "plan_id": plan_id}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.delete("/cases/{case_id}/plan")
def delete_plan(case_id: int, u: dict = Depends(current_user)):
    conn = get_conn()
    try:
        case = load_case(conn, case_id)
        if not case:
            raise HTTPException(404, "案件が見つかりません")
        check_access(u, case, write=True)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM plan_headers WHERE case_id=%s", (case_id,))
        conn.commit()
        run_and_save_prediction(case_id)
        return {"case_id": case_id, "deleted": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.put("/cases/{case_id}/fees")
def put_fees(case_id: int, body: FeesBody, u: dict = Depends(current_user)):
    conn = get_conn()
    try:
        case = load_case(conn, case_id)
        if not case:
            raise HTTPException(404, "案件が見つかりません")
        check_access(u, case, write=True)

        validate_fees(case, body.fees)

        with conn.cursor() as cur:
            cur.execute("DELETE FROM case_fees WHERE case_id=%s", (case_id,))
            for f in body.fees:
                cur.execute(
                    "INSERT INTO case_fees(case_id, from_year, fee) VALUES (%s,%s,%s)",
                    (case_id, f.from_year, f.fee),
                )
        conn.commit()
        run_and_save_prediction(case_id)
        return {"case_id": case_id, "count": len(body.fees)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()