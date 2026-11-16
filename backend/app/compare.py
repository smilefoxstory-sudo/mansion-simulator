import json

import pymysql

from app.db.client import get_conn
from app.engine.engine import Input, simulate


def _dict_cur(conn):
    return conn.cursor(pymysql.cursors.DictCursor)


def load_case(conn, case_id: int) -> dict | None:
    with _dict_cur(conn) as cur:
        cur.execute(
            "SELECT id, company_id, shared, name, input_json FROM cases WHERE id=%s",
            (case_id,),
        )
        return cur.fetchone()


def load_input(case_row: dict) -> Input:
    return Input(**json.loads(case_row["input_json"]))


def load_plan(conn, case_id: int) -> dict | None:
    """修繕計画（工事のみ）を読み込む。積立金は case_fees 側で管理する。"""
    with _dict_cur(conn) as cur:
        cur.execute(
            "SELECT id, title FROM plan_headers WHERE case_id=%s", (case_id,)
        )
        header = cur.fetchone()
        if not header:
            return None
        cur.execute(
            "SELECT year, amount_gross, note FROM plan_works "
            "WHERE plan_id=%s ORDER BY year",
            (header["id"],),
        )
        works = cur.fetchall()
    return {"title": header["title"], "works": works}


def load_fee_rows(conn, case_id: int) -> list[dict]:
    """積立金の増額予定（開始年・年額）を一覧で返す。"""
    with _dict_cur(conn) as cur:
        cur.execute(
            "SELECT from_year, fee FROM case_fees WHERE case_id=%s ORDER BY from_year",
            (case_id,),
        )
        return list(cur.fetchall())


def load_fee_schedule(conn, case_id: int) -> dict[int, int] | None:
    rows = load_fee_rows(conn, case_id)
    return {int(r["from_year"]): int(r["fee"]) for r in rows} or None


def build_cost_override(plan: dict) -> dict[int, int] | None:
    """計画の工事を {年: 税込金額} に変換する。未登録なら None。"""
    co: dict[int, int] = {}
    for w in plan["works"]:
        y = int(w["year"])
        co[y] = co.get(y, 0) + int(w["amount_gross"])
    return co or None


def simulate_with_plan(conn, case: dict) -> dict:
    """積立金の増額予定は常に反映。計画があれば工事も反映する。
    個別画面・一覧の判定・保存処理はすべてこの関数を通す。"""
    inp = load_input(case)
    fee_schedule = load_fee_schedule(conn, case["id"])
    plan = load_plan(conn, case["id"])
    override = build_cost_override(plan) if plan else None
    return simulate(inp, cost_override=override, fee_schedule=fee_schedule)


def _summary(r: dict) -> dict:
    return {
        "judge": r["judge"],
        "deficit_year": r["deficit_year"],
        "reserve_break_year": r["reserve_break_year"],
        "shortage": r["shortage"],
        "fee_schedule": r.get("fee_schedule", []),
        "rows": r["rows"],
    }


def compare_case(case_id: int) -> dict | None:
    conn = get_conn()
    try:
        case = load_case(conn, case_id)
        if not case:
            return None
        inp = load_input(case)
        plan = load_plan(conn, case_id)
        fee_schedule = load_fee_schedule(conn, case_id)
        fee_rows = load_fee_rows(conn, case_id)
    finally:
        conn.close()

    # シミュレーションにも積立金の増額予定を反映
    base = simulate(inp, fee_schedule=fee_schedule)
    result = {
        "case_id": case_id,
        "name": case["name"],
        "fees": fee_rows,
        "base": _summary(base),
        "plan": None,
        "diff": None,
    }
    if plan:
        after = simulate(
            inp, cost_override=build_cost_override(plan), fee_schedule=fee_schedule
        )
        result["plan"] = {
            "title": plan["title"],
            "works": plan["works"],
            **_summary(after),
        }
        result["diff"] = {
            "shortage": after["shortage"] - base["shortage"],
            "judge_changed": after["judge"] != base["judge"],
        }
    return result


def run_and_save_prediction(case_id: int) -> dict | None:
    """積立金・計画込み（なければ現状入力）で計算し、predictions に保存する"""
    conn = get_conn()
    try:
        case = load_case(conn, case_id)
        if not case:
            return None
        r = simulate_with_plan(conn, case)
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO predictions "
                "(case_id, judge, deficit_year, reserve_break_year, shortage, result_json) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    case_id, r["judge"], r["deficit_year"],
                    r["reserve_break_year"], r["shortage"],
                    json.dumps(r, ensure_ascii=False, default=str),
                ),
            )
        conn.commit()
        return r
    finally:
        conn.close()