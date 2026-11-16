import pymysql

from app.compare import run_and_save_prediction
from app.db.client import get_conn


def main() -> None:
    conn = get_conn()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("SELECT id FROM cases ORDER BY id")
            ids = [row["id"] for row in cur.fetchall()]
    finally:
        conn.close()

    for cid in ids:
        r = run_and_save_prediction(cid)
        print(cid, r["judge"] if r else None, r["shortage"] if r else None)


if __name__ == "__main__":
    main()