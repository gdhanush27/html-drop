import os
import json
import shutil
from datetime import datetime, timezone

from app.config import META_FILE, DECKS_META, PAGES_DIR, DECKS_DIR

# ---------------------------------------------------------------------------
# meta helpers — pages
# ---------------------------------------------------------------------------

def load_meta():
    if not os.path.exists(META_FILE):
        return {}
    with open(META_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_meta(m):
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2)

def get_page_meta(page_id):
    return load_meta().get(page_id)

def upsert_meta(page_id, **kwargs):
    m = load_meta()
    if page_id not in m:
        m[page_id] = {"hits": 0, "blocked": False,
                      "created": datetime.now(timezone.utc).isoformat(), "size": 0}
    m[page_id].update(kwargs)
    save_meta(m)

def inc_hits(page_id):
    m = load_meta()
    if page_id in m:
        m[page_id]["hits"] = m[page_id].get("hits", 0) + 1
        save_meta(m)

def delete_page(page_id):
    path = os.path.join(PAGES_DIR, f"{page_id}.html")
    if os.path.exists(path):
        os.remove(path)
    m = load_meta()
    m.pop(page_id, None)
    save_meta(m)

# ---------------------------------------------------------------------------
# meta helpers — decks
# ---------------------------------------------------------------------------

def load_decks_meta():
    if not os.path.exists(DECKS_META):
        return {}
    with open(DECKS_META, "r", encoding="utf-8") as f:
        return json.load(f)

def save_decks_meta(m):
    with open(DECKS_META, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2)

def get_deck_meta(deck_id):
    return load_decks_meta().get(deck_id)

def upsert_deck_meta(deck_id, **kwargs):
    m = load_decks_meta()
    if deck_id not in m:
        m[deck_id] = {
            "hits": 0,
            "blocked": False,
            "created": datetime.now(timezone.utc).isoformat(),
            "slide_count": 0,
            "title": "Untitled Deck",
        }
    m[deck_id].update(kwargs)
    save_decks_meta(m)

def inc_deck_hits(deck_id):
    m = load_decks_meta()
    if deck_id in m:
        m[deck_id]["hits"] = m[deck_id].get("hits", 0) + 1
        save_decks_meta(m)

def delete_deck(deck_id):
    deck_dir = os.path.join(DECKS_DIR, deck_id)
    if os.path.isdir(deck_dir):
        shutil.rmtree(deck_dir)
    m = load_decks_meta()
    m.pop(deck_id, None)
    save_decks_meta(m)
