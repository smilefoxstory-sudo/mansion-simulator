from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Callable, Optional, Union

from .params import PLAN_YEARS
from .cost_model import Building, estimate_schedule

CORRIDOR_JP = {"single": "片廊下", "center": "中廊下", "stairhall": "階段室"}
WALL_CYCLE_ITEMS = [
    "外壁塗装等", "屋根防水", "床防水",
    "建具・金物等", "共用内部", "外構・附属設備",
]


@dataclass
class Input:
    name: str
    pref: str            # 正式名称（「東京都」など）
    units: int
    built_year: int
    floors: int
    building_area: float
    total_exclusive_area: float
    wall: str            # "tile" | "paint"
    corridor: str        # "single" | "center" | "stairhall"
    base_year: int
    wall_cycle: int      # 12〜15
    start_year: int
    opening_balance: float
    annual_fee: float
    increases: list[dict] = field(default_factory=list)  # [{"year":.., "fee":..}]
    usage_fee_transfer: float = 0
    has_tank: bool = False      # 貯水槽
    all_electric: bool = False  # オール電化
    elevators: int = 0          # EV台数
    parking: int = 0            # 機械式駐車場台数


def js_round(x: float) -> int:
    return math.floor(x + 0.5)


def is_work_year(i: Input, y: int) -> bool:
    return y >= i.base_year and (y - i.base_year) % i.wall_cycle == 0


def _first_wall_offset(i: Input) -> int:
    """開始年以降で最初の外壁系工事の年（start_year からの経過年数）"""
    if i.base_year >= i.start_year:
        return i.base_year - i.start_year
    n = math.ceil((i.start_year - i.base_year) / i.wall_cycle)
    return i.base_year + n * i.wall_cycle - i.start_year


def build_schedule(i: Input) -> dict:
    """cost_model で工事費を計算し、{経過年数: 結果} で返す"""
    b = Building(
        units=i.units,
        floors=i.floors,
        avg_area=i.total_exclusive_area / i.units,
        age=i.start_year - i.built_year,
        building_area=i.building_area,
        wall=i.wall,
        corridor=CORRIDOR_JP.get(i.corridor, "片廊下"),
        has_tank=i.has_tank,
        all_electric=i.all_electric,
        elevators=i.elevators,
        parking=i.parking,
        prefecture=i.pref,
    )
    first = {n: _first_wall_offset(i) for n in WALL_CYCLE_ITEMS}
    sched = estimate_schedule(
        b, wall_cycle=i.wall_cycle, first_years=first, years=PLAN_YEARS - 1
    )
    return {s["year"]: s for s in sched}


CostOverride = Union[dict, Callable[[int], float], None]
FeeSchedule = Optional[dict]  # {開始年: 年額}


def _override_cost(co: CostOverride, year: int) -> Optional[float]:
    if co is None:
        return None
    return co.get(year, 0) if isinstance(co, dict) else co(year)


def fee_for_year(year: int, base_fee: float, schedule: dict) -> float:
    """その年以降、次の段階が来るまで同じ年額を適用。
    どの段階にも満たない年は base_fee を使う。"""
    applicable = [y for y in schedule if y <= year]
    return schedule[max(applicable)] if applicable else base_fee


def _default_fee_schedule(i: Input) -> dict:
    return {int(x["year"]): x["fee"] for x in i.increases}


def simulate(
    i: Input,
    cost_override: CostOverride = None,
    fee_schedule: FeeSchedule = None,
) -> dict:
    reserve_ratio = 16 / 12 if i.units <= 50 else 14 / 12 if i.units <= 100 else 1
    balance = i.opening_balance
    rows = []
    deficit_year = None
    reserve_break_year = None
    max_gap = 0.0  # 各年の（準備金目安 − 期末残高）の最大値
    red = yellow = False

    schedule = build_schedule(i)
    fees = (
        {int(k): v for k, v in fee_schedule.items()}
        if fee_schedule
        else _default_fee_schedule(i)
    )

    prev_fee = None
    for n in range(PLAN_YEARS):
        year = i.start_year + n
        fee = fee_for_year(year, i.annual_fee, fees)
        fee_changed = prev_fee is not None and fee != prev_fee
        prev_fee = fee

        ov = _override_cost(cost_override, year)
        cost_items = []
        if ov is not None:
            cost = ov
        else:
            s = schedule.get(n)
            cost = s["amount_gross"] if s else 0
            cost_items = s["cost_items"] if s else []

        balance = balance + fee + i.usage_fee_transfer - cost
        reserve = fee * reserve_ratio
        status = "red" if balance < 0 else "yellow" if balance < reserve else "blue"

        if balance < 0 and deficit_year is None:
            deficit_year = year
        if balance < reserve and reserve_break_year is None:
            reserve_break_year = year

        if n < 10:
            if balance < 0:
                red = True
            elif balance < reserve:
                yellow = True
        elif balance < reserve:
            yellow = True

        # 各年で「その年の目安」に対する不足を測り、最大のものを不足額にする
        max_gap = max(max_gap, reserve - balance)
        rows.append({"year": year, "fee": fee, "fee_changed": fee_changed,
                     "cost": js_round(cost),
                     "balance": js_round(balance), "reserve": js_round(reserve),
                     "status": status, "cost_items": cost_items})

    judge = "red" if red else "yellow" if yellow else "blue"
    shortage = max(0, js_round(max_gap))
    return {"judge": judge, "deficit_year": deficit_year,
            "reserve_break_year": reserve_break_year, "shortage": shortage,
            "fee_schedule": [{"from_year": y, "fee": fees[y]} for y in sorted(fees)],
            "rows": rows}