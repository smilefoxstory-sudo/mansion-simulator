from app.engine.engine import Input, simulate


def base(**kw) -> Input:
    d = dict(name="demo", pref="東京都", units=60, built_year=2000, floors=8,
             building_area=700, total_exclusive_area=60 * 65, wall="tile", corridor="single",
             base_year=2027, wall_cycle=12, start_year=2026,
             opening_balance=30_000_000, annual_fee=18_000_000)
    d.update(kw)
    return Input(**d)


CASES = {
    "赤想定": base(name="赤", opening_balance=5_000_000, annual_fee=8_000_000),
    "黄想定": base(name="黄", opening_balance=75_000_000, annual_fee=20_000_000),
    "青想定": base(name="青", opening_balance=150_000_000, annual_fee=40_000_000),
}

if __name__ == "__main__":
    for label, inp in CASES.items():
        r = simulate(inp)
        print(f"{label}: 判定={r['judge']} 赤字転落年={r['deficit_year']} "
              f"準備金割れ年={r['reserve_break_year']} 不足額={r['shortage']:,}円")
        # 再現性チェック：同じ入力なら同じ結果
        assert r == simulate(inp), "再現性NG"

    # 工事費の内訳（税込）：2027年の行を表示
    r = simulate(CASES["青想定"])
    row = next(x for x in r["rows"] if x["year"] == 2027)
    print("2027年 工事費内訳(税込):", {c["name"]: c["amount"] for c in row["cost_items"]})
    print("2027年 工事費合計(税込):", row["cost"])
    assert sum(c["amount"] for c in row["cost_items"]) == row["cost"], "内訳合計NG"

    # cost_override が本体の結果を変えないことの確認
    a = simulate(CASES["青想定"])
    simulate(CASES["青想定"], cost_override={2030: 100_000_000})
    assert a == simulate(CASES["青想定"]), "override が本体に影響している"
    print("OK")