import os
from pathlib import Path

import pymysql
from dotenv import load_dotenv

# backend/.env を、実行場所に関係なく読み込む
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

HOST = os.getenv("DB_HOST", "")
USER = os.getenv("DB_USER", "")
PASSWORD = os.getenv("DB_PASSWORD", "")
DB = os.getenv("DB_NAME", "mansion")
SSL_CA = os.getenv("DB_SSL_CA", "")


def _ssl():
    return {"ca": SSL_CA} if SSL_CA else {}


def get_conn(db: str | None = DB):
    return pymysql.connect(
        host=HOST, user=USER, password=PASSWORD, database=db,
        charset="utf8mb4", ssl=_ssl(), autocommit=False,
    )


CASE_FEES_DDL = """
CREATE TABLE IF NOT EXISTS case_fees (
  case_id INT NOT NULL,
  from_year INT NOT NULL,
  fee BIGINT NOT NULL,
  PRIMARY KEY (case_id, from_year),
  FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE
)
"""


def init_db() -> None:
    conn = get_conn(None)
    with conn.cursor() as cur:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS {DB} "
            "DEFAULT CHARACTER SET utf8mb4"
        )
    conn.commit()
    conn.close()

    sql = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    conn = get_conn()
    with conn.cursor() as cur:
        for s in statements:
            cur.execute(s)
        # 積立金の増額予定（案件ごと）。cases の作成後に作る
        cur.execute(CASE_FEES_DDL)
    conn.commit()
    conn.close()