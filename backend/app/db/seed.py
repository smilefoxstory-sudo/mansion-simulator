import json
from dataclasses import asdict
from app.db.client import get_conn, init_db
from app.engine.engine import simulate
from tests.demo import base

# (名前, 期首残高, 年間収入, 共有)
COMPANIES = {
    "管理会社A": [
        ("赤マンション", 5_000_000, 8_000_000, 1),
        ("黄マンション", 65_000_000, 20_000_000, 0),
        ("A第三ハイツ", 10_000_000, 10_000_000, 1),
        ("A第四レジデンス", 20_000_000, 12_000_000, 0),
        ("A第五コート", 30_000_000, 18_000_000, 1),
        ("A第六パーク", 45_000_000, 22_000_000, 0),
        ("A第七タワー", 80_000_000, 25_000_000, 1),
        ("A第八ガーデン", 100_000_000, 30_000_000, 0),
        ("A第九ヒルズ", 120_000_000, 35_000_000, 1),
        ("A第十プラザ", 150_000_000, 40_000_000, 0),
    ],
    "管理会社B": [
        ("青マンション", 60_000_000, 30_000_000, 1),
        ("B第二ハイツ", 3_000_000, 7_000_000, 1),
        ("B第三レジデンス", 12_000_000, 9_000_000, 0),
        ("B第四コート", 25_000_000, 14_000_000, 1),
        ("B第五パーク", 35_000_000, 17_000_000, 0),
        ("B第六タワー", 55_000_000, 21_000_000, 1),
        ("B第七ガーデン", 75_000_000, 24_000_000, 0),
        ("B第八ヒルズ", 95_000_000, 28_000_000, 1),
        ("B第九プラザ", 130_000_000, 36_000_000, 0),
        ("B第十シティ", 160_000_000, 42_000_000, 1),
    ],
    "管理会社C": [
        ("C第一ハイツ", 4_000_000, 6_000_000, 1),
        ("C第二レジデンス", 8_000_000, 11_000_000, 0),
        ("C第三コート", 18_000_000, 13_000_000, 1),
        ("C第四パーク", 28_000_000, 16_000_000, 0),
        ("C第五タワー", 40_000_000, 19_000_000, 1),
        ("C第六ガーデン", 60_000_000, 23_000_000, 0),
        ("C第七ヒルズ", 85_000_000, 27_000_000, 1),
        ("C第八プラザ", 110_000_000, 32_000_000, 0),
        ("C第九シティ", 140_000_000, 38_000_000, 1),
        ("C第十スクエア", 180_000_000, 45_000_000, 0),
    ],
}

SUFFIX = {"管理会社A": "A", "管理会社B": "B", "管理会社C": "C"}

# 計画を入れる案件名: (タイトル, [(年, 税込工事費, メモ)], [(開始年, 年間収入)])
PLANS = {
    "赤マンション": ("大規模修繕＋値上げ案",
                 [(2027, 60_000_000, "外壁・防水")],
                 [(2027, 16_000_000)]),
    "青マンション": ("外壁改修案",
                 [(2029, 40_000_000, "外壁タイル")],
                 [(2028, 36_000_000)]),
    "A第三ハイツ": ("段階値上げ案",
                 [(2028, 30_000_000, "防水")],
                 [(2027, 15_000_000)]),
    "C第一ハイツ": ("抜本改修案",
                 [(2027, 50_000_000, "外壁・給排水")],
                 [(2027, 14_000_000)]),
}


def seed() -> None:
    init_db()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for t in ["predictions", "case_status", "plan_works", "plan_fees",
                      "plan_headers", "cases", "users", "companies"]:
                cur.execute(f"DELETE FROM {t}")

            ids = {}
            for cname in COMPANIES:
                cur.execute("INSERT INTO companies(name) VALUES (%s)", (cname,))
                ids[cname] = cur.lastrowid

            for cname, s in SUFFIX.items():
                cur.execute(
                    "INSERT INTO users(login_code, role, company_id, display_name) "
                    "VALUES (%s,%s,%s,%s)",
                    (f"KANRI-{s}", "manager", ids[cname], f"{cname} 担当"))
            cur.execute(
                "INSERT INTO users(login_code, role, company_id, display_name) "
                "VALUES (%s,%s,%s,%s)",
                ("BANK-DEMO", "bank", None, "銀行 担当"))

            for cname, rows in COMPANIES.items():
                for name, bal, fee, shared in rows:
                    inp = base(name=name, opening_balance=bal, annual_fee=fee)
                    cur.execute(
                        "INSERT INTO cases(company_id, shared, name, input_json) "
                        "VALUES (%s,%s,%s,%s)",
                        (ids[cname], shared, name,
                         json.dumps(asdict(inp), ensure_ascii=False)))
                    case_id = cur.lastrowid

                    r = simulate(inp)
                    cur.execute(
                        "INSERT INTO predictions(case_id, judge, deficit_year, "
                        "reserve_break_year, shortage, result_json) "
                        "VALUES (%s,%s,%s,%s,%s,%s)",
                        (case_id, r["judge"], r["deficit_year"],
                         r["reserve_break_year"], r["shortage"],
                         json.dumps(r, ensure_ascii=False, default=str)))
                    cur.execute("INSERT INTO case_status(case_id) VALUES (%s)",
                                (case_id,))

                    if name in PLANS:
                        title, works, fees = PLANS[name]
                        cur.execute(
                            "INSERT INTO plan_headers(case_id, title) VALUES (%s,%s)",
                            (case_id, title))
                        plan_id = cur.lastrowid
                        for y, amt, note in works:
                            cur.execute(
                                "INSERT INTO plan_works(plan_id, year, amount_gross, note) "
                                "VALUES (%s,%s,%s,%s)", (plan_id, y, amt, note))
                        for fy, fee in fees:
                            cur.execute(
                                "INSERT INTO plan_fees(plan_id, from_year, fee) "
                                "VALUES (%s,%s,%s)", (plan_id, fy, fee))
        conn.commit()
    finally:
        conn.close()
    print("seed 完了")


if __name__ == "__main__":
    seed()