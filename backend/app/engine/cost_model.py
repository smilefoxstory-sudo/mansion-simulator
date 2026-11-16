from dataclasses import dataclass
from math import sqrt

from app.engine.params import region_factor

TAX = 0.10
PRICE_INDEX_2026 = 1.310  # 解説書 P.49（2026年度）


@dataclass
class Building:
    units: int                    # 戸数
    floors: int                   # 階数
    avg_area: float               # 平均専有面積(㎡) = 専有面積合計 ÷ 戸数
    age: int                      # 利用年（0年目）時点の築年数
    building_area: float = 0      # 建築面積(㎡)（屋根防水）
    wall: str = "tile"            # "tile" or "paint"
    corridor: str = "片廊下"      # 片廊下 / 中廊下 / 階段室
    has_tank: bool = False        # 貯水槽の有無
    all_electric: bool = False    # オール電化（ガス工事なし）
    elevators: int = 0
    parking: int = 0              # 機械式駐車場台数
    prefecture: str = "全国"      # 正式名称（「東京都」など）。未定義は係数1
    price_index: float = PRICE_INDEX_2026


# ---------- 共通の部品 ----------
def r2(x):  # √
    return sqrt(x)


def r4(x):  # √√
    return sqrt(sqrt(x))


def band(age, table):
    """table: [(上限年, 値), ...] 昇順。最後は上限 None（以降）。"""
    for upper, v in table:
        if upper is None or age <= upper:
            return v
    return table[-1][1]


def area_amt(a, t, low, k, high):
    """平均専有面積: <=t は low、t超〜100は k×面積、100超は high"""
    if a <= t:
        return low
    if a <= 100:
        return k * a
    return high


def units_amt(u, k, c1, c2, sign=-1):
    """戸数: <=50 / 50超〜100 / 100超 の3区分（sign=-1 は減額型）"""
    if u <= 50:
        return sign * k * u
    if u <= 100:
        return sign * k * r2(u - 50) + sign * c1
    return sign * k * r4(u - 100) + sign * c2


def units100(u, k, c):
    """戸数: <=100 / 100超 の2区分（給水・排水の管更生）"""
    if u <= 100:
        return -k * u
    return -k * r2(u - 100) - c


def floors_amt(f, k, c15, c30):
    """階数: <=15 / 15超〜30 / 30超"""
    if f <= 15:
        return k * f
    if f <= 30:
        return k * r2(f - 15) + c15
    return k * r4(f - 30) + c30


# ---------- 年数区分表（解説書の表をそのまま） ----------
AGE_ROOF = [(18, 0), (30, -751), (42, -1161), (54, -751), (66, -1161),
            (78, -751), (90, -1161), (100, -751), (None, -1161)]
AGE_FLOOR = [(18, 0), (30, -15292), (42, -22808), (54, -34930), (66, 0),
             (78, -15292), (90, -22808), (100, -34930), (None, 0)]
AGE_WALL_TILE = [(18, 0), (30, -70663), (42, -67206), (54, -63749), (66, -60292),
                 (78, -56835), (90, -53378), (100, -49921), (None, -46464)]
AGE_WALL_PAINT = [(18, 0), (30, -181388), (42, -159949), (54, -109694), (66, -73129),
                  (78, -36565), (90, 0), (100, 36565), (None, 73129)]
AGE_INNER = [(18, 0), (30, 11315), (42, 44880), (None, 74186)]
# 鉄部: 10〜100年は 1,756×築年数 + 調整定数、0〜9年と101年以降は固定値
AGE_IRON_CONST = [(15, 0), (21, 2877), (27, -4977), (33, -4657), (39, -9115),
                  (45, -21397), (51, -37466), (57, -57657), (63, -57337),
                  (69, -61795), (75, -74077), (81, -90146), (87, -110337),
                  (93, -110017), (100, -114475)]
# 建具: 19〜100年は 5,605×築年数 + 調整定数
AGE_FITTING_CONST = [(30, -19064), (42, 54352), (54, 28500), (66, -207385),
                     (78, -274645), (90, -214688), (100, -240540)]


def age_iron(age):
    if age <= 9:
        return 15804
    if age > 100:
        return 52355
    return 1756 * age + band(age, AGE_IRON_CONST)


def age_fitting(age):
    if age <= 18 or age > 100:
        return 100890
    return 5605 * age + band(age, AGE_FITTING_CONST)


# ---------- 工事項目ごとの単価（戸あたり / ㎡あたり / 台あたり） ----------
def unit_roof(b, age):
    A = b.building_area
    if A <= 1000:
        p = -5 * A + 3586
    elif A <= 2000:
        p = -1 * A
    else:
        p = -r2(A - 2000) - 2000
    return p + band(age, AGE_ROOF) + 8102


def unit_floor(b, age):
    f = b.floors
    fl = 1157 * f if f <= 30 else 1157 * r2(f - 30) + 34710
    base = (area_amt(b.avg_area, 30, 28230, 941, 94100)
            + units_amt(b.units, 104, 5200, 5935)
            + fl + band(age, AGE_FLOOR) + 64210)
    return base * {"片廊下": 1.0, "中廊下": 0.6, "階段室": 0.9}[b.corridor]


def unit_wall(b, age):
    u, f, a = b.units, b.floors, b.avg_area
    if b.wall == "tile":
        if u <= 20:
            un = -15779 * u + 287153
        elif u <= 50:
            un = -1702 * u
        else:
            un = units_amt(u, 1702, 85100, 97135)
        if f <= 10:
            fl = 15348 * f + 430830
        elif f <= 15:
            fl = 47972 * f
        elif f <= 30:
            fl = 47972 * r2(f - 15) + 719580
        else:
            fl = 47972 * r4(f - 30) + 905375
        v = (area_amt(a, 30, 117870, 3929, 392900) + un + fl
             + band(age, AGE_WALL_TILE) - 318680)
        return v / 1.45 if u >= 100 else v
    if u <= 30:
        un = -6132 * u + 173504
    elif u <= 50:
        un = -1136 * u
    else:
        un = units_amt(u, 1136, 56800, 64833)
    v = (area_amt(a, 30, 97890, 3263, 326300) + un
         + floors_amt(f, 9185, 137775, 173348)
         + band(age, AGE_WALL_PAINT) + 232678)
    return v / 1.52 if u >= 100 else v


def unit_iron(b, age):
    return (area_amt(b.avg_area, 40, 19760, 494, 49400)
            + units_amt(b.units, 138, 6900, 7875)
            + floors_amt(b.floors, 1632, 24480, 30800)
            + age_iron(age) - 26246)


def unit_fitting(b, age):
    return (area_amt(b.avg_area, 60, 120660, 2011, 201100)
            + units_amt(b.units, 577, 28850, 32930, sign=1)
            + floors_amt(b.floors, 2965, 44475, 55958)
            + age_fitting(age) - 201122)


def unit_inner(b, age):
    return (area_amt(b.avg_area, 30, 13110, 437, 43700)
            + units_amt(b.units, 245, 12250, 13982)
            + band(age, AGE_INNER) + 8000)


def unit_water_repair(b, age):
    return units100(b.units, 212, 21200) + 85134


def unit_water_replace(b, age):
    v = (area_amt(b.avg_area, 30, 78390, 2613, 261300)
         + units_amt(b.units, 1298, 64900, 74078) + 335841)
    if b.has_tank:
        v += units_amt(b.units, 231, 11550, 13183, sign=1) + 78156
    return v


def unit_drain_repair(b, age):
    return units100(b.units, 25, 2500) + 26699


def unit_drain_replace(b, age):
    return (area_amt(b.avg_area, 30, 51090, 1703, 170300)
            + units_amt(b.units, 1374, 68700, 78416) + 485571)


def unit_gas(b, age):
    if b.all_electric:
        return 0
    return area_amt(b.avg_area, 30, 40380, 1346, 134600) + 24035


def unit_hvac(b, age):
    return (area_amt(b.avg_area, 30, 510, 17, 1700)
            + units_amt(b.units, 46, 2300, 2625) + 26298)


def unit_lighting(b, age):
    return (area_amt(b.avg_area, 30, 33510, 1117, 111700)
            + units_amt(b.units, 84, 4200, 4794) - 215)


def unit_info(b, age):
    return 173522 * r4(32 / b.units)


def unit_fire(b, age):
    return units_amt(b.units, 53, 2650, 3025) + (6028 if age >= 38 else 0) + 31439


def unit_ev_repair(b, age):
    return 601868 * r2(b.floors / 7)


def unit_ev_replace(b, age):
    f = b.floors
    p = 178355 * f if f <= 30 else 178355 * r2(f - 30) + 5350650
    return p + 7003526


def unit_park_repair(b, age):
    return -17 * b.parking + 113301


def unit_park_replace(b, age):
    n = b.parking
    p = -2556 * n if n <= 100 else -2556 * r4(n - 100) - 255600
    return p + 1104978


def unit_exterior(b, age):
    return (area_amt(b.avg_area, 30, 20160, 672, 67200)
            + units_amt(b.units, 144, 7200, 8218)
            + (20142 if age >= 37 else 0) + 1378)


# 項目名: (単価関数, 数量の種類)  数量 units=戸数 / area=建築面積 / ev=EV台数 / park=駐車台数
ITEMS = {
    "屋根防水": (unit_roof, "area"),
    "床防水": (unit_floor, "units"),
    "外壁塗装等": (unit_wall, "units"),
    "鉄部塗装等": (unit_iron, "units"),
    "建具・金物等": (unit_fitting, "units"),
    "共用内部": (unit_inner, "units"),
    "給水設備（管更生・設備補修等）": (unit_water_repair, "units"),
    "給水設備（管取替）": (unit_water_replace, "units"),
    "排水設備（管更生・設備補修等）": (unit_drain_repair, "units"),
    "排水設備（管取替）": (unit_drain_replace, "units"),
    "ガス設備（管取替）": (unit_gas, "units"),
    "空調・換気設備": (unit_hvac, "units"),
    "電灯設備等": (unit_lighting, "units"),
    "情報・通信設備": (unit_info, "units"),
    "消防用設備": (unit_fire, "units"),
    "エレベーター設備（補修）": (unit_ev_repair, "ev"),
    "エレベーター設備（取替）": (unit_ev_replace, "ev"),
    "機械式駐車場設備（補修）": (unit_park_repair, "park"),
    "機械式駐車場設備（一式交換）": (unit_park_replace, "park"),
    "外構・附属設備": (unit_exterior, "units"),
}


def _qty(b, kind):
    return {"units": b.units, "area": b.building_area,
            "ev": b.elevators, "park": b.parking}[kind]


def factor(b):
    return b.price_index * region_factor(b.prefecture)


def estimate_item(name, b, year=0):
    """year 年目（利用年=0）の工事項目の推定修繕工事費（税抜）"""
    fn, kind = ITEMS[name]
    q = _qty(b, kind)
    if q <= 0:
        return 0
    return max(0, round(fn(b, b.age + year) * q * factor(b)))


def temp_parts(b, others_total, year=0):
    """仮設工事を (直接仮設, 共通仮設) に分けて返す"""
    u = b.units
    unit = (area_amt(b.avg_area, 30, 80460, 2682, 268200)
            + units_amt(u, 1052, 52600, 60039)
            + floors_amt(b.floors, 8925, 133875, 168441) + 21305)
    unit *= 1 if u < 100 else (1 / 1.21 if u < 200 else 1 / 1.48)
    direct = round(unit * u * factor(b))
    ratio = 0.092 if u <= 40 else (0.067 if u <= 80 else 0.051)
    return direct, round(others_total * ratio)


def temp_work(b, others_total, year=0):
    """仮設工事 = 直接仮設 + 共通仮設（従来どおりの合計）"""
    direct, common = temp_parts(b, others_total, year)
    return direct + common


# ---------- 工事周期（解説書 表3-1） ----------
def cycles(c):
    """c: 外壁塗装等の周期（12〜15年）。値は繰り返し使う間隔のリスト"""
    wall = [c]
    return {
        "外壁塗装等": wall, "屋根防水": wall, "床防水": wall,
        "建具・金物等": wall, "共用内部": wall, "外構・附属設備": wall,
        "鉄部塗装等": {12: [6], 13: [6, 7], 14: [7], 15: [7, 8]}[c],
        "機械式駐車場設備（補修）": {12: [5], 13: [5, 5, 5, 6],
                                     14: [5, 5, 6, 6], 15: [5, 6, 6, 6]}[c],
        "給水設備（管更生・設備補修等）": [20],
        "排水設備（管更生・設備補修等）": [20],
        "エレベーター設備（補修）": [15],
        "情報・通信設備": [c + 3],   # 要確認：表の抽出が崩れていたため推定
        "空調・換気設備": [c + 8], "電灯設備等": [c + 8],
        "機械式駐車場設備（一式交換）": [c + 8], "消防用設備": [c + 8],
    }


# ---------- 8工種へのグルーピング ----------
WORK_ORDER = ["足場", "外壁", "防水", "鉄部塗装",
              "電気設備", "給排水", "建具", "現場管理"]

WORK_OF = {
    "外壁塗装等": "外壁",
    "屋根防水": "防水",
    "床防水": "防水",
    "鉄部塗装等": "鉄部塗装",
    "電灯設備等": "電気設備",
    "情報・通信設備": "電気設備",
    "消防用設備": "電気設備",
    "空調・換気設備": "電気設備",
    "エレベーター設備（補修）": "電気設備",
    "エレベーター設備（取替）": "電気設備",
    "機械式駐車場設備（補修）": "電気設備",
    "機械式駐車場設備（一式交換）": "電気設備",
    "給水設備（管更生・設備補修等）": "給排水",
    "給水設備（管取替）": "給排水",
    "排水設備（管更生・設備補修等）": "給排水",
    "排水設備（管取替）": "給排水",
    "ガス設備（管取替）": "給排水",
    "建具・金物等": "建具",
    "共用内部": "建具",
    "外構・附属設備": "建具",
}


def work_items(items, direct, common, tax_rate, gross_total):
    """20工種＋仮設を8工種に集約し、税込で按分する（合計は gross_total に一致）"""
    net = {w: 0 for w in WORK_ORDER}
    for name, amount in items.items():
        net[WORK_OF[name]] += amount
    net["足場"] += direct
    net["現場管理"] += common

    gross = {w: round(v * (1 + tax_rate)) for w, v in net.items()}
    diff = gross_total - sum(gross.values())
    if diff and any(gross.values()):
        gross[max(gross, key=gross.get)] += diff  # 端数は最大の工種へ
    return [{"name": w, "amount": gross[w]} for w in WORK_ORDER if gross[w] > 0]


def estimate_schedule(b, wall_cycle=12, first_years=None,
                      once=None, years=40):
    """
    first_years: {項目名: 初回の実施年(0=利用年)}。未指定は周期の最初の値。
    once: {項目名: 実施年}。管取替・ガス・EV取替など1回だけの工事。
          未指定は築30年（給水・排水の管取替は築40年）の年。
    戻り値: [{year, items, temp, subtotal, tax, amount_gross, cost_items}]
      cost_items: 8工種の税込金額 [{name, amount}]  合計は amount_gross と一致する
    """
    first_years = first_years or {}
    once = dict(once or {})
    for name, at in [("給水設備（管取替）", 40), ("排水設備（管取替）", 40),
                     ("ガス設備（管取替）", 30), ("エレベーター設備（取替）", 30)]:
        once.setdefault(name, max(0, at - b.age))

    plan = {y: {} for y in range(years + 1)}
    for name, steps in cycles(wall_cycle).items():
        y, i = first_years.get(name, steps[0]), 0
        while y <= years:
            plan[y][name] = estimate_item(name, b, y)
            y += steps[i % len(steps)]
            i += 1
    for name, y in once.items():
        if y is not None and 0 <= y <= years:
            plan[y][name] = estimate_item(name, b, y)

    out = []
    for y in range(years + 1):
        items = plan[y]
        direct = common = 0
        # 外壁塗装等の年だけ仮設工事を計上
        if "外壁塗装等" in items:
            direct, common = temp_parts(b, sum(items.values()), y)
        temp = direct + common
        sub = sum(items.values()) + temp
        tax = round(sub * TAX)
        gross_total = sub + tax

        out.append({"year": y, "items": items, "temp": temp,
                    "subtotal": sub, "tax": tax, "amount_gross": gross_total,
                    "cost_items": work_items(items, direct, common, TAX, gross_total)})
    return out