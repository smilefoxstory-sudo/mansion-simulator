from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Optional

PRICE_INDEX = 1.310
TAX = 0.10
PLAN_YEARS = 41

REGION = {
    "北海道": 1.008, "青森県": 0.954, "岩手県": 0.968, "宮城県": 1.020, "秋田県": 0.985,
    "山形県": 1.032, "福島県": 1.027, "茨城県": 1.052, "栃木県": 1.078, "群馬県": 1.001,
    "埼玉県": 1.097, "千葉県": 1.113, "東京都": 1.117, "神奈川県": 1.104, "新潟県": 0.994,
    "富山県": 1.013, "石川県": 1.014, "福井県": 0.921, "山梨県": 1.073, "長野県": 1.001,
    "岐阜県": 1.016, "静岡県": 1.051, "愛知県": 1.036, "三重県": 1.046, "滋賀県": 0.965,
    "京都府": 0.983, "大阪府": 0.985, "兵庫県": 0.952, "奈良県": 0.996, "和歌山県": 0.972,
    "鳥取県": 0.957, "島根県": 0.930, "岡山県": 0.949, "広島県": 0.939, "山口県": 0.930,
    "徳島県": 0.947, "香川県": 0.958, "愛媛県": 0.950, "高知県": 0.954, "福岡県": 0.972,
    "佐賀県": 1.000, "長崎県": 0.989, "熊本県": 0.974, "大分県": 0.972, "宮崎県": 0.977,
    "鹿児島県": 0.977, "沖縄県": 1.054,
}
REGION_DEFAULT = 1.0


def region_factor(pref: str) -> float:
    """正式名称で引く。末尾なし（「東京」など）の既存データも受け付ける。"""
    p = (pref or "").strip()
    if p in REGION:
        return REGION[p]
    for key, v in REGION.items():
        if key.rstrip("都府県") == p:
            return v
    return REGION_DEFAULT

@dataclass
class Seg:
    type: str  # "const" | "linear" | "root"
    lte: Optional[float] = None
    a: Optional[float] = None
    c: Optional[float] = None
    offset: Optional[float] = None
    n: Optional[float] = None


@dataclass
class Band:
    from_: float
    to: Optional[float]
    value: float


def seg(x: float, segs: list[Seg]) -> float:
    s = next(s for s in segs if s.lte is None or x <= s.lte)
    a = s.a or 0
    c = s.c or 0
    if s.type == "const":
        return c
    if s.type == "linear":
        return a * x + c
    return a * math.pow(x - (s.offset or 0), 1 / (s.n or 2)) + c


def band(age: float, bands: list[Band]) -> float:
    for b in bands:
        if age >= b.from_ and (b.to is None or age <= b.to):
            return b.value
    return 0


def bands(rows: list[tuple]) -> list[Band]:
    return [Band(f, t, v) for f, t, v in rows]


def area(c30, a, c100, lo=30) -> list[Seg]:
    return [Seg("const", lte=lo, c=c30), Seg("linear", lte=100, a=a, c=0), Seg("const", c=c100)]


def units_root(a, c1, c2) -> list[Seg]:
    return [Seg("linear", lte=50, a=a, c=0),
            Seg("root", lte=100, a=a, offset=50, n=2, c=c1),
            Seg("root", a=a, offset=100, n=4, c=c2)]


def floors_root(a, c1, c2) -> list[Seg]:
    return [Seg("linear", lte=15, a=a, c=0),
            Seg("root", lte=30, a=a, offset=15, n=2, c=c1),
            Seg("root", a=a, offset=30, n=4, c=c2)]


@dataclass
class P:
    avg: float
    units: int
    floors: int
    b_area: float
    age: int


# ---------- 単価（円/戸 or 円/㎡） ----------
def direct_temp(p: P) -> float:
    base = (seg(p.avg, area(80460, 2682, 268200)) + seg(p.units, units_root(-1052, -52600, -60039))
            + seg(p.floors, floors_root(8925, 133875, 168441)) + 21305)
    return base * (1 if p.units < 100 else 1 / 1.21 if p.units < 200 else 1 / 1.48)


_ROOF_AGE = bands([(0, 18, 0), (19, 30, -751), (31, 42, -1161), (43, 54, -751), (55, 66, -1161),
                   (67, 78, -751), (79, 90, -1161), (91, 100, -751), (101, None, -1161)])


def roof(p: P) -> float:
    return (seg(p.b_area, [Seg("linear", lte=1000, a=-5, c=3586), Seg("linear", lte=2000, a=-1, c=0),
                           Seg("root", a=-1, offset=2000, n=2, c=-2000)])
            + band(p.age, _ROOF_AGE) + 8102)


FLOOR_AGE = bands([(0, 18, 0), (19, 30, -15292), (31, 42, -22808), (43, 54, -34930), (55, 66, 0),
                   (67, 78, -15292), (79, 90, -22808), (91, 100, -34930), (101, None, 0)])
CORRIDOR = {"single": 1, "center": 0.6, "stairhall": 0.9}


def floor_wp(p: P, corridor: str) -> float:
    return (seg(p.avg, area(28230, 941, 94100)) + seg(p.units, units_root(-104, -5200, -5935))
            + seg(p.floors, [Seg("linear", lte=30, a=1157, c=0), Seg("root", a=1157, offset=30, n=2, c=34710)])
            + band(p.age, FLOOR_AGE) + 64210) * CORRIDOR[corridor]


_TILE_AGE = bands([(0, 18, 0), (19, 30, -70663), (31, 42, -67206), (43, 54, -63749), (55, 66, -60292),
                   (67, 78, -56835), (79, 90, -53378), (91, 100, -49921), (101, None, -46464)])


def wall_tile(p: P) -> float:
    v = (seg(p.avg, area(117870, 3929, 392900))
         + seg(p.units, [Seg("linear", lte=20, a=-15779, c=287153), Seg("linear", lte=50, a=-1702, c=0),
                         Seg("root", lte=100, a=-1702, offset=50, n=2, c=-85100),
                         Seg("root", a=-1702, offset=100, n=4, c=-97135)])
         + seg(p.floors, [Seg("linear", lte=10, a=15348, c=430830), Seg("linear", lte=15, a=47972, c=0),
                          Seg("root", lte=30, a=47972, offset=15, n=2, c=719580),
                          Seg("root", a=47972, offset=30, n=4, c=905375)])
         + band(p.age, _TILE_AGE) - 318680)
    return v * (1 / 1.45 if p.units >= 100 else 1)


_PAINT_AGE = bands([(0, 18, 0), (19, 30, -181388), (31, 42, -159949), (43, 54, -109694), (55, 66, -73129),
                    (67, 78, -36565), (79, 90, 0), (91, 100, 36565), (101, None, 73129)])


def wall_paint(p: P) -> float:
    v = (seg(p.avg, area(97890, 3263, 326300))
         + seg(p.units, [Seg("linear", lte=30, a=-6132, c=173504), Seg("linear", lte=50, a=-1136, c=0),
                         Seg("root", lte=100, a=-1136, offset=50, n=2, c=-56800),
                         Seg("root", a=-1136, offset=100, n=4, c=-64833)])
         + seg(p.floors, floors_root(9185, 137775, 173348))
         + band(p.age, _PAINT_AGE) + 232678)
    return v * (1 / 1.52 if p.units >= 100 else 1)


def _fit_age(age: int) -> float:
    if age <= 18: return 100890
    if age <= 30: return 5605 * age - 19064
    if age <= 42: return 54352
    if age <= 54: return 28500
    if age <= 66: return -207385
    if age <= 78: return -274645
    if age <= 90: return -214688
    if age <= 100: return -240540
    return 100890


def fittings(p: P) -> float:
    return (seg(p.avg, area(120660, 2011, 201100, 60)) + seg(p.units, units_root(577, 28850, 32930))
            + seg(p.floors, floors_root(2965, 44475, 55958)) + _fit_age(p.age) - 201122)


_INTERIOR_AGE = bands([(0, 18, 0), (19, 30, 11315), (31, 42, 44880), (43, None, 74186)])


def common_interior(p: P) -> float:
    return (seg(p.avg, area(13110, 437, 43700)) + seg(p.units, units_root(-245, -12250, -13982))
            + band(p.age, _INTERIOR_AGE) + 8000)


def exterior(p: P) -> float:
    return (seg(p.avg, area(20160, 672, 67200)) + seg(p.units, units_root(-144, -7200, -8218))
            + (20142 if p.age >= 37 else 0) + 1378)