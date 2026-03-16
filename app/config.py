import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES_DIR = os.path.join(BASE, "pages")
DECKS_DIR = os.path.join(BASE, "decks")
META_FILE = os.path.join(BASE, "meta.json")
DECKS_META = os.path.join(BASE, "decks_meta.json")

os.makedirs(PAGES_DIR, exist_ok=True)
os.makedirs(DECKS_DIR, exist_ok=True)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "password")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB
