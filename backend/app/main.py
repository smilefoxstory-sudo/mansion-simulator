import json
import logging
import os
import re
import time
import unicodedata
from collections import defaultdict, deque
from dataclasses import asdict, fields
from typing import Any, Dict, List

from fastapi import Depends, FastAPI, Form, HTTPException, Path, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware
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

logger = logging.getLogger("mansion-simulator")

# ---------------------------------------------------------------
# 本番では docs / redoc / openapi.json を無効化
# 既定は prod（設定漏れでも公開されない）。開発時だけ APP_ENV=dev にする
# ---------------------------------------------------------------
IS_PROD = os.getenv("APP_ENV", "prod") == "prod"

app = FastAPI(
    title="mansion-simulator",
    docs_url=None if IS_PROD else "/docs",
    redoc_url=None if IS_PROD else "/redoc",
    openapi_url=None if IS_PROD else "/openapi.json",
)

# フロントの URL（Azure）とローカル開発用の URL を許可
FRONT_ORIGIN = "https://mansion-simulator-fe-cegaawaphka8bnbx.japaneast-01.azurewebsites.net"

origins = [
    FRONT_ORIGIN,
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
# 追加で許可したい URL があれば、Azure のアプリケーション設定 CORS_ORIGINS にカンマ区切りで登録
extra = os.getenv("CORS_ORIGINS")
if extra:
    origins += [o.strip() for o in extra.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# Host ヘッダーの制限（Azure の設定 ALLOWED_HOSTS にカンマ区切りで登録。未設定なら無効）
# 例: mansion-simulator-be-xxxx.japaneast-01.azurewebsites.net,localhost,127.0.0.1
_allowed_hosts = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]
if _allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    res = await call_next(request)
    res.headers["X-Content-Type-Options"] = "nosniff"
    res.headers["X-Frame-Options"] = "DENY"
    res.headers["Referrer-Policy"] = "no-referrer"
    res.headers["Strict-Transport-Security"] = "max-age=31536000"
    res.headers["Cache-Control"] = "no-store"
    return res


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    # 詳細はログにだけ残し、画面には汎用メッセージを返す
    logger.exception("unhandled error: %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "サーバーエラーが発生しました"})


@app.on_event("startup")
def startup():
    init_db()


# ---------------------------------------------------------------
# 共通：ID の型・範囲
# ---------------------------------------------------------------
CASE_ID = Path(ge=1, le=2_147_483_647)


# ---------------------------------------------------------------
# 自由入力文字列のクリーニング
# 制御文字（NUL・タブ・改行など）、ゼロ幅文字、双方向制御文字、BOM を拒否する。
# 改行は allow_newline=True のときだけ \n を許可する
# ---------------------------------------------------------------
_BAD_CHARS = re.compile(
    r"[\x00-\x09\x0b-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]"
)


def clean_text(v: str, allow_newline: bool = False) -> str:
    v = unicodedata.normalize("NFKC", v).strip()
    if allow_newline:
        v = v.replace("\r\n", "\n")
        target = v.replace("\n", "")
    else:
        target = v
        if "\n" in v or "\r" in v:
            raise ValueError("改行は使えません")
    if _BAD_CHARS.search(target):
        raise ValueError("使用できない文字が含まれています")
    return v


# ---------------------------------------------------------------
# options の検証（想定外の項目・値はエラー）
# ---------------------------------------------------------------
PREFECTURES = {
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
    "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
    "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
    "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
}

# キー名が Input に存在するものだけ適用される（無いキーは既存チェックで弾かれる）
# 値の範囲は仮です。業務ルールに合わせて調整してください。
OPTION_RULES: Dict[str, tuple] = {
    "pref": ("choice", PREFECTURES),
    "units": ("int", 1, 5000),
    "built_year": ("int", 1900, 2100),
    "floors": ("int", 1, 100),
    "building_area": ("float", 0.0001, 1_000_000),
    "total_exclusive_area": ("float", 0.0001, 1_000_000),
    "wall": ("choice", {"tile", "paint"}),
    "corridor": ("choice", {"single", "center", "stairhall"}),
    "base_year": ("int", 1900, 2100),
    "wall_cycle": ("int", 12, 15),
    "start_year": ("int", 2000, 2100),
    "has_tank": ("bool",),
    "all_electric": ("bool",),
    "elevators": ("int", 0, 100),
    "parking": ("int", 0, 10000),
}
MAX_OPTIONS = 50
MAX_STR_LEN = 100
MAX_ABS_NUM = 1_000_000_000_000


def validate_options(options: Dict[str, Any]) -> None:
    if len(options) > MAX_OPTIONS:
        raise HTTPException(422, "options の項目数が多すぎます")

    for key, v in options.items():
        if v is None:
            continue
        rule = OPTION_RULES.get(key)
        if rule is None:
            # ルール未定義の項目は、型と大きさだけ制限する
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                if abs(v) > MAX_ABS_NUM:
                    raise HTTPException(422, f"{key} の値が範囲外です")
                continue
            if isinstance(v, str):
                if len(v) > MAX_STR_LEN:
                    raise HTTPException(422, f"{key} が長すぎます")
                try:
                    clean_text(v)
                except ValueError:
                    raise HTTPException(422, f"{key} に使用できない文字が含まれています")
                continue
            raise HTTPException(422, f"{key} の型が不正です")

        kind = rule[0]
        if kind == "choice":
            if not isinstance(v, str) or v not in rule[1]:
                raise HTTPException(422, f"{key} は選択肢以外の値です")
        elif kind == "bool":
            if not isinstance(v, bool):
                raise HTTPException(422, f"{key} は true / false で指定してください")
        elif kind == "int":
            if isinstance(v, bool) or not isinstance(v, int) or not (rule[1] <= v <= rule[2]):
                raise HTTPException(422, f"{key} は {rule[1]}〜{rule[2]} の整数で指定してください")
        elif kind == "float":
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not (rule[1] <= v <= rule[2]):
                raise HTTPException(422, f"{key} は {rule[1]}〜{rule[2]} の数値で指定してください")


# ---------------------------------------------------------------
# ログインのレート制限（簡易・メモリ内）
# 同一IP＋コードで 60 秒間に 5 回失敗したら 429。
# インスタンスが複数ある場合は共有されないので、その場合は Redis や slowapi を検討
# ---------------------------------------------------------------
LOGIN_MAX_FAILS = 5
LOGIN_WINDOW_SEC = 60
_login_fails: Dict[str, deque] = defaultdict(deque)


def _client_key(request: Request, login_code: str) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")
    return f"{ip}|{login_code}"


def _check_login_rate(key: str) -> None:
    q = _login_fails[key]
    now = time.time()
    while q and now - q[0] > LOGIN_WINDOW_SEC:
        q.popleft()
    if len(q) >= LOGIN_MAX_FAILS:
        raise HTTPException(429, "試行回数が多すぎます。しばらくしてからお試しください")


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
    validate_options(options)

    try:
        inp = base(
            name=name,
            opening_balance=opening_balance,
            annual_fee=annual_fee,
            **options,
        )
        r = simulate(inp)
    except Exception:
        # 内部の例外文は外に出さず、ログにだけ残す
        logger.exception("simulate failed")
        raise HTTPException(422, "入力値でシミュレーションできませんでした。入力内容を確認してください")
    return name, inp, r


@app.post("/login")
def login(
    request: Request,
    login_code: str = Form(..., min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$"),
    password: str = Form(..., min_length=1, max_length=128),
):
    key = _client_key(request, login_code)
    _check_login_rate(key)

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
        _login_fails[key].append(time.time())
        raise HTTPException(401, "IDまたはパスワードが違います")

    _login_fails.pop(key, None)
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
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=100)
    opening_balance: int = Field(ge=0, le=100_000_000_000)
    annual_fee: int = Field(ge=0, le=100_000_000_000)
    shared: bool = False
    # Input のその他の項目を上書きしたい場合に指定（任意）。中身は validate_options で検証
    options: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return clean_text(v)


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
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=100)
    opening_balance: int = Field(ge=0, le=100_000_000_000)
    annual_fee: int = Field(ge=0, le=100_000_000_000)
    # 省略すると共有設定は変更しない
    shared: bool | None = None
    options: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return clean_text(v)


@app.put("/cases/{case_id}")
def update_case(
    body: CaseUpdateBody,
    case_id: int = CASE_ID,
    u: dict = Depends(current_user),
):
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
def delete_case(case_id: int = CASE_ID, u: dict = Depends(current_user)):
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
def case_result(case_id: int = CASE_ID, u: dict = Depends(current_user)):
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
        except Exception:
            logger.exception("simulate_with_plan failed: case_id=%s", case_id)
            raise HTTPException(422, "シミュレーションできませんでした")
    finally:
        conn.close()
    return {"name": case["name"], "input": data, **r}


@app.post("/cases/{case_id}/simulate")
def simulate_case(case_id: int = CASE_ID, u: dict = Depends(current_user)):
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
def compare(case_id: int = CASE_ID, u: dict = Depends(current_user)):
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
    model_config = ConfigDict(extra="forbid", strict=True)

    shared: bool


@app.put("/cases/{case_id}/share")
def set_share(body: ShareBody, case_id: int = CASE_ID, u: dict = Depends(current_user)):
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
    model_config = ConfigDict(extra="forbid", strict=True)

    # ステータスの選択肢が決まっているなら Literal["未対応", ...] にするとより厳密になる
    status: str = Field(min_length=1, max_length=50)
    memo: str | None = Field(default=None, max_length=1000)

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        return clean_text(v)

    @field_validator("memo")
    @classmethod
    def _memo(cls, v: str | None) -> str | None:
        # メモは改行を許可する
        return None if v is None else clean_text(v, allow_newline=True)


@app.put("/cases/{case_id}/status")
def set_status(body: StatusBody, case_id: int = CASE_ID, u: dict = Depends(current_user)):
    conn = get_conn()
    try:
        case = load_case(conn, case_id)
        if not case:
            raise HTTPException(404, "案件が見つかりません")
        if u["role"] != "bank" or case["shared"] != 1:
            raise HTTPException(403, "銀行ユーザーのみ、共有済み案件で更新できます")
        with conn.cursor() as cur:
            cur.exec        with conn.cursor() as cur:
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
    model_config = ConfigDict(extra="forbid", strict=True)

    year: int = Field(ge=1900, le=2200)
    amount_gross: int = Field(ge=0, le=100_000_000_000)
    note: str | None = Field(default=None, max_length=200)

    @field_validator("note")
    @classmethod
    def _note(cls, v: str | None) -> str | None:
        return None if v is None else clean_text(v)


class FeeItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    from_year: int = Field(ge=1900, le=2200)
    fee: int = Field(ge=0, le=100_000_000_000)


class PlanBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str | None = Field(default=None, max_length=100)
    works: List[WorkItem] = Field(default_factory=list, max_length=200)

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        return None if v is None else clean_text(v)


class FeesBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    fees: List[FeeItem] = Field(default_factory=list, max_length=200)


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
def put_plan(body: PlanBody, case_id: int = CASE_ID, u: dict = Depends(current_user)):
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
def delete_plan(case_id: int = CASE_ID, u: dict = Depends(current_user)):
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
def put_fees(body: FeesBody, case_id: int = CASE_ID, u: dict = Depends(current_user)):
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