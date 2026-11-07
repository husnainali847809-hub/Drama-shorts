import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / os.getenv("OUTPUT_DIR", "output")
DOWNLOAD_DIR = ROOT / "downloads"
MUSIC_DIR = ROOT / "assets" / "music"
DB_PATH = ROOT / "history.sqlite3"
CLIP_MIN_SECONDS = int(os.getenv("CLIP_MIN_SECONDS", "120"))
CLIP_MAX_SECONDS = int(os.getenv("CLIP_MAX_SECONDS", "180"))
MAX_SOURCE_MB = int(os.getenv("MAX_SOURCE_MB", "800"))
IA_SEARCH_ROWS = int(os.getenv("IA_SEARCH_ROWS", "100"))
CLOUDINARY_FOLDER = os.getenv("CLOUDINARY_FOLDER", "movie-reels-publisher").strip()

if CLIP_MIN_SECONDS < 120 or CLIP_MAX_SECONDS > 180 or CLIP_MIN_SECONDS > CLIP_MAX_SECONDS:
    raise ValueError("Clip duration must stay between 120 and 180 seconds.")
for folder in (OUTPUT_DIR, DOWNLOAD_DIR, MUSIC_DIR):
    folder.mkdir(parents=True, exist_ok=True)
