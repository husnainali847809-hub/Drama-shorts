import sqlite3
from config import DB_PATH

def connect():
    db = sqlite3.connect(DB_PATH)
    db.execute("""CREATE TABLE IF NOT EXISTS used_items (
        identifier TEXT PRIMARY KEY,
        used_at TEXT DEFAULT CURRENT_TIMESTAMP,
        clip_path TEXT,
        facebook_video_id TEXT
    )""")
    return db

def was_used(identifier: str) -> bool:
    with connect() as db:
        return db.execute(
            "SELECT 1 FROM used_items WHERE identifier = ?", (identifier,)
        ).fetchone() is not None

def mark_used(identifier: str, clip_path: str, facebook_video_id: str = ""):
    with connect() as db:
        db.execute(
            "INSERT OR REPLACE INTO used_items(identifier, clip_path, facebook_video_id) VALUES (?, ?, ?)",
            (identifier, clip_path, facebook_video_id),
        )
