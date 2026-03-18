"""
htmldrop — single-file Flask HTML sharing app
  /              upload / paste HTML
  /p/<id>        view shared page
  /p/<id>/source remix in editor
  /deck          create a slideshow from multiple HTML pages
  /d/<id>        view slideshow deck
  /d/<id>/edit   edit/manage deck slides
  /admin         admin dashboard (password protected)
  /admin/action  bulk/single actions (POST)
"""
import os, uuid, json, re
from datetime import datetime, timezone
from functools import wraps

# load .env file if present (no third-party dependency)
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as _ef:
        for _line in _ef:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            k, v = _line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from flask import Flask, request, redirect, url_for, abort, send_from_directory, Response, session, render_template
from werkzeug.security import generate_password_hash, check_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # bumped for multi-slide uploads

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per minute"],
    storage_uri="memory://",
)

BASE       = os.path.dirname(os.path.abspath(__file__))
PAGES_DIR  = os.path.join(BASE, "pages")
DECKS_DIR  = os.path.join(BASE, "decks")
META_FILE  = os.path.join(BASE, "meta.json")
DECKS_META = os.path.join(BASE, "decks_meta.json")
os.makedirs(PAGES_DIR, exist_ok=True)
os.makedirs(DECKS_DIR, exist_ok=True)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")  # change this in production!
SETTINGS_FILE = os.path.join(BASE, "settings.json")
USERS_FILE = os.path.join(BASE, "users.json")

# ---------------------------------------------------------------------------
# settings helpers
# ---------------------------------------------------------------------------

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {"freeze_pages": "off", "freeze_decks": "off", "freeze_reg": False, "pinned": None}
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        s = json.load(f)
    s.setdefault("pinned", None)
    s.setdefault("freeze_reg", False)
    # migrate old boolean format to tri-state
    for key in ("freeze_pages", "freeze_decks"):
        if isinstance(s.get(key), bool):
            s[key] = "all" if s[key] else "off"
        elif s.get(key) not in ("off", "anon", "all"):
            s[key] = "off"
    s.pop("pinned_pages", None)
    s.pop("pinned_decks", None)
    return s

def save_settings(s):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)

# ---------------------------------------------------------------------------
# user helpers
# ---------------------------------------------------------------------------

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_users(u):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(u, f, indent=2)

def create_user(email, password):
    users = load_users()
    if email in users:
        return False
    users[email] = {
        "password_hash": generate_password_hash(password),
        "created": datetime.now(timezone.utc).isoformat(),
    }
    save_users(users)
    return True

def verify_user(email, password):
    users = load_users()
    user = users.get(email)
    if not user:
        return False
    return check_password_hash(user["password_hash"], password)

def update_user(email, **fields):
    """Update arbitrary fields on a user record and persist to users.json."""
    users = load_users()
    if email not in users:
        return
    users[email].update(fields)
    save_users(users)

def get_current_user():
    return session.get("user_email")

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_email"):
            return redirect(url_for("user_login"))
        return f(*args, **kwargs)
    return wrapper

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
    s = load_settings()
    p = s.get("pinned")
    if p and p.get("type") == "page" and p.get("id") == page_id:
        s["pinned"] = None
        save_settings(s)

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
        import shutil
        shutil.rmtree(deck_dir)
    m = load_decks_meta()
    m.pop(deck_id, None)
    save_decks_meta(m)
    s = load_settings()
    p = s.get("pinned")
    if p and p.get("type") == "deck" and p.get("id") == deck_id:
        s["pinned"] = None
        save_settings(s)

# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper

def _admin_redirect():
    tab = request.form.get("_tab", "")
    base = url_for("admin")
    if tab in ("pages", "decks"):
        return redirect(f"{base}#{tab}")
    return redirect(base)

# ---------------------------------------------------------------------------
# template rendering helpers
# ---------------------------------------------------------------------------

def render_home():
    settings = load_settings()
    pinned = settings.get("pinned")
    pinned_ctx = None
    if pinned and isinstance(pinned, dict):
        p_type = pinned.get("type")
        p_id = pinned.get("id", "")
        p_name = pinned.get("name", "").strip()
        if p_type == "page":
            info = load_meta().get(p_id)
            if info and not info.get("blocked") and os.path.exists(os.path.join(PAGES_DIR, f"{p_id}.html")):
                safe_name = (p_name or p_id).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                pinned_ctx = {"type": "page", "name": safe_name, "url": f"/p/{p_id}", "path": f"/p/{p_id}"}
        elif p_type == "deck":
            info = load_decks_meta().get(p_id)
            if info and not info.get("blocked") and os.path.isdir(os.path.join(DECKS_DIR, p_id)):
                safe_name = (p_name or info.get("title") or "Untitled").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                pinned_ctx = {"type": "deck", "name": safe_name, "url": f"/d/{p_id}", "path": f"/d/{p_id}"}
    return render_template("home.html", active_nav="home", pinned=pinned_ctx)


def error_page(code, title, subtitle, detail, show_home=True):
    return render_template("error.html", code=code, title=title,
                           subtitle=subtitle, detail=detail,
                           show_home=show_home), code


def _is_frozen(mode):
    """Check if a freeze mode blocks the current user."""
    if mode == "all":
        return True
    if mode == "anon" and not get_current_user():
        return True
    return False

def render_index(error="", page_id="", prefill="", host=""):
    error_html = ""
    fp = load_settings().get("freeze_pages", "off")
    if error:
        error_html = f'<div class="error">&#9888; {error}</div>'
    elif fp == "all":
        error_html = '<div class="error">&#10052; Uploading new pages is currently disabled.</div>'
    elif fp == "anon" and not get_current_user():
        error_html = '<div class="error">&#10052; Uploading is restricted to logged-in users. <a href="/login">Log in</a> to continue.</div>'
    result_html = ""
    if page_id:
        url = f"{host}p/{page_id}"
        result_html = (f'<div class="result">'
                       f'<div><div class="rlabel">&#10003; your page is live</div>'
                       f'<div class="rurl" id="rurl">{url}</div></div>'
                       f'<button class="copy-btn" onclick="copyUrl()">copy link</button>'
                       f'</div>')
    safe = prefill.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return render_template("page.html", active_nav="page",
                           error_html=error_html, result_html=result_html,
                           prefill=safe)


def render_deck_page(error="", deck_id="", host=""):
    error_html = ""
    fd = load_settings().get("freeze_decks", "off")
    if error:
        error_html = f'<div class="error">&#9888; {error}</div>'
    elif fd == "all":
        error_html = '<div class="error">&#10052; Creating new decks is currently disabled.</div>'
    elif fd == "anon" and not get_current_user():
        error_html = '<div class="error">&#10052; Deck creation is restricted to logged-in users. <a href="/login">Log in</a> to continue.</div>'
    result_html = ""
    if deck_id:
        url = f"{host}d/{deck_id}"
        result_html = (f'<div class="result">'
                       f'<div><div class="rlabel">&#10003; your deck is live</div>'
                       f'<div class="rurl" id="rurl">{url}</div></div>'
                       f'<button class="copy-btn" onclick="copyUrl()">copy link</button>'
                       f'</div>')
    return render_template("deck.html", active_nav="deck",
                           error_html=error_html, result_html=result_html)


def build_deck_viewer(deck_id, slides, title):
    """Build a self-contained full-screen slide viewer."""
    slides_json = json.dumps([{"title": s["title"], "html": s["html"]} for s in slides])
    slides_json = slides_json.replace("</", "<\\/")
    return render_template("deck_viewer.html", title=title, slides_json=slides_json)


def build_admin_page(meta, flash_msg=None, flash_type="ok"):
    pages = []
    for pid, info in meta.items():
        if not os.path.exists(os.path.join(PAGES_DIR, f"{pid}.html")):
            continue
        pages.append({**info, "id": pid})
    pages.sort(key=lambda p: p.get("created", ""), reverse=True)

    total       = len(pages)
    total_hits  = sum(p.get("hits", 0) for p in pages)
    blocked_n   = sum(1 for p in pages if p.get("blocked"))
    max_hits    = max((p.get("hits", 0) for p in pages), default=1) or 1

    decks_meta = load_decks_meta()
    deck_list = []
    for did, dinfo in decks_meta.items():
        if not os.path.isdir(os.path.join(DECKS_DIR, did)):
            continue
        deck_list.append({**dinfo, "id": did})
    deck_list.sort(key=lambda d: d.get("created", ""), reverse=True)

    total_decks     = len(deck_list)
    total_deck_hits = sum(d.get("hits", 0) for d in deck_list)
    blocked_decks   = sum(1 for d in deck_list if d.get("blocked"))
    max_deck_hits   = max((d.get("hits", 0) for d in deck_list), default=1) or 1

    def fmt_date(iso):
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return (iso or "\u2014")[:16]

    def fmt_size(b):
        if b < 1024: return f"{b} B"
        if b < 1048576: return f"{b/1024:.1f} KB"
        return f"{b/1048576:.1f} MB"

    flash_html = ""
    if flash_msg:
        cls = "flash-ok" if flash_type == "ok" else "flash-err"
        flash_html = f'<div class="flash {cls}">{flash_msg}</div>'

    settings = load_settings()
    freeze_pages = settings.get("freeze_pages", False)
    freeze_decks = settings.get("freeze_decks", False)
    pinned_pages = set()
    pinned_decks = set()
    pinned = settings.get("pinned")
    pinned_name = ""
    if pinned and isinstance(pinned, dict):
        pinned_name = pinned.get("name", "")
        if pinned.get("type") == "page":
            pinned_pages.add(pinned.get("id", ""))
        elif pinned.get("type") == "deck":
            pinned_decks.add(pinned.get("id", ""))

    # build page rows HTML
    if not pages:
        rows_html = '<tr class="page-empty-row"><td colspan="8"><div class="empty"><span class="empty-icon">&#128237;</span>No pages yet. <a href="/">Share your first page &rarr;</a></div></td></tr>'
    else:
        rows = []
        for p in pages:
            pid     = p["id"]
            hits    = p.get("hits", 0)
            size    = p.get("size", 0)
            blocked = p.get("blocked", False)
            created = p.get("created", "")
            owner   = p.get("owner", "")
            safe_owner = owner.replace('&','&amp;').replace('"','&quot;').replace('<','&lt;').replace('>','&gt;') if owner else ''
            pct     = int(hits / max_hits * 100)
            badge   = (f'<span class="bdg bdg-off"><span class="bdg-dot"></span>blocked</span>'
                       if blocked else
                       f'<span class="bdg bdg-on"><span class="bdg-dot"></span>active</span>')
            is_pinned = pid in pinned_pages
            safe_pin_name = pinned_name.replace('&','&amp;').replace('"','&quot;').replace('<','&lt;').replace('>','&gt;') if is_pinned else ''
            pinned_badge = f'<span class="bdg bdg-pin" title="Pinned to homepage">&#9733; pinned</span>' if is_pinned else ''
            block_btn = (
                f'<button class="act ok" onclick="doAction(\'unblock\',[\'{pid}\'])">unblock</button>'
                if blocked else
                f'<button class="act warn" onclick="doAction(\'block\',[\'{pid}\'])">block</button>'
            )
            pin_btn = (
                f'<form method="POST" action="/admin/pin" style="display:inline-flex;align-items:center;gap:4px"><input type="hidden" name="type" value="page"/><input type="hidden" name="id" value="{pid}"/><input type="hidden" name="action" value="rename"/><input type="text" name="name" value="{safe_pin_name}" placeholder="Hero name" maxlength="80" style="width:90px;font-family:var(--mono);font-size:.65rem;padding:3px 6px;background:var(--bg);border:1px solid var(--border);border-radius:3px;color:var(--text);outline:none;"/><button type="submit" class="act" title="Save hero name">&#10003;</button></form>'
                f'<form method="POST" action="/admin/pin" style="display:inline"><input type="hidden" name="type" value="page"/><input type="hidden" name="id" value="{pid}"/><input type="hidden" name="action" value="unpin"/><button type="submit" class="act ok" title="Unpin from homepage">&#9733; unpin</button></form>'
                if is_pinned else
                f'<form method="POST" action="/admin/pin" style="display:inline-flex;align-items:center;gap:4px"><input type="hidden" name="type" value="page"/><input type="hidden" name="id" value="{pid}"/><input type="hidden" name="action" value="pin"/><input type="text" name="name" placeholder="Hero name" maxlength="80" style="width:90px;font-family:var(--mono);font-size:.65rem;padding:3px 6px;background:var(--bg);border:1px solid var(--border);border-radius:3px;color:var(--text);outline:none;"/><button type="submit" class="act info" title="Pin to homepage">&#9734; pin</button></form>'
            )
            block_popup = (
                f'<button class="ap-item ap-ok" onclick="doAction(\'unblock\',[\'{pid}\']);closePopup()">&#8593; unblock</button>'
                if blocked else
                f'<button class="ap-item ap-warn" onclick="doAction(\'block\',[\'{pid}\']);closePopup()">&#8856; block</button>'
            )
            pin_popup = (
                f'<form method="POST" action="/admin/pin" class="ap-pin-form"><input type="hidden" name="type" value="page"/><input type="hidden" name="id" value="{pid}"/><input type="hidden" name="action" value="rename"/><input type="text" name="name" value="{safe_pin_name}" placeholder="Hero name" maxlength="80" class="ap-pin-input"/><button type="submit" class="ap-item ap-ok">&#10003; save name</button></form>'
                f'<form method="POST" action="/admin/pin" style="display:contents"><input type="hidden" name="type" value="page"/><input type="hidden" name="id" value="{pid}"/><input type="hidden" name="action" value="unpin"/><button type="submit" class="ap-item ap-ok">&#9733; unpin</button></form>'
                if is_pinned else
                f'<form method="POST" action="/admin/pin" class="ap-pin-form"><input type="hidden" name="type" value="page"/><input type="hidden" name="id" value="{pid}"/><input type="hidden" name="action" value="pin"/><input type="text" name="name" placeholder="Hero name" maxlength="80" class="ap-pin-input"/><button type="submit" class="ap-item ap-info">&#9734; pin to home</button></form>'
            )
            rows.append(
                f'<tr id="row-{pid}" class="page-row {"is-blocked" if blocked else ""}"'
                f' data-id="{pid}" data-hits="{hits}" data-size="{size}"'
                f' data-status="{"blocked" if blocked else "active"}" data-created="{created}"'
                f' data-owner="{safe_owner}">'
                f'<td><input type="checkbox" class="cb row-cb" value="{pid}" onchange="updateBulk()"/></td>'
                f'<td><a class="pid" href="/p/{pid}" target="_blank">{pid}</a></td>'
                f'<td class="ts owner-cell" style="color:var(--info);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{safe_owner}">{safe_owner or "<span style=color:var(--muted2)>anon</span>"}</td>'
                f'<td class="ts">{fmt_date(created)}</td>'
                f'<td class="sz">{fmt_size(size)}</td>'
                f'<td><div class="hits-bar"><span class="hits-val">{hits:,}</span>'
                f'<div class="hits-track"><div class="hits-fill" style="width:{pct}%"></div></div></div></td>'
                f'<td>{badge} {pinned_badge}</td>'
                f'<td>'
                f'<div class="acts-desktop">'
                f'<a class="act" href="/p/{pid}/source">source</a>'
                f'{pin_btn}'
                f'{block_btn}'
                f'<button class="act danger" onclick="confirmDelete([&quot;{pid}&quot;])">delete</button>'
                f'</div>'
                f'<div class="acts-mobile">'
                f'<div class="act-trigger">'
                f'<button type="button" class="act-dots" onclick="togglePopup(this)" title="Actions">&#8943;</button>'
                f'<div class="act-popup">'
                f'<a class="ap-item" href="/p/{pid}/source">&#128196; view source</a>'
                f'<div class="ap-sep"></div>'
                f'{pin_popup}'
                f'<div class="ap-sep"></div>'
                f'{block_popup}'
                f'<div class="ap-sep"></div>'
                f'<button class="ap-item ap-danger" onclick="confirmDelete([\'{pid}\']);closePopup()">&#10005; delete</button>'
                f'</div></div></div>'
                f'</td></tr>'
            )
        rows_html = "\n".join(rows)

    # build deck rows HTML
    if not deck_list:
        deck_rows_html = '<tr class="deck-empty-row"><td colspan="9"><div class="empty"><span class="empty-icon">&#9707;</span>No decks yet. <a href="/deck">Create your first deck &rarr;</a></div></td></tr>'
    else:
        deck_rows = []
        for d in deck_list:
            did      = d["id"]
            dtitle   = d.get("title", "Untitled")
            dslides  = d.get("slide_count", 0)
            dcreated = d.get("created", "")
            dhits    = d.get("hits", 0)
            dblocked = d.get("blocked", False)
            downer   = d.get("owner", "")
            safe_downer = downer.replace('&','&amp;').replace('"','&quot;').replace('<','&lt;').replace('>','&gt;') if downer else ''
            dpct     = int(dhits / max_deck_hits * 100)
            dbadge   = (f'<span class="bdg bdg-off"><span class="bdg-dot"></span>blocked</span>'
                        if dblocked else
                        f'<span class="bdg bdg-on"><span class="bdg-dot"></span>active</span>')
            is_deck_pinned = did in pinned_decks
            safe_dpin_name = pinned_name.replace('&','&amp;').replace('"','&quot;').replace('<','&lt;').replace('>','&gt;') if is_deck_pinned else ''
            dpinned_badge = f'<span class="bdg bdg-pin" title="Pinned to homepage">&#9733; pinned</span>' if is_deck_pinned else ''
            dblock_btn = (
                f'<button class="act ok" onclick="doDeckAction(\'unblock\',[\'{did}\'])">unblock</button>'
                if dblocked else
                f'<button class="act warn" onclick="doDeckAction(\'block\',[\'{did}\'])">block</button>'
            )
            dpin_btn = (
                f'<form method="POST" action="/admin/pin" style="display:inline-flex;align-items:center;gap:4px"><input type="hidden" name="type" value="deck"/><input type="hidden" name="id" value="{did}"/><input type="hidden" name="action" value="rename"/><input type="text" name="name" value="{safe_dpin_name}" placeholder="Hero name" maxlength="80" style="width:90px;font-family:var(--mono);font-size:.65rem;padding:3px 6px;background:var(--bg);border:1px solid var(--border);border-radius:3px;color:var(--text);outline:none;"/><button type="submit" class="act" title="Save hero name">&#10003;</button></form>'
                f'<form method="POST" action="/admin/pin" style="display:inline"><input type="hidden" name="type" value="deck"/><input type="hidden" name="id" value="{did}"/><input type="hidden" name="action" value="unpin"/><button type="submit" class="act ok" title="Unpin from homepage">&#9733; unpin</button></form>'
                if is_deck_pinned else
                f'<form method="POST" action="/admin/pin" style="display:inline-flex;align-items:center;gap:4px"><input type="hidden" name="type" value="deck"/><input type="hidden" name="id" value="{did}"/><input type="hidden" name="action" value="pin"/><input type="text" name="name" placeholder="Hero name" maxlength="80" style="width:90px;font-family:var(--mono);font-size:.65rem;padding:3px 6px;background:var(--bg);border:1px solid var(--border);border-radius:3px;color:var(--text);outline:none;"/><button type="submit" class="act info" title="Pin to homepage">&#9734; pin</button></form>'
            )
            dblock_popup = (
                f'<button class="ap-item ap-ok" onclick="doDeckAction(\'unblock\',[\'{did}\']);closePopup()">&#8593; unblock</button>'
                if dblocked else
                f'<button class="ap-item ap-warn" onclick="doDeckAction(\'block\',[\'{did}\']);closePopup()">&#8856; block</button>'
            )
            dpin_popup = (
                f'<form method="POST" action="/admin/pin" class="ap-pin-form"><input type="hidden" name="type" value="deck"/><input type="hidden" name="id" value="{did}"/><input type="hidden" name="action" value="rename"/><input type="text" name="name" value="{safe_dpin_name}" placeholder="Hero name" maxlength="80" class="ap-pin-input"/><button type="submit" class="ap-item ap-ok">&#10003; save name</button></form>'
                f'<form method="POST" action="/admin/pin" style="display:contents"><input type="hidden" name="type" value="deck"/><input type="hidden" name="id" value="{did}"/><input type="hidden" name="action" value="unpin"/><button type="submit" class="ap-item ap-ok">&#9733; unpin</button></form>'
                if is_deck_pinned else
                f'<form method="POST" action="/admin/pin" class="ap-pin-form"><input type="hidden" name="type" value="deck"/><input type="hidden" name="id" value="{did}"/><input type="hidden" name="action" value="pin"/><input type="text" name="name" placeholder="Hero name" maxlength="80" class="ap-pin-input"/><button type="submit" class="ap-item ap-info">&#9734; pin to home</button></form>'
            )
            safe_title = dtitle.replace('&','&amp;').replace('"','&quot;').replace('<','&lt;').replace('>','&gt;')
            deck_rows.append(
                f'<tr id="drow-{did}" class="deck-row {"is-blocked" if dblocked else ""}"'
                f' data-id="{did}" data-title="{safe_title}" data-hits="{dhits}"'
                f' data-slides="{dslides}" data-status="{"blocked" if dblocked else "active"}"'
                f' data-created="{dcreated}" data-owner="{safe_downer}">'
                f'<td><input type="checkbox" class="cb deck-cb" value="{did}" onchange="updateDeckBulk()"/></td>'
                f'<td><a class="pid" href="/d/{did}" target="_blank">{did}</a></td>'
                f'<td style="color:var(--text);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{dtitle}</td>'
                f'<td class="ts owner-cell" style="color:var(--info);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{safe_downer}">{safe_downer or "<span style=color:var(--muted2)>anon</span>"}</td>'
                f'<td class="ts">{fmt_date(dcreated)}</td>'
                f'<td style="color:var(--info)">{dslides}</td>'
                f'<td><div class="hits-bar"><span class="hits-val">{dhits:,}</span>'
                f'<div class="hits-track"><div class="hits-fill" style="width:{dpct}%"></div></div></div></td>'
                f'<td>{dbadge} {dpinned_badge}</td>'
                f'<td>'
                f'<div class="acts-desktop">'
                f'{dpin_btn}'
                f'{dblock_btn}'
                f'<button class="act danger" onclick="confirmDeckDelete([\'{did}\'])">delete</button>'
                f'</div>'
                f'<div class="acts-mobile">'
                f'<div class="act-trigger">'
                f'<button type="button" class="act-dots" onclick="togglePopup(this)" title="Actions">&#8943;</button>'
                f'<div class="act-popup">'
                f'{dpin_popup}'
                f'<div class="ap-sep"></div>'
                f'{dblock_popup}'
                f'<div class="ap-sep"></div>'
                f'<button class="ap-item ap-danger" onclick="confirmDeckDelete([\'{did}\']);closePopup()">&#10005; delete</button>'
                f'</div></div></div>'
                f'</td></tr>'
            )
        deck_rows_html = "\n".join(deck_rows)

    freeze_reg = settings.get("freeze_reg", False)

    return render_template("admin.html",
                           flash_html=flash_html,
                           freeze_pages=freeze_pages, freeze_decks=freeze_decks,
                           freeze_reg=freeze_reg,
                           total=total, total_hits=total_hits,
                           total_decks=total_decks, total_deck_hits=total_deck_hits,
                           rows_html=rows_html, deck_rows_html=deck_rows_html)

# ---------------------------------------------------------------------------
# routes — pages
# ---------------------------------------------------------------------------

@app.route("/favicon.png")
def favicon():
    return send_from_directory(BASE, "favicon.png", mimetype="image/png")


@app.route("/")
def index():
    return render_home()


@app.route("/page")
def page_create():
    return render_index()


@app.route("/share", methods=["POST"])
@limiter.limit("10 per minute")
def share():
    fp = load_settings().get("freeze_pages", "off")
    if _is_frozen(fp):
        msg = "Uploading is restricted to logged-in users." if fp == "anon" else "Uploading new pages is currently disabled by the administrator."
        return render_index(error=msg)
    content = None
    if "file" in request.files and request.files["file"].filename:
        f = request.files["file"]
        if not f.filename.lower().endswith((".html", ".htm")):
            return render_index(error="Only .html / .htm files are accepted.")
        content = f.read().decode("utf-8", errors="replace")
    else:
        content = request.form.get("html", "").strip()

    if not content:
        return render_index(error="Please paste some HTML or upload a file.")

    page_id = uuid.uuid4().hex[:10]
    filepath = os.path.join(PAGES_DIR, f"{page_id}.html")
    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write(content)
    owner = get_current_user() or ""
    upsert_meta(page_id, size=len(content.encode("utf-8")), owner=owner)
    if owner:
        update_user(owner, last_active=datetime.now(timezone.utc).isoformat(), last_action="share_page")
    return render_index(page_id=page_id, host=request.host_url)


@app.route("/p/<page_id>")
def view_page(page_id):
    pid = re.sub(r"[^a-zA-Z0-9]", "", page_id)[:20]
    meta = get_page_meta(pid)
    if meta is None or not os.path.exists(os.path.join(PAGES_DIR, f"{pid}.html")):
        return error_page(404, "Page not found",
                          "This page doesn't exist or may have been deleted.",
                          f"id: {pid}")
    if meta.get("blocked"):
        return error_page(451, "Page unavailable",
                          "This page has been temporarily blocked by an administrator.",
                          f"id: {pid}")
    inc_hits(pid)
    return send_from_directory(PAGES_DIR, f"{pid}.html", mimetype="text/html")


@app.route("/p/<page_id>/source")
def view_source(page_id):
    pid = re.sub(r"[^a-zA-Z0-9]", "", page_id)[:20]
    filepath = os.path.join(PAGES_DIR, f"{pid}.html")
    if not os.path.exists(filepath):
        return error_page(404, "Page not found",
                          "That page doesn't exist.",
                          f"id: {pid}")
    with open(filepath, encoding="utf-8") as fh:
        source = fh.read()
    return render_index(prefill=source, page_id=pid, host=request.host_url)

# ---------------------------------------------------------------------------
# routes — decks
# ---------------------------------------------------------------------------

@app.route("/deck")
def deck_create():
    return render_deck_page()


@app.route("/deck/import-zai", methods=["POST"])
@limiter.limit("10 per minute")
def deck_import_zai():
    """Accept pre-fetched z.ai slides from the client and create a deck."""
    fd = load_settings().get("freeze_decks", "off")
    if _is_frozen(fd):
        msg = "Deck creation is restricted to logged-in users." if fd == "anon" else "Creating new decks is currently disabled by the administrator."
        return Response(json.dumps({"error": msg}),
                        mimetype="application/json", status=403)
    data = request.get_json(silent=True) or {}
    pages = data.get("pages", [])
    if not pages or not isinstance(pages, list):
        return Response(json.dumps({"error": "No slides received."}),
                        mimetype="application/json", status=400)

    title = (data.get("title") or "Untitled Deck").strip()[:120]
    slides = []
    for i, page_html in enumerate(pages[:20]):
        if isinstance(page_html, str) and page_html.strip():
            slides.append({"title": f"Slide {i+1}", "html": page_html})

    if not slides:
        return Response(json.dumps({"error": "All slides were empty."}),
                        mimetype="application/json", status=422)

    deck_id = uuid.uuid4().hex[:10]
    deck_dir = os.path.join(DECKS_DIR, deck_id)
    os.makedirs(deck_dir)

    for i, slide in enumerate(slides):
        path = os.path.join(deck_dir, f"slide_{i:03d}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(slide["html"])

    manifest = {
        "title": title,
        "slides": [{"title": s["title"], "file": f"slide_{i:03d}.html"}
                   for i, s in enumerate(slides)]
    }
    with open(os.path.join(deck_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    owner = get_current_user() or ""
    upsert_deck_meta(deck_id, title=title, slide_count=len(slides), owner=owner)
    if owner:
        update_user(owner, last_active=datetime.now(timezone.utc).isoformat(), last_action="import_deck")

    result = {
        "deck_id": deck_id,
        "url": f"{request.host_url}d/{deck_id}",
        "title": title,
        "slide_count": len(slides)
    }
    return Response(json.dumps(result), mimetype="application/json")


@app.route("/deck/create", methods=["POST"])
@limiter.limit("10 per minute")
def deck_save():
    fd = load_settings().get("freeze_decks", "off")
    if _is_frozen(fd):
        msg = "Deck creation is restricted to logged-in users." if fd == "anon" else "Creating new decks is currently disabled by the administrator."
        return render_deck_page(error=msg)
    title = request.form.get("title", "").strip() or "Untitled Deck"
    slides = []

    # --- upload mode: multiple files ---
    if "files" in request.files:
        files = request.files.getlist("files")
        files = [f for f in files if f and f.filename]
        if not files:
            return render_deck_page(error="Please upload at least one .html file.")
        files.sort(key=lambda f: f.filename)
        for f in files[:20]:
            if not f.filename.lower().endswith((".html", ".htm")):
                continue
            content = f.read().decode("utf-8", errors="replace")
            if content.strip():
                slide_title = re.sub(r"\.(html?)", "", f.filename, flags=re.IGNORECASE)
                slides.append({"title": slide_title, "html": content})
    else:
        # --- paste mode: textarea arrays ---
        html_list  = request.form.getlist("slide_html[]")
        title_list = request.form.getlist("slide_title[]")
        for i, h in enumerate(html_list):
            h = h.strip()
            if h:
                t = title_list[i].strip() if i < len(title_list) else ""
                slides.append({"title": t, "html": h})

    if not slides:
        return render_deck_page(error="Please add at least one slide with content.")
    if len(slides) > 20:
        slides = slides[:20]

    deck_id  = uuid.uuid4().hex[:10]
    deck_dir = os.path.join(DECKS_DIR, deck_id)
    os.makedirs(deck_dir)

    # save each slide as individual file
    for i, slide in enumerate(slides):
        path = os.path.join(deck_dir, f"slide_{i:03d}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(slide["html"])

    # save manifest
    manifest = {
        "title": title,
        "slides": [{"title": s["title"], "file": f"slide_{i:03d}.html"}
                   for i, s in enumerate(slides)]
    }
    with open(os.path.join(deck_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    owner = get_current_user() or ""
    upsert_deck_meta(deck_id, title=title, slide_count=len(slides), owner=owner)
    if owner:
        update_user(owner, last_active=datetime.now(timezone.utc).isoformat(), last_action="create_deck")
    return render_deck_page(deck_id=deck_id, host=request.host_url)


@app.route("/d/<deck_id>")
def view_deck(deck_id):
    did = re.sub(r"[^a-zA-Z0-9]", "", deck_id)[:20]
    deck_dir = os.path.join(DECKS_DIR, did)
    manifest_path = os.path.join(deck_dir, "manifest.json")

    if not os.path.isdir(deck_dir) or not os.path.exists(manifest_path):
        return error_page(404, "Deck not found",
                          "This deck doesn't exist or may have been deleted.",
                          f"id: {did}")

    meta = get_deck_meta(did)
    if meta and meta.get("blocked"):
        return error_page(451, "Deck unavailable",
                          "This deck has been blocked by an administrator.",
                          f"id: {did}")

    inc_deck_hits(did)

    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)

    slides = []
    for slide_info in manifest.get("slides", []):
        fpath = os.path.join(deck_dir, slide_info["file"])
        if os.path.exists(fpath):
            with open(fpath, encoding="utf-8") as fh:
                slides.append({
                    "title": slide_info.get("title", ""),
                    "html":  fh.read()
                })

    if not slides:
        return error_page(404, "Deck is empty",
                          "This deck has no slides.",
                          f"id: {did}")

    title = manifest.get("title", "Untitled Deck")
    return build_deck_viewer(did, slides, title)


# ---------------------------------------------------------------------------
# routes — user auth
# ---------------------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def user_register():
    if load_settings().get("freeze_reg"):
        return render_template("register.html", active_nav="",
                               error_html='<div class="err">&#10052; Registration is currently disabled by the administrator.</div>')
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        confirm = request.form.get("confirm", "").strip()
        if not email or not password:
            return render_template("register.html", active_nav="",
                                   error_html='<div class="err">&#9888; email and password are required</div>')
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            return render_template("register.html", active_nav="",
                                   error_html='<div class="err">&#9888; please enter a valid email</div>')
        if len(password) < 6:
            return render_template("register.html", active_nav="",
                                   error_html='<div class="err">&#9888; password must be at least 6 characters</div>')
        if password != confirm:
            return render_template("register.html", active_nav="",
                                   error_html='<div class="err">&#9888; passwords do not match</div>')
        if not create_user(email, password):
            return render_template("register.html", active_nav="",
                                   error_html='<div class="err">&#9888; an account with this email already exists</div>')
        session["user_email"] = email
        update_user(email, last_login=datetime.now(timezone.utc).isoformat(), last_action="register")
        return redirect(url_for("profile"))
    return render_template("register.html", active_nav="", error_html="")


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def user_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        if not email or not password:
            return render_template("user_login.html", active_nav="",
                                   error_html='<div class="err">&#9888; email and password are required</div>')
        if not verify_user(email, password):
            return render_template("user_login.html", active_nav="",
                                   error_html='<div class="err">&#9888; invalid email or password</div>')
        session["user_email"] = email
        update_user(email, last_login=datetime.now(timezone.utc).isoformat(), last_action="login")
        return redirect(url_for("profile"))
    return render_template("user_login.html", active_nav="", error_html="")


@app.route("/logout", methods=["POST"])
def user_logout():
    session.pop("user_email", None)
    return redirect(url_for("index"))


@app.route("/profile")
@login_required
def profile():
    email = get_current_user()
    flash_msg = session.pop("profile_flash", None)
    flash_type = session.pop("profile_flash_type", "ok")

    # gather user's pages
    meta = load_meta()
    user_pages = []
    for pid, info in meta.items():
        if info.get("owner") == email and os.path.exists(os.path.join(PAGES_DIR, f"{pid}.html")):
            user_pages.append({**info, "id": pid})
    user_pages.sort(key=lambda p: p.get("created", ""), reverse=True)

    # gather user's decks
    decks_meta = load_decks_meta()
    user_decks = []
    for did, dinfo in decks_meta.items():
        if dinfo.get("owner") == email and os.path.isdir(os.path.join(DECKS_DIR, did)):
            user_decks.append({**dinfo, "id": did})
    user_decks.sort(key=lambda d: d.get("created", ""), reverse=True)

    return render_template("profile.html", active_nav="profile",
                           email=email, pages=user_pages, decks=user_decks,
                           flash_msg=flash_msg, flash_type=flash_type)


@app.route("/profile/delete_page", methods=["POST"])
@login_required
def profile_delete_page():
    email = get_current_user()
    pid = re.sub(r"[^a-zA-Z0-9]", "", request.form.get("id", ""))[:20]
    meta = load_meta()
    if pid in meta and meta[pid].get("owner") == email:
        delete_page(pid)
        update_user(email, last_active=datetime.now(timezone.utc).isoformat(), last_action="delete_page")
        session["profile_flash"] = f"Page {pid} deleted."
        session["profile_flash_type"] = "ok"
    else:
        session["profile_flash"] = "You can only delete your own pages."
        session["profile_flash_type"] = "err"
    return redirect(url_for("profile"))


@app.route("/profile/delete_deck", methods=["POST"])
@login_required
def profile_delete_deck():
    email = get_current_user()
    did = re.sub(r"[^a-zA-Z0-9]", "", request.form.get("id", ""))[:20]
    decks_meta = load_decks_meta()
    if did in decks_meta and decks_meta[did].get("owner") == email:
        delete_deck(did)
        update_user(email, last_active=datetime.now(timezone.utc).isoformat(), last_action="delete_deck")
        session["profile_flash"] = f"Deck {did} deleted."
        session["profile_flash_type"] = "ok"
    else:
        session["profile_flash"] = "You can only delete your own decks."
        session["profile_flash_type"] = "err"
    return redirect(url_for("profile"))


# ---------------------------------------------------------------------------
# routes — admin
# ---------------------------------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def admin_login():
    if request.method == "POST":
        if request.form.get("password", "") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin"))
        return render_template("login.html",
                               error_html='<div class="err">&#9888; incorrect password</div>')
    return render_template("login.html", error_html="")


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
@admin_required
def admin():
    flash_msg  = session.pop("flash", None)
    flash_type = session.pop("flash_type", "ok")
    return build_admin_page(load_meta(),
                             flash_msg=flash_msg, flash_type=flash_type)


@app.route("/admin/action", methods=["POST"])
@admin_required
def admin_action():
    op       = request.form.get("op", "")
    raw      = request.form.get("ids", "")
    ids      = [i.strip() for i in raw.split(",")
                if re.match(r"^[a-zA-Z0-9]{1,20}$", i.strip())]

    if not ids:
        session["flash"] = "No pages selected."
        session["flash_type"] = "err"
    elif op == "delete":
        for pid in ids:
            delete_page(pid)
        n = len(ids)
        session["flash"] = f"Deleted {n} page{'s' if n!=1 else ''}."
        session["flash_type"] = "ok"
    elif op == "block":
        m = load_meta()
        for pid in ids:
            if pid in m:
                m[pid]["blocked"] = True
        save_meta(m)
        n = len(ids)
        session["flash"] = f"Blocked {n} page{'s' if n!=1 else ''}."
        session["flash_type"] = "ok"
    elif op == "unblock":
        m = load_meta()
        for pid in ids:
            if pid in m:
                m[pid]["blocked"] = False
        save_meta(m)
        n = len(ids)
        session["flash"] = f"Unblocked {n} page{'s' if n!=1 else ''}."
        session["flash_type"] = "ok"
    else:
        session["flash"] = f"Unknown operation: {op}"
        session["flash_type"] = "err"

    return _admin_redirect()


@app.route("/admin/freeze", methods=["POST"])
@admin_required
def admin_freeze():
    target = request.form.get("target", "")
    mode = request.form.get("mode", "")
    s = load_settings()
    if target in ("pages", "decks"):
        key = f"freeze_{target}"
        if mode in ("off", "anon", "all"):
            s[key] = mode
        else:
            s[key] = "off"
        labels = {"off": "open", "anon": "anon-only freeze", "all": "fully frozen"}
        nice = "Page uploads" if target == "pages" else "Deck creation"
        session["flash"] = f"{nice}: {labels[s[key]]}."
        session["flash_type"] = "ok"
    elif target == "reg":
        s["freeze_reg"] = not s.get("freeze_reg", False)
        state = "frozen" if s["freeze_reg"] else "unfrozen"
        session["flash"] = f"New registrations {state}."
        session["flash_type"] = "ok"
    else:
        session["flash"] = "Unknown freeze target."
        session["flash_type"] = "err"
    save_settings(s)
    return _admin_redirect()


@app.route("/admin/pin", methods=["POST"])
@admin_required
def admin_pin():
    item_type = request.form.get("type", "")
    item_id = re.sub(r"[^a-zA-Z0-9]", "", request.form.get("id", ""))[:20]
    action = request.form.get("action", "")
    if not item_id or item_type not in ("page", "deck") or action not in ("pin", "unpin", "rename"):
        session["flash"] = "Invalid pin request."
        session["flash_type"] = "err"
        return _admin_redirect()
    s = load_settings()
    current = s.get("pinned")
    if action == "pin":
        pin_name = request.form.get("name", "").strip()[:80]
        s["pinned"] = {"type": item_type, "id": item_id, "name": pin_name}
        label = pin_name or item_id
        session["flash"] = f'Pinned {item_type} as homepage hero: "{label}".'
        session["flash_type"] = "ok"
    elif action == "rename":
        if current and current.get("type") == item_type and current.get("id") == item_id:
            pin_name = request.form.get("name", "").strip()[:80]
            current["name"] = pin_name
            s["pinned"] = current
            label = pin_name or item_id
            session["flash"] = f'Updated hero name to "{label}".'
            session["flash_type"] = "ok"
        else:
            session["flash"] = "That item is not currently pinned."
            session["flash_type"] = "err"
    elif action == "unpin":
        if current and current.get("type") == item_type and current.get("id") == item_id:
            s["pinned"] = None
            session["flash"] = f"Unpinned {item_type} {item_id}."
            session["flash_type"] = "ok"
        else:
            session["flash"] = "That item is not currently pinned."
            session["flash_type"] = "err"
    save_settings(s)
    return _admin_redirect()


@app.route("/admin/deck/action", methods=["POST"])
@admin_required
def admin_deck_action():
    op   = request.form.get("op", "")
    raw  = request.form.get("ids", "")
    ids  = [i.strip() for i in raw.split(",")
            if re.match(r"^[a-zA-Z0-9]{1,20}$", i.strip())]

    if not ids:
        session["flash"] = "No decks selected."
        session["flash_type"] = "err"
    elif op == "delete":
        for did in ids:
            delete_deck(did)
        n = len(ids)
        session["flash"] = f"Deleted {n} deck{'s' if n != 1 else ''}."
        session["flash_type"] = "ok"
    elif op == "block":
        m = load_decks_meta()
        for did in ids:
            if did in m:
                m[did]["blocked"] = True
        save_decks_meta(m)
        n = len(ids)
        session["flash"] = f"Blocked {n} deck{'s' if n != 1 else ''}."
        session["flash_type"] = "ok"
    elif op == "unblock":
        m = load_decks_meta()
        for did in ids:
            if did in m:
                m[did]["blocked"] = False
        save_decks_meta(m)
        n = len(ids)
        session["flash"] = f"Unblocked {n} deck{'s' if n != 1 else ''}."
        session["flash_type"] = "ok"
    else:
        session["flash"] = f"Unknown operation: {op}"
        session["flash_type"] = "err"

    return _admin_redirect()


# ---------------------------------------------------------------------------
# global error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(_):
    return error_page(404, "Nothing here",
                      "The page you're looking for doesn't exist.",
                      f"requested: {request.path}")

@app.errorhandler(413)
def too_large(_):
    return error_page(413, "File too large",
                      "The uploaded file exceeds the limit.",
                      "try compressing assets or splitting content")

@app.errorhandler(429)
def rate_limited(_):
    return error_page(429, "Too many requests",
                      "You've made too many requests. Please wait a moment and try again.",
                      "rate limit exceeded")

# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    print(f"  Admin password : {ADMIN_PASSWORD}")
    print(f"  Set ADMIN_PASSWORD env var to change it.")
    print(f"  Pages stored in: {PAGES_DIR}")
    print(f"  Decks stored in: {DECKS_DIR}")
    app.run(debug="--debug" in sys.argv, port=5000, host="0.0.0.0")