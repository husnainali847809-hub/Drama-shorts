import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / os.getenv("OUTPUT_DIR", "output")
DOWNLOAD_DIR = ROOT / "downloads"
MUSIC_DIR = ROOT / "assets" / "music"
DB_PATH = ROOT / "history.sqlite3"
CLIP_MIN_SECONDS = int(os.getenv("CLIP_MIN_SECONDS", "85"))
CLIP_MAX_SECONDS = int(os.getenv("CLIP_MAX_SECONDS", "89"))
MAX_SOURCE_MB = int(os.getenv("MAX_SOURCE_MB", "800"))
IA_SEARCH_ROWS = max(250, min(int(os.getenv("IA_SEARCH_ROWS", "250")), 500))
IA_SEARCH_PAGES = max(1, min(int(os.getenv("IA_SEARCH_PAGES", "2")), 5))
CLOUDINARY_FOLDER = os.getenv("CLOUDINARY_FOLDER", "movie-reels-publisher").strip()

if CLIP_MIN_SECONDS < 60 or CLIP_MAX_SECONDS > 90 or CLIP_MIN_SECONDS > CLIP_MAX_SECONDS:
    raise ValueError("Facebook Reel clip duration must be between 60 and 90 seconds.")
for folder in (OUTPUT_DIR, DOWNLOAD_DIR, MUSIC_DIR):
    folder.mkdir(parents=True, exist_ok=True)
