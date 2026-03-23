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
import os, uuid, json, re, smtplib, hashlib, hmac, time, threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")  
SETTINGS_FILE = os.path.join(BASE, "settings.json")
USERS_FILE = os.path.join(BASE, "users.json")

# ---------------------------------------------------------------------------
# email config
# ---------------------------------------------------------------------------
SMTP_EMAIL = os.environ.get("SMTP_EMAIL")
SMTP_APP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD")
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

# in-memory token store: {token: {type, email, payload, expires}}
_tokens = {}
TOKEN_EXPIRY = 15 * 60  # 15 minutes

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
# email helpers
# ---------------------------------------------------------------------------

def send_email(to_email, subject, html_body):
    """Send email synchronously. Returns True on success, False on failure."""
    if not SMTP_EMAIL or not SMTP_APP_PASSWORD:
        print("[EMAIL ERROR] SMTP_EMAIL or SMTP_APP_PASSWORD not configured.")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"htmldrop <{SMTP_EMAIL}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_APP_PASSWORD)
            server.sendmail(SMTP_EMAIL, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] Failed to send to {to_email}: {e}")
        return False

def send_email_async(to_email, subject, html_body):
    """Fire-and-forget email for notifications where delivery failure is acceptable."""
    t = threading.Thread(target=send_email, args=(to_email, subject, html_body), daemon=True)
    t.start()

def _email_wrap(content):
    """Wrap content in a styled email template."""
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#0c0c0e;font-family:'Segoe UI',Arial,sans-serif;">
<div style="max-width:520px;margin:40px auto;background:#141418;border:1px solid #252530;border-radius:8px;overflow:hidden;">
<div style="background:linear-gradient(135deg,#1a3d1a,#141418);padding:28px 32px;border-bottom:1px solid #252530;">
<div style="font-size:22px;font-weight:bold;color:#e8e8f0;letter-spacing:-.03em;">html<span style="color:#7fff7f">drop</span></div>
</div>
<div style="padding:28px 32px;color:#e8e8f0;font-size:14px;line-height:1.7;">
{content}
</div>
<div style="padding:16px 32px;border-top:1px solid #252530;font-size:11px;color:#6b6b80;">
This email was sent by htmldrop. If you didn't expect this, you can ignore it.
</div>
</div></body></html>"""

def generate_token(token_type, email, payload=None):
    """Create a time-limited token and store it in memory."""
    # clean expired tokens
    now = time.time()
    expired = [k for k, v in _tokens.items() if v["expires"] < now]
    for k in expired:
        del _tokens[k]
    token = uuid.uuid4().hex
    _tokens[token] = {
        "type": token_type,
        "email": email,
        "payload": payload or {},
        "expires": now + TOKEN_EXPIRY,
    }
    return token

def validate_token(token, expected_type):
    """Return token data if valid, else None. Consumes the token."""
    data = _tokens.get(token)
    if not data:
        return None
    if data["type"] != expected_type:
        return None
    if time.time() > data["expires"]:
        del _tokens[token]
        return None
    del _tokens[token]
    return data

def invalidate_tokens_for(email, token_type):
    """Remove all tokens of a given type for an email."""
    to_delete = [k for k, v in _tokens.items()
                 if v["email"] == email and v["type"] == token_type]
    for k in to_delete:
        del _tokens[k]

def send_verification_email_with_url(email, site_url):
    """Send email verification with the correct site URL. Returns True on success."""
    token = generate_token("verify_email", email)
    link = f"{site_url}verify-email?token={token}"
    html = _email_wrap(f"""
    <h2 style="margin:0 0 16px;font-size:18px;color:#7fff7f;">Verify your email</h2>
    <p>Click the button below to verify your email address. This link expires in 15 minutes.</p>
    <a href="{link}" style="display:inline-block;background:#7fff7f;color:#0a1a0a;font-weight:bold;text-decoration:none;padding:12px 28px;border-radius:6px;margin:16px 0;">Verify Email &rarr;</a>
    <p style="font-size:12px;color:#6b6b80;">If the button doesn't work, copy this link:<br/><span style="color:#7fcfff;word-break:break-all;">{link}</span></p>
    """)
    return send_email(email, "Verify your email — htmldrop", html)

def send_welcome_email(email):
    """Send account created welcome email (fire-and-forget notification)."""
    html = _email_wrap(f"""
    <h2 style="margin:0 0 16px;font-size:18px;color:#7fff7f;">Welcome to htmldrop! &#127881;</h2>
    <p>Your account <strong style="color:#7fcfff;">{email}</strong> has been created successfully.</p>
    <p>You can now upload HTML pages and create slide decks. Please verify your email to unlock all features.</p>
    <p style="color:#6b6b80;font-size:12px;margin-top:20px;">If you didn't create this account, please ignore this email.</p>
    """)
    send_email_async(email, "Welcome to htmldrop!", html)

def send_password_changed_email(email):
    """Notify user their password was changed (fire-and-forget)."""
    html = _email_wrap(f"""
    <h2 style="margin:0 0 16px;font-size:18px;color:#ffd47f;">Password changed</h2>
    <p>The password for <strong style="color:#7fcfff;">{email}</strong> was successfully changed.</p>
    <p>If you didn't make this change, please contact the administrator immediately.</p>
    """)
    send_email_async(email, "Password changed — htmldrop", html)

def send_email_changed_notification(old_email, new_email):
    """Notify both old and new email about the change (fire-and-forget)."""
    html_old = _email_wrap(f"""
    <h2 style="margin:0 0 16px;font-size:18px;color:#ffd47f;">Email address changed</h2>
    <p>Your htmldrop account email has been changed from <strong style="color:#7fcfff;">{old_email}</strong> to <strong style="color:#7fcfff;">{new_email}</strong>.</p>
    <p>If you didn't make this change, please contact the administrator immediately.</p>
    """)
    html_new = _email_wrap(f"""
    <h2 style="margin:0 0 16px;font-size:18px;color:#7fff7f;">Email address updated</h2>
    <p>Your htmldrop account email has been updated to <strong style="color:#7fcfff;">{new_email}</strong>.</p>
    <p>Please verify your new email address from your profile page.</p>
    """)
    send_email_async(old_email, "Email address changed — htmldrop", html_old)
    send_email_async(new_email, "Email address updated — htmldrop", html_new)

def send_blocked_email(email):
    """Notify user their account was blocked (fire-and-forget)."""
    html = _email_wrap(f"""
    <h2 style="margin:0 0 16px;font-size:18px;color:#ff7f7f;">Account blocked</h2>
    <p>Your htmldrop account <strong style="color:#7fcfff;">{email}</strong> has been blocked by an administrator.</p>
    <p>While blocked, you cannot log in or use your account. If you believe this is a mistake, please contact the administrator.</p>
    """)
    send_email_async(email, "Account blocked — htmldrop", html)

def send_unblocked_email(email):
    """Notify user their account was unblocked (fire-and-forget)."""
    html = _email_wrap(f"""
    <h2 style="margin:0 0 16px;font-size:18px;color:#7fff7f;">Account unblocked</h2>
    <p>Your htmldrop account <strong style="color:#7fcfff;">{email}</strong> has been unblocked. You can now log in and use your account again.</p>
    """)
    send_email_async(email, "Account unblocked — htmldrop", html)

def send_account_deleted_email(email):
    """Notify user their account was deleted by admin (fire-and-forget)."""
    html = _email_wrap(f"""
    <h2 style="margin:0 0 16px;font-size:18px;color:#ff7f7f;">Account deleted</h2>
    <p>Your htmldrop account <strong style="color:#7fcfff;">{email}</strong> has been deleted by an administrator.</p>
    <p>All your account data has been removed. Your uploaded pages and decks may still exist.</p>
    """)
    send_email_async(email, "Account deleted — htmldrop", html)

def send_page_pinned_email(owner_email, item_type, item_id, pin_name):
    """Notify user one of their items was pinned (fire-and-forget)."""
    label = pin_name or item_id
    html = _email_wrap(f"""
    <h2 style="margin:0 0 16px;font-size:18px;color:#7fff7f;">Your {item_type} was featured! &#11088;</h2>
    <p>Your {item_type} <strong style="color:#7fcfff;">{label}</strong> (<code style="color:#ffd47f;">{item_id}</code>) has been pinned to the htmldrop homepage by an administrator.</p>
    <p>It will be featured as the hero content for all visitors to see!</p>
    """)
    send_email_async(owner_email, f"Your {item_type} was featured — htmldrop", html)

def send_page_unpinned_email(owner_email, item_type, item_id):
    """Notify user their pinned item was unpinned (fire-and-forget)."""
    html = _email_wrap(f"""
    <h2 style="margin:0 0 16px;font-size:18px;color:#ffd47f;">Your {item_type} was unpinned</h2>
    <p>Your {item_type} <code style="color:#ffd47f;">{item_id}</code> has been removed from the htmldrop homepage.</p>
    """)
    send_email_async(owner_email, f"Your {item_type} was unpinned — htmldrop", html)

def send_delete_account_email(email, site_url):
    """Send account deletion confirmation link. Returns True on success."""
    token = generate_token("delete_account", email)
    link = f"{site_url}confirm-delete-account?token={token}"
    html = _email_wrap(f"""
    <h2 style="margin:0 0 16px;font-size:18px;color:#ff7f7f;">Confirm account deletion</h2>
    <p>You requested to delete your htmldrop account <strong style="color:#7fcfff;">{email}</strong>.</p>
    <p style="color:#ff7f7f;font-weight:bold;">This action is permanent and cannot be undone.</p>
    <p>Your pages and decks will remain but will no longer be linked to an account.</p>
    <a href="{link}" style="display:inline-block;background:#ff7f7f;color:#1a0a0a;font-weight:bold;text-decoration:none;padding:12px 28px;border-radius:6px;margin:16px 0;">Confirm Deletion &rarr;</a>
    <p style="font-size:12px;color:#6b6b80;">This link expires in 15 minutes. If you didn't request this, just ignore this email.</p>
    """)
    return send_email(email, "Confirm account deletion — htmldrop", html)

def send_change_password_email(email, site_url):
    """Send password change confirmation link. Returns True on success."""
    token = generate_token("change_password", email)
    link = f"{site_url}confirm-change-password?token={token}"
    html = _email_wrap(f"""
    <h2 style="margin:0 0 16px;font-size:18px;color:#ffd47f;">Confirm password change</h2>
    <p>Click the link below to set a new password for <strong style="color:#7fcfff;">{email}</strong>.</p>
    <a href="{link}" style="display:inline-block;background:#ffd47f;color:#1a1a0a;font-weight:bold;text-decoration:none;padding:12px 28px;border-radius:6px;margin:16px 0;">Change Password &rarr;</a>
    <p style="font-size:12px;color:#6b6b80;">This link expires in 15 minutes.</p>
    """)
    return send_email(email, "Change your password — htmldrop", html)

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
        "email_verified": False,
    }
    save_users(users)
    return True

def verify_user(email, password):
    users = load_users()
    user = users.get(email)
    if not user:
        return False
    if user.get("blocked"):
        return None  # blocked
    return check_password_hash(user["password_hash"], password)

def is_user_blocked(email):
    users = load_users()
    user = users.get(email)
    return user.get("blocked", False) if user else False

def delete_user_account(email):
    """Delete a user from users.json (does NOT delete their pages/decks)."""
    users = load_users()
    users.pop(email, None)
    save_users(users)

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
    if tab in ("pages", "decks", "users"):
        return redirect(f"{base}#{tab}")
    return redirect(base)

def _get_item_owner(item_type, item_id):
    """Return the owner email of a page or deck, or empty string."""
    if item_type == "page":
        info = load_meta().get(item_id)
        return info.get("owner", "") if info else ""
    elif item_type == "deck":
        info = load_decks_meta().get(item_id)
        return info.get("owner", "") if info else ""
    return ""

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
                safe_name = (p_name or info.get("title") or p_id).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
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

def _extract_html_title(html_content):
    """Extract the content of the <title> tag from HTML, or return empty string."""
    m = re.search(r'<title[^>]*>([^<]+)</title>', html_content, re.IGNORECASE)
    return m.group(1).strip() if m else ""


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
        rows_html = '<tr class="page-empty-row"><td colspan="9"><div class="empty"><span class="empty-icon">&#128237;</span>No pages yet. <a href="/">Share your first page &rarr;</a></div></td></tr>'
    else:
        rows = []
        for p in pages:
            pid     = p["id"]
            hits    = p.get("hits", 0)
            size    = p.get("size", 0)
            blocked = p.get("blocked", False)
            created = p.get("created", "")
            owner   = p.get("owner", "")
            title   = p.get("title", "Untitled")
            safe_title = title.replace('&','&amp;').replace('"','&quot;').replace('<','&lt;').replace('>','&gt;') if title else 'Untitled'
            safe_owner = owner.replace('&','&amp;').replace('"','&quot;').replace('<','&lt;').replace('>','&gt;') if owner else ''
            pct     = int(hits / max_hits * 100)
            badge   = (f'<span class="bdg bdg-off"><span class="bdg-dot"></span>blocked</span>'
                       if blocked else
                       f'<span class="bdg bdg-on"><span class="bdg-dot"></span>active</span>')
            is_pinned = pid in pinned_pages
            safe_pin_name = pinned_name.replace('&','&amp;').replace('"','&quot;').replace('<','&lt;').replace('>','&gt;') if is_pinned else ''
            pinned_badge = f'<span class="bdg bdg-pin" title="Pinned to homepage">&#9733; pinned</span>' if is_pinned else ''
            pid_style = ' style="color:var(--warn)"' if is_pinned else ''
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
                f' data-owner="{safe_owner}" data-title="{safe_title}">'
                f'<td><input type="checkbox" class="cb row-cb" value="{pid}" onchange="updateBulk()"/></td>'
                f'<td><a class="pid" href="/p/{pid}" target="_blank"{pid_style}>{pid}</a></td>'
                f'<td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{safe_title}">{safe_title}</td>'
                f'<td class="ts owner-cell" style="color:var(--info);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{safe_owner}">{safe_owner or "<span style=color:var(--muted2)>anon</span>"}</td>'
                f'<td class="ts">{fmt_date(created)}</td>'
                f'<td class="sz">{fmt_size(size)}</td>'
                f'<td><div class="hits-bar"><span class="hits-val">{hits:,}</span>'
                f'<div class="hits-track"><div class="hits-fill" style="width:{pct}%"></div></div></div></td>'
                f'<td>{badge}</td>'
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
            did_style = ' style="color:var(--warn)"' if is_deck_pinned else ''
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
                f'<td><a class="pid" href="/d/{did}" target="_blank"{did_style}>{did}</a></td>'
                f'<td style="color:var(--text);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{dtitle}</td>'
                f'<td class="ts owner-cell" style="color:var(--info);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{safe_downer}">{safe_downer or "<span style=color:var(--muted2)>anon</span>"}</td>'
                f'<td class="ts">{fmt_date(dcreated)}</td>'
                f'<td style="color:var(--info)">{dslides}</td>'
                f'<td><div class="hits-bar"><span class="hits-val">{dhits:,}</span>'
                f'<div class="hits-track"><div class="hits-fill" style="width:{dpct}%"></div></div></div></td>'
                f'<td>{dbadge}</td>'
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

    # build user rows HTML
    users = load_users()
    # count pages/decks per owner
    owner_pages = {}
    for pid, pinfo in meta.items():
        o = pinfo.get("owner", "")
        if o:
            owner_pages[o] = owner_pages.get(o, 0) + 1
    owner_decks = {}
    for did, dinfo in decks_meta.items():
        o = dinfo.get("owner", "")
        if o:
            owner_decks[o] = owner_decks.get(o, 0) + 1

    user_list = []
    for email, uinfo in users.items():
        user_list.append({
            "email": email,
            "created": uinfo.get("created", ""),
            "last_login": uinfo.get("last_login", ""),
            "blocked": uinfo.get("blocked", False),
            "pages": owner_pages.get(email, 0),
            "decks": owner_decks.get(email, 0),
        })
    user_list.sort(key=lambda u: u.get("created", ""), reverse=True)
    total_users = len(user_list)
    blocked_users = sum(1 for u in user_list if u.get("blocked"))

    if not user_list:
        user_rows_html = '<tr class="user-empty-row"><td colspan="8"><div class="empty"><span class="empty-icon">&#9679;</span>No users yet.</div></td></tr>'
    else:
        user_rows = []
        for u in user_list:
            uemail = u["email"]
            safe_email = uemail.replace('&','&amp;').replace('"','&quot;').replace('<','&lt;').replace('>','&gt;')
            # js-safe email for onclick (escape single quotes)
            js_email = safe_email.replace("'", "\\'")
            ucreated = u.get("created", "")
            ulast = u.get("last_login", "")
            ublocked = u.get("blocked", False)
            upages = u.get("pages", 0)
            udecks = u.get("decks", 0)
            ubadge = (f'<span class="bdg bdg-off"><span class="bdg-dot"></span>blocked</span>'
                      if ublocked else
                      f'<span class="bdg bdg-on"><span class="bdg-dot"></span>active</span>')
            ublock_btn = (
                f'<button class="act ok" onclick="doUserAction(\'unblock\',[\'{js_email}\'])">unblock</button>'
                if ublocked else
                f'<button class="act warn" onclick="doUserAction(\'block\',[\'{js_email}\'])">block</button>'
            )
            ublock_popup = (
                f'<button class="ap-item ap-ok" onclick="doUserAction(\'unblock\',[\'{js_email}\']);closePopup()">&#8593; unblock</button>'
                if ublocked else
                f'<button class="ap-item ap-warn" onclick="doUserAction(\'block\',[\'{js_email}\']);closePopup()">&#8856; block</button>'
            )
            user_rows.append(
                f'<tr id="urow-{safe_email}" class="user-row {"is-blocked" if ublocked else ""}"'
                f' data-email="{safe_email}" data-created="{ucreated}" data-last-login="{ulast}"'
                f' data-pages="{upages}" data-decks="{udecks}"'
                f' data-status="{"blocked" if ublocked else "active"}">'
                f'<td><input type="checkbox" class="cb user-cb" value="{safe_email}" onchange="updateUserBulk()"/></td>'
                f'<td style="color:var(--info);max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="{safe_email}">{safe_email}</td>'
                f'<td class="ts">{fmt_date(ucreated)}</td>'
                f'<td class="ts">{fmt_date(ulast) if ulast else "<span style=color:var(--muted2)>never</span>"}</td>'
                f'<td style="color:var(--accent)">{upages}</td>'
                f'<td style="color:var(--warn)">{udecks}</td>'
                f'<td>{ubadge}</td>'
                f'<td>'
                f'<div class="acts-desktop">'
                f'<button class="act info" onclick="filterByUser(\'{js_email}\',\'pages\')">pages</button>'
                f'<button class="act info" onclick="filterByUser(\'{js_email}\',\'decks\')">decks</button>'
                f'{ublock_btn}'
                f'<button class="act danger" onclick="confirmUserDelete([\'{js_email}\'])">delete</button>'
                f'</div>'
                f'<div class="acts-mobile">'
                f'<div class="act-trigger">'
                f'<button type="button" class="act-dots" onclick="togglePopup(this)" title="Actions">&#8943;</button>'
                f'<div class="act-popup">'
                f'<button class="ap-item ap-info" onclick="filterByUser(\'{js_email}\',\'pages\');closePopup()">&#128196; view pages</button>'
                f'<button class="ap-item ap-info" onclick="filterByUser(\'{js_email}\',\'decks\');closePopup()">&#9707; view decks</button>'
                f'<div class="ap-sep"></div>'
                f'{ublock_popup}'
                f'<div class="ap-sep"></div>'
                f'<button class="ap-item ap-danger" onclick="confirmUserDelete([\'{js_email}\']);closePopup()">&#10005; delete</button>'
                f'</div></div></div>'
                f'</td></tr>'
            )
        user_rows_html = "\n".join(user_rows)

    return render_template("admin.html",
                           flash_html=flash_html,
                           freeze_pages=freeze_pages, freeze_decks=freeze_decks,
                           freeze_reg=freeze_reg,
                           total=total, total_hits=total_hits,
                           total_decks=total_decks, total_deck_hits=total_deck_hits,
                           total_users=total_users, blocked_users=blocked_users,
                           rows_html=rows_html, deck_rows_html=deck_rows_html,
                           user_rows_html=user_rows_html)

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
    # require verified email for logged-in users
    current = get_current_user()
    if current:
        users = load_users()
        if current in users and not users[current].get("email_verified", False):
            return render_index(error="Please verify your email before uploading. Check your profile page.")
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

    # resolve page title: form field > <title> tag > "Untitled"
    title = request.form.get("title", "").strip()[:120]
    if not title:
        title = _extract_html_title(content)[:120] or "Untitled"

    page_id = uuid.uuid4().hex[:10]
    filepath = os.path.join(PAGES_DIR, f"{page_id}.html")
    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write(content)
    owner = get_current_user() or ""
    upsert_meta(page_id, size=len(content.encode("utf-8")), owner=owner, title=title)
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
    # require verified email
    current = get_current_user()
    if current:
        users = load_users()
        if current in users and not users[current].get("email_verified", False):
            return Response(json.dumps({"error": "Please verify your email before creating decks."}),
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
    # require verified email
    current = get_current_user()
    if current:
        users = load_users()
        if current in users and not users[current].get("email_verified", False):
            return render_deck_page(error="Please verify your email before creating decks. Check your profile page.")
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
        if not request.form.get("tos"):
            return render_template("register.html", active_nav="",
                                   error_html='<div class="err">&#9888; you must agree to the terms &amp; conditions</div>')
        if not create_user(email, password):
            return render_template("register.html", active_nav="",
                                   error_html='<div class="err">&#9888; an account with this email already exists</div>')
        session["user_email"] = email
        update_user(email, last_login=datetime.now(timezone.utc).isoformat(), last_action="register")
        # send welcome + verification emails
        send_welcome_email(email)
        if not send_verification_email_with_url(email, request.host_url):
            session["profile_flash"] = "Account created, but verification email failed. Please try again later from your profile."
            session["profile_flash_type"] = "err"
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
        result = verify_user(email, password)
        if result is None:
            return render_template("user_login.html", active_nav="",
                                   error_html='<div class="err">&#9888; your account has been blocked by an administrator</div>')
        if not result:
            return render_template("user_login.html", active_nav="",
                                   error_html='<div class="err">&#9888; invalid email or password</div>')
        session["user_email"] = email
        update_user(email, last_login=datetime.now(timezone.utc).isoformat(), last_action="login")
        return redirect(url_for("profile"))
    return render_template("user_login.html", active_nav="", error_html="")


@app.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("3 per minute")
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email:
            return render_template("user_login.html", active_nav="", error_html="",
                                   forgot=True, forgot_error='<div class="err">&#9888; please enter your email</div>')
        users = load_users()
        if email not in users:
            return render_template("user_login.html", active_nav="", error_html="",
                                   forgot=True, forgot_error='<div class="err">&#9888; no account found with this email</div>')
        if send_change_password_email(email, request.host_url):
            return render_template("user_login.html", active_nav="", error_html="",
                                   forgot=True, forgot_success='<div class="ok-msg">&#10003; Password reset link sent! Check your inbox.</div>')
        return render_template("user_login.html", active_nav="", error_html="",
                               forgot=True, forgot_error='<div class="err">&#9888; failed to send email. Please try again later.</div>')
    return render_template("user_login.html", active_nav="", error_html="", forgot=True)


@app.route("/logout", methods=["POST"])
@limiter.limit("10 per minute")
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

    users = load_users()
    email_verified = users.get(email, {}).get("email_verified", False)

    return render_template("profile.html", active_nav="profile",
                           email=email, pages=user_pages, decks=user_decks,
                           flash_msg=flash_msg, flash_type=flash_type,
                           email_verified=email_verified)


@app.route("/profile/delete_page", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
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
@limiter.limit("10 per minute")
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
# routes — email verification & account management
# ---------------------------------------------------------------------------

@app.route("/verify-email")
@limiter.limit("10 per minute")
def verify_email():
    token = request.args.get("token", "")
    data = validate_token(token, "verify_email")
    if not data:
        return error_page(400, "Invalid or expired link",
                          "This verification link is invalid or has expired.",
                          "Request a new verification email from your profile page.")
    email = data["email"]
    users = load_users()
    if email in users:
        users[email]["email_verified"] = True
        save_users(users)
    if session.get("user_email") == email:
        session["profile_flash"] = "Email verified successfully!"
        session["profile_flash_type"] = "ok"
    return redirect(url_for("profile"))


@app.route("/profile/resend-verification", methods=["POST"])
@login_required
@limiter.limit("3 per minute")
def resend_verification():
    email = get_current_user()
    users = load_users()
    if email in users and users[email].get("email_verified"):
        session["profile_flash"] = "Email is already verified."
        session["profile_flash_type"] = "ok"
    else:
        if send_verification_email_with_url(email, request.host_url):
            session["profile_flash"] = "Verification email sent! Check your inbox."
            session["profile_flash_type"] = "ok"
        else:
            session["profile_flash"] = "Failed to send verification email. Please try again later."
            session["profile_flash_type"] = "err"
    return redirect(url_for("profile"))


@app.route("/profile/request-change-password", methods=["POST"])
@login_required
@limiter.limit("3 per minute")
def request_change_password():
    """Send a password change link to the user's email."""
    email = get_current_user()
    if send_change_password_email(email, request.host_url):
        session["profile_flash"] = "Password change link sent to your email."
        session["profile_flash_type"] = "ok"
    else:
        session["profile_flash"] = "Failed to send email. Please try again later."
        session["profile_flash_type"] = "err"
    return redirect(url_for("profile"))


@app.route("/confirm-change-password", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def confirm_change_password():
    if request.method == "GET":
        token = request.args.get("token", "")
        # peek at the token without consuming it
        data = _tokens.get(token)
        if not data or data["type"] != "change_password" or time.time() > data["expires"]:
            return error_page(400, "Invalid or expired link",
                              "This password change link is invalid or has expired.",
                              "Request a new one from your profile page.")
        return render_template("change_password.html", token=token, error_html="")

    # POST - actually change the password
    token = request.form.get("token", "")
    new_password = request.form.get("new_password", "").strip()
    confirm = request.form.get("confirm", "").strip()

    if not new_password or len(new_password) < 6:
        return render_template("change_password.html", token=token,
                               error_html='<div class="err">&#9888; password must be at least 6 characters</div>')
    if new_password != confirm:
        return render_template("change_password.html", token=token,
                               error_html='<div class="err">&#9888; passwords do not match</div>')

    data = validate_token(token, "change_password")
    if not data:
        return error_page(400, "Invalid or expired link",
                          "This password change link is invalid or has expired.",
                          "Request a new one from your profile page.")
    email = data["email"]
    users = load_users()
    if email in users:
        users[email]["password_hash"] = generate_password_hash(new_password)
        save_users(users)
        invalidate_tokens_for(email, "change_password")
        send_password_changed_email(email)
    if session.get("user_email") == email:
        session["profile_flash"] = "Password changed successfully!"
        session["profile_flash_type"] = "ok"
    return redirect(url_for("profile"))


@app.route("/profile/change-email", methods=["POST"])
@login_required
@limiter.limit("3 per minute")
def change_email():
    """Change email requires current password verification."""
    email = get_current_user()
    password = request.form.get("password", "").strip()
    new_email = request.form.get("new_email", "").strip().lower()

    if not password or not new_email:
        session["profile_flash"] = "Password and new email are required."
        session["profile_flash_type"] = "err"
        return redirect(url_for("profile"))

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", new_email):
        session["profile_flash"] = "Please enter a valid email address."
        session["profile_flash_type"] = "err"
        return redirect(url_for("profile"))

    users = load_users()
    if email not in users:
        return redirect(url_for("user_login"))

    if not check_password_hash(users[email]["password_hash"], password):
        session["profile_flash"] = "Incorrect password."
        session["profile_flash_type"] = "err"
        return redirect(url_for("profile"))

    if new_email in users:
        session["profile_flash"] = "An account with that email already exists."
        session["profile_flash_type"] = "err"
        return redirect(url_for("profile"))

    # move user data to new email key
    user_data = users.pop(email)
    user_data["email_verified"] = False
    users[new_email] = user_data
    save_users(users)

    # update ownership of pages and decks
    meta = load_meta()
    for pid, info in meta.items():
        if info.get("owner") == email:
            info["owner"] = new_email
    save_meta(meta)

    dm = load_decks_meta()
    for did, dinfo in dm.items():
        if dinfo.get("owner") == email:
            dinfo["owner"] = new_email
    save_decks_meta(dm)

    session["user_email"] = new_email
    send_email_changed_notification(email, new_email)
    if send_verification_email_with_url(new_email, request.host_url):
        session["profile_flash"] = f"Email changed to {new_email}. Please verify your new email."
        session["profile_flash_type"] = "ok"
    else:
        session["profile_flash"] = f"Email changed to {new_email}, but verification email failed. Please try again later."
        session["profile_flash_type"] = "err"
    return redirect(url_for("profile"))


@app.route("/profile/request-delete-account", methods=["POST"])
@login_required
@limiter.limit("3 per minute")
def request_delete_account():
    """Send account deletion confirmation email."""
    email = get_current_user()
    if send_delete_account_email(email, request.host_url):
        session["profile_flash"] = "Account deletion link sent to your email. Check your inbox."
        session["profile_flash_type"] = "ok"
    else:
        session["profile_flash"] = "Failed to send email. Please try again later."
        session["profile_flash_type"] = "err"
    return redirect(url_for("profile"))


@app.route("/confirm-delete-account")
@limiter.limit("5 per minute")
def confirm_delete_account():
    token = request.args.get("token", "")
    data = validate_token(token, "delete_account")
    if not data:
        return error_page(400, "Invalid or expired link",
                          "This deletion link is invalid or has expired.",
                          "Request a new one from your profile page.")
    email = data["email"]
    delete_user_account(email)
    if session.get("user_email") == email:
        session.pop("user_email", None)
    return error_page(200, "Account deleted",
                      "Your htmldrop account has been permanently deleted.",
                      "Your pages and decks still exist but are no longer linked to an account.")


# ---------------------------------------------------------------------------
# routes — admin
# ---------------------------------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin"))
        return render_template("login.html",
                               error_html='<div class="err">&#9888; incorrect username or password</div>')
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
        # notify owner
        owner = _get_item_owner(item_type, item_id)
        if owner:
            send_page_pinned_email(owner, item_type, item_id, pin_name)
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
            # notify owner
            owner = _get_item_owner(item_type, item_id)
            if owner:
                send_page_unpinned_email(owner, item_type, item_id)
        else:
            session["flash"] = "That item is not currently pinned."
            session["flash_type"] = "err"
    save_settings(s)
    return _admin_redirect()


@app.route("/admin/user/action", methods=["POST"])
@admin_required
def admin_user_action():
    op   = request.form.get("op", "")
    raw  = request.form.get("ids", "")
    # emails can contain @, ., etc so we split by comma
    ids  = [e.strip() for e in raw.split(",") if e.strip()]

    if not ids:
        session["flash"] = "No users selected."
        session["flash_type"] = "err"
    elif op == "delete":
        for email in ids:
            send_account_deleted_email(email)
            delete_user_account(email)
        n = len(ids)
        session["flash"] = f"Deleted {n} user{'s' if n != 1 else ''}."
        session["flash_type"] = "ok"
    elif op == "block":
        users = load_users()
        for email in ids:
            if email in users:
                users[email]["blocked"] = True
                send_blocked_email(email)
        save_users(users)
        n = len(ids)
        session["flash"] = f"Blocked {n} user{'s' if n != 1 else ''}."
        session["flash_type"] = "ok"
    elif op == "unblock":
        users = load_users()
        for email in ids:
            if email in users:
                users[email]["blocked"] = False
                send_unblocked_email(email)
        save_users(users)
        n = len(ids)
        session["flash"] = f"Unblocked {n} user{'s' if n != 1 else ''}."
        session["flash_type"] = "ok"
    else:
        session["flash"] = f"Unknown operation: {op}"
        session["flash_type"] = "err"

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