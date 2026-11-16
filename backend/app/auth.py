import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pymysql
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import ExpiredSignatureError, JWTError, jwt
from pwdlib import PasswordHash

from app.db.client import get_conn

# app/auth.py から見て、1つ上のプロジェクトルートの .env を読む
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

password_hash = PasswordHash.recommended()

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "環境変数 SECRET_KEY が設定されていません。.env に SECRET_KEY=... を追加してください"
    )
ALGORITHM = "HS256"
TOKEN_HOURS = 8

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


def verify_password(plain: str, hashed: str) -> bool:
    return password_hash.verify(plain, hashed)


def get_password_hash(password: str) -> str:
    return password_hash.hash(password)


def create_access_token(user_id: int, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS)
    payload = {"sub": str(user_id), "role": role, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def current_user(token: str = Depends(oauth2_scheme)) -> dict:
    def err(msg: str):
        return HTTPException(
            status.HTTP_401_UNAUTHORIZED, msg,
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except ExpiredSignatureError:
        raise err("トークンの有効期限が切れています。再度ログインしてください")
    except JWTError:
        raise err("認証情報が無効です。再度ログインしてください")

    user_id = payload.get("sub")
    if user_id is None:
        raise err("認証情報が無効です。再度ログインしてください")

    conn = get_conn()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                "SELECT id, role, company_id, display_name FROM users WHERE id=%s",
                (int(user_id),),
            )
            u = cur.fetchone()
    finally:
        conn.close()
    if not u:
        raise err("認証情報が無効です。再度ログインしてください")
    return u