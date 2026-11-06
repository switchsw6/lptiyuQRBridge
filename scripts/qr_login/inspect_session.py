"""Read the on-device session stores left by a successful login (values masked)."""
import sqlite3
import sys
from pathlib import Path

CASE = Path(__file__).resolve().parents[2] / ".work" / "qr-login-20261107"


def describe(path: Path):
    print(f"### {path.name} ({path.stat().st_size} bytes)")
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    tables = [row[0] for row in db.execute("select name from sqlite_master where type='table'")]
    print("   tables:", tables)
    for table in tables:
        columns = [row[1] for row in db.execute(f"pragma table_info('{table}')")]
        try:
            count = db.execute(f"select count(*) from '{table}'").fetchone()[0]
        except sqlite3.DatabaseError as exc:
            print(f"   {table}: unreadable ({exc})")
            continue
        print(f"   {table}: columns={columns} rows={count}")
        if count and count <= 40 and "name" in columns and "value" in columns:
            for name, value in db.execute(f"select name, value from '{table}'"):
                raw = value if isinstance(value, bytes) else str(value).encode()
                text = raw.decode("utf-8", "replace")
                shown = text if len(text) <= 8 else text[:4] + "…" + text[-2:]
                print(f"      {name} = {shown} (len {len(text)})")
    db.close()


for name in sys.argv[1:]:
    path = CASE / name
    if path.exists():
        describe(path)
    else:
        print(f"missing {path}")
