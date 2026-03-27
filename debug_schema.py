import sqlite3
conn = sqlite3.connect("navidrome.db")
cur = conn.cursor()

# Find the tracks table
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("Tables:", tables)

# Check media_file schema
for t in ["media_file", "song", "track"]:
    if t in tables:
        cur.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{t}'")
        r = cur.fetchone()
        if r:
            print(f"\n=== {t} ===")
            print(r[0])

# Sample a few tracks
if "media_file" in tables:
    cur.execute("SELECT * FROM media_file LIMIT 1")
    cols = [d[0] for d in cur.description]
    print("\n=== media_file columns ===")
    for c in cols:
        print(f"  {c}")

conn.close()
