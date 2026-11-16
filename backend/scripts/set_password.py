import sys

import pymysql
from pwdlib import PasswordHash

from app.db.client import get_conn

login_code, password = sys.argv[1], sys.argv[2]
hashed = PasswordHash.recommended().hash(password)

conn = get_conn()
try:
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            "UPDATE users SET password_hash=%s WHERE login_code=%s",
            (hashed, login_code),
        )
        print("更新件数:", cur.rowcount)
    conn.commit()
finally:
    conn.close()