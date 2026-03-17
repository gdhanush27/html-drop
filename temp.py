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
from flask import Flask, request, redirect, url_for, abort, send_from_directory, Response, session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # bumped for multi-slide uploads

BASE       = os.path.dirname(os.path.abspath(__file__))
PAGES_DIR  = os.path.join(BASE, "pages")
DECKS_DIR  = os.path.join(BASE, "decks")
META_FILE  = os.path.join(BASE, "meta.json")
DECKS_META = os.path.join(BASE, "decks_meta.json")
os.makedirs(PAGES_DIR, exist_ok=True)
os.makedirs(DECKS_DIR, exist_ok=True)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ttpod123")

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
        import shutil
        shutil.rmtree(deck_dir)
    m = load_decks_meta()
    m.pop(deck_id, None)
    save_decks_meta(m)

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

# ---------------------------------------------------------------------------
# shared CSS
# ---------------------------------------------------------------------------

COMMON_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;800&family=JetBrains+Mono:wght@400;500&display=swap');
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
:root{
  --bg:#0c0c0e;--surface:#141418;--surface2:#1c1c22;--border:#252530;
  --border2:#2e2e3a;--text:#e8e8f0;--muted:#6b6b80;--muted2:#4a4a5a;
  --accent:#7fff7f;--accent-dim:#1a3d1a;--accent2:#ff7f7f;--accent2-dim:#3d1a1a;
  --warn:#ffd47f;--warn-dim:#3d2e0a;--info:#7fcfff;--info-dim:#0a2433;
  --r:6px;--mono:'JetBrains Mono',monospace;--sans:'Syne',sans-serif;
}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:var(--sans);}
body::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:9999;opacity:.35;
  background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.05'/%3E%3C/svg%3E");}
a{color:var(--accent);text-decoration:none;}a:hover{text-decoration:underline;}
@keyframes fadeD{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:translateY(0)}}
@keyframes fadeU{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
"""

# ---------------------------------------------------------------------------
# error page
# ---------------------------------------------------------------------------

def error_page(code, title, subtitle, detail, show_home=True):
    home = ('<a href="/" style="color:var(--accent);font-family:var(--mono);font-size:.8rem;">'
            '&#8592; back to htmldrop</a>') if show_home else ''
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>{code} &#8212; htmldrop</title>
  <style>
    {COMMON_CSS}
    body{{display:flex;align-items:center;justify-content:center;min-height:100vh;}}
    .box{{text-align:center;max-width:440px;padding:48px 32px;animation:fadeU .5s ease both;}}
    .code{{font-family:var(--mono);font-size:5rem;font-weight:800;letter-spacing:-.04em;line-height:1;
           background:linear-gradient(135deg,var(--text) 0%,var(--muted2) 100%);
           -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}}
    .title{{font-size:1.2rem;font-weight:700;margin:16px 0 8px;}}
    .sub{{font-family:var(--mono);font-size:.8rem;color:var(--muted);line-height:1.7;margin-bottom:6px;}}
    .detail{{font-family:var(--mono);font-size:.7rem;color:var(--muted2);margin-bottom:28px;}}
    .divider{{width:40px;height:1px;background:var(--border2);margin:20px auto;}}
  </style>
</head>
<body>
<div class="box">
  <div class="code">{code}</div>
  <div class="title">{title}</div>
  <div class="sub">{subtitle}</div>
  <div class="detail">{detail}</div>
  <div class="divider"></div>
  {home}
  <div style="margin-top:18px;font-family:var(--mono);font-size:.62rem;color:var(--muted2);">
    <a href="https://github.com/gdhanush27/html-drop" style="color:var(--muted);">github</a> &middot; <a href="https://github.com/gdhanush27" style="color:var(--muted);">@gdhanush27</a>
  </div>
</div>
</body></html>"""
    return Response(html, status=code, mimetype="text/html")

# ---------------------------------------------------------------------------
# index page
# ---------------------------------------------------------------------------

INDEX_TMPL = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>htmldrop</title>
  <style>
    %%CSS%%
    .layout{min-height:100vh;display:flex;flex-direction:column;max-width:860px;margin:0 auto;padding:0 24px;}
    header{padding:36px 0 24px;border-bottom:1px solid var(--border);animation:fadeD .4s ease both;display:flex;align-items:baseline;gap:14px;justify-content:space-between;flex-wrap:wrap;}
    .logo{font-size:1.5rem;font-weight:800;letter-spacing:-.04em;}
    .logo span{color:var(--accent);}
    .tagline{font-family:var(--mono);font-size:.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;}
    .header-nav{display:flex;gap:8px;align-items:center;flex-wrap:wrap;}
    .nav-link{font-family:var(--mono);font-size:.72rem;color:var(--muted);border:1px solid var(--border);border-radius:var(--r);padding:6px 12px;transition:color .15s,border-color .15s;}
    .nav-link:hover{color:var(--text);border-color:var(--border2);text-decoration:none;}
    .nav-link.accent{color:var(--accent);border-color:rgba(127,255,127,.3);}
    .nav-link.accent:hover{background:var(--accent-dim);}
    main{flex:1;padding:36px 0;animation:fadeU .4s ease .1s both;}
    .sect{font-family:var(--mono);font-size:.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:.12em;margin-bottom:12px;display:flex;align-items:center;gap:8px;}
    .sect::before{content:'';display:inline-block;width:16px;height:1px;background:var(--muted);}
    .tabs{display:flex;border-bottom:1px solid var(--border);}
    .tab{font-family:var(--mono);font-size:.76rem;padding:9px 18px;cursor:pointer;color:var(--muted);border:1px solid transparent;border-bottom:none;background:none;border-radius:var(--r) var(--r) 0 0;margin-bottom:-1px;transition:color .15s,border-color .15s,background .15s;}
    .tab:hover{color:var(--text);}
    .tab.active{color:var(--accent);border-color:var(--border);background:var(--surface);border-bottom-color:var(--surface);}
    .panel{display:none;background:var(--surface);border:1px solid var(--border);border-top:none;border-radius:0 var(--r) var(--r) var(--r);padding:20px;}
    .panel.active{display:block;}
    textarea{width:100%;height:300px;background:var(--bg);border:1px solid var(--border);border-radius:var(--r);color:var(--text);font-family:var(--mono);font-size:.8rem;line-height:1.7;padding:14px;resize:vertical;outline:none;transition:border-color .2s,box-shadow .2s;}
    textarea:focus{border-color:var(--border2);box-shadow:0 0 0 3px rgba(127,255,127,.06);}
    textarea::placeholder{color:var(--muted);}
    .dropzone{border:1.5px dashed var(--border);border-radius:var(--r);padding:56px 24px;text-align:center;cursor:pointer;transition:border-color .2s,background .2s;position:relative;}
    .dropzone:hover,.dropzone.over{border-color:var(--accent);background:var(--accent-dim);}
    .dropzone input[type=file]{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;height:100%;}
    .dz-icon{font-size:2rem;display:block;margin-bottom:10px;}
    .dz-text{font-family:var(--mono);font-size:.8rem;color:var(--muted);line-height:1.6;}
    .dz-text strong{color:var(--text);display:block;margin-bottom:4px;}
    .file-name{font-family:var(--mono);font-size:.78rem;color:var(--accent);margin-top:10px;}
    .row{margin-top:14px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;}
    .hint{font-family:var(--mono);font-size:.68rem;color:var(--muted);}
    button[type=submit]{font-family:var(--sans);font-weight:600;font-size:.86rem;background:var(--accent);color:#0a1a0a;border:none;border-radius:var(--r);padding:10px 26px;cursor:pointer;transition:transform .15s,box-shadow .15s;}
    button[type=submit]:hover{transform:translateY(-1px);box-shadow:0 4px 18px rgba(127,255,127,.22);}
    button[type=submit]:active{transform:translateY(0);}
    .error{background:rgba(255,95,95,.1);border:1px solid rgba(255,95,95,.3);border-radius:var(--r);padding:11px 15px;margin-bottom:20px;font-family:var(--mono);font-size:.78rem;color:var(--accent2);}
    .result{background:var(--accent-dim);border:1px solid rgba(127,255,127,.2);border-radius:var(--r);padding:15px 18px;margin-bottom:26px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;}
    .rlabel{font-family:var(--mono);font-size:.68rem;color:var(--accent);text-transform:uppercase;letter-spacing:.1em;margin-bottom:3px;}
    .rurl{font-family:var(--mono);font-size:.83rem;color:var(--text);word-break:break-all;}
    .copy-btn{font-family:var(--mono);font-size:.73rem;background:none;border:1px solid var(--accent);color:var(--accent);border-radius:var(--r);padding:7px 13px;cursor:pointer;white-space:nowrap;transition:background .15s,color .15s;}
    .copy-btn:hover{background:var(--accent);color:#0a1a0a;}
    .how{margin-top:44px;padding-top:28px;border-top:1px solid var(--border);display:grid;grid-template-columns:repeat(3,1fr);gap:20px;}
    .how-item{padding:18px;background:var(--surface);border:1px solid var(--border);border-radius:var(--r);}
    .how-num{font-family:var(--mono);font-size:.68rem;color:var(--accent);margin-bottom:8px;}
    .how-title{font-size:.92rem;font-weight:600;margin-bottom:5px;}
    .how-desc{font-family:var(--mono);font-size:.7rem;color:var(--muted);line-height:1.6;}
    footer{border-top:1px solid var(--border);padding:18px 0;font-family:var(--mono);font-size:.66rem;color:var(--muted);display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px;}
    @media(max-width:600px){.how{grid-template-columns:1fr}}
  </style>
</head>
<body>
<div class="layout">
  <header>
    <div style="display:flex;align-items:baseline;gap:14px">
      <div class="logo">html<span>drop</span></div>
      <div class="tagline">instant html sharing</div>
    </div>
    <div class="header-nav">
      <a href="/deck" class="nav-link accent">&#9707; slides</a>
      <a href="/admin" class="nav-link">admin &#8599;</a>
    </div>
  </header>
  <main>
    %%ERROR%%
    %%RESULT%%
    <div class="sect">create or share a page</div>
    <div class="tabs">
      <button class="tab active" onclick="switchTab('paste',this)">paste html</button>
      <button class="tab" onclick="switchTab('upload',this)">upload file</button>
    </div>
    <div id="panel-paste" class="panel active">
      <form method="POST" action="/share" enctype="multipart/form-data">
        <textarea name="html" spellcheck="false" placeholder="<!DOCTYPE html>&#10;<html>&#10;  <body><h1>Hello!</h1></body>&#10;</html>">%%PREFILL%%</textarea>
        <div class="row">
          <span class="hint">any self-contained html · max 2 MB</span>
          <button type="submit">publish &#8594;</button>
        </div>
      </form>
    </div>
    <div id="panel-upload" class="panel">
      <form method="POST" action="/share" enctype="multipart/form-data">
        <div class="dropzone" id="dz">
          <input type="file" name="file" accept=".html,.htm" onchange="fileChosen(this)"/>
          <span class="dz-icon">&#8679;</span>
          <div class="dz-text"><strong>drop an .html file here</strong>or click to browse</div>
          <div class="file-name" id="fname"></div>
        </div>
        <div class="row">
          <span class="hint">.html / .htm · max 2 MB</span>
          <button type="submit">publish &#8594;</button>
        </div>
      </form>
    </div>
    <div class="how">
      <div class="how-item"><div class="how-num">01</div><div class="how-title">paste or upload</div><div class="how-desc">Drop any self-contained HTML &#8212; inline CSS, JS, everything welcome.</div></div>
      <div class="how-item"><div class="how-num">02</div><div class="how-title">get a link</div><div class="how-desc">Receive a short permanent URL to your fully rendered page.</div></div>
      <div class="how-item"><div class="how-num">03</div><div class="how-title">share it</div><div class="how-desc">Anyone with the link can view it. Append /source to remix.</div></div>
    </div>
  </main>
  <footer><span>htmldrop &middot; <a href="https://github.com/gdhanush27/html-drop">github</a> &middot; <a href="https://github.com/gdhanush27">@gdhanush27</a></span><span>pages stored locally &#183; no accounts needed</span></footer>
</div>
<script>
function switchTab(n,btn){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('panel-'+n).classList.add('active');
}
function fileChosen(i){document.getElementById('fname').textContent=i.files[0]?'&#128196; '+i.files[0].name:'';}
const dz=document.getElementById('dz');
dz.addEventListener('dragover',()=>dz.classList.add('over'));
dz.addEventListener('dragleave',()=>dz.classList.remove('over'));
dz.addEventListener('drop',()=>dz.classList.remove('over'));
function copyUrl(){
  navigator.clipboard.writeText(document.getElementById('rurl').textContent).then(()=>{
    const b=document.querySelector('.copy-btn');b.textContent='copied!';
    setTimeout(()=>b.textContent='copy link',2000);
  });
}
</script>
</body></html>"""

def render_index(error="", page_id="", prefill="", host=""):
    error_html  = f'<div class="error">&#9888; {error}</div>' if error else ""
    result_html = ""
    if page_id:
        url = f"{host}p/{page_id}"
        result_html = (f'<div class="result">'
                       f'<div><div class="rlabel">&#10003; your page is live</div>'
                       f'<div class="rurl" id="rurl">{url}</div></div>'
                       f'<button class="copy-btn" onclick="copyUrl()">copy link</button>'
                       f'</div>')
    safe = prefill.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = (INDEX_TMPL
            .replace("%%CSS%%", COMMON_CSS)
            .replace("%%ERROR%%", error_html)
            .replace("%%RESULT%%", result_html)
            .replace("%%PREFILL%%", safe))
    return Response(html, mimetype="text/html")

# ---------------------------------------------------------------------------
# deck creation page
# ---------------------------------------------------------------------------

DECK_CSS = """
.layout{min-height:100vh;display:flex;flex-direction:column;max-width:900px;margin:0 auto;padding:0 24px;}
header{padding:36px 0 24px;border-bottom:1px solid var(--border);animation:fadeD .4s ease both;display:flex;align-items:center;gap:14px;justify-content:space-between;flex-wrap:wrap;}
.logo{font-size:1.5rem;font-weight:800;letter-spacing:-.04em;}
.logo span{color:var(--accent);}
.tagline{font-family:var(--mono);font-size:.7rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;}
.header-nav{display:flex;gap:8px;}
.nav-link{font-family:var(--mono);font-size:.72rem;color:var(--muted);border:1px solid var(--border);border-radius:var(--r);padding:6px 12px;transition:color .15s,border-color .15s;}
.nav-link:hover{color:var(--text);border-color:var(--border2);text-decoration:none;}
main{flex:1;padding:36px 0;animation:fadeU .4s ease .1s both;}
.sect{font-family:var(--mono);font-size:.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:.12em;margin-bottom:12px;display:flex;align-items:center;gap:8px;}
.sect::before{content:'';display:inline-block;width:16px;height:1px;background:var(--muted);}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:24px;}
label.field-label{font-family:var(--mono);font-size:.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;display:block;margin-bottom:7px;}
input[type=text]{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:var(--r);color:var(--text);font-family:var(--mono);font-size:.85rem;padding:10px 12px;outline:none;transition:border-color .2s;margin-bottom:20px;}
input[type=text]:focus{border-color:var(--border2);}
input[type=text]::placeholder{color:var(--muted2);}
.slides-area{display:flex;flex-direction:column;gap:12px;margin-bottom:14px;}
.slide-card{background:var(--bg);border:1px solid var(--border);border-radius:var(--r);overflow:hidden;transition:border-color .2s;}
.slide-card:hover{border-color:var(--border2);}
.slide-card.drag-over{border-color:var(--accent);background:var(--accent-dim);}
.slide-header{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--border);cursor:grab;user-select:none;}
.slide-header:active{cursor:grabbing;}
.drag-handle{color:var(--muted2);font-size:.9rem;flex-shrink:0;}
.slide-num{font-family:var(--mono);font-size:.68rem;color:var(--accent);font-weight:600;min-width:24px;}
.slide-title-input{flex:1;background:transparent;border:none;color:var(--text);font-family:var(--mono);font-size:.8rem;outline:none;padding:2px 0;}
.slide-title-input::placeholder{color:var(--muted2);}
.slide-remove{background:none;border:none;color:var(--muted2);cursor:pointer;font-size:1rem;padding:2px 6px;border-radius:3px;transition:color .15s,background .15s;flex-shrink:0;}
.slide-remove:hover{color:var(--accent2);background:var(--accent2-dim);}
.slide-body{padding:12px;}
textarea.slide-ta{width:100%;height:180px;background:transparent;border:none;color:var(--text);font-family:var(--mono);font-size:.75rem;line-height:1.7;resize:vertical;outline:none;}
textarea.slide-ta::placeholder{color:var(--muted2);}
.add-slide-btn{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;padding:13px;background:none;border:1.5px dashed var(--border);border-radius:var(--r);color:var(--muted);font-family:var(--mono);font-size:.78rem;cursor:pointer;transition:border-color .2s,color .2s,background .2s;margin-bottom:20px;}
.add-slide-btn:hover{border-color:var(--accent);color:var(--accent);background:var(--accent-dim);}
.row{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;}
.hint{font-family:var(--mono);font-size:.68rem;color:var(--muted);}
button[type=submit]{font-family:var(--sans);font-weight:600;font-size:.86rem;background:var(--accent);color:#0a1a0a;border:none;border-radius:var(--r);padding:10px 26px;cursor:pointer;transition:transform .15s,box-shadow .15s;}
button[type=submit]:hover{transform:translateY(-1px);box-shadow:0 4px 18px rgba(127,255,127,.22);}
.error{background:rgba(255,95,95,.1);border:1px solid rgba(255,95,95,.3);border-radius:var(--r);padding:11px 15px;margin-bottom:20px;font-family:var(--mono);font-size:.78rem;color:var(--accent2);}
.result{background:var(--accent-dim);border:1px solid rgba(127,255,127,.2);border-radius:var(--r);padding:15px 18px;margin-bottom:26px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;}
.rlabel{font-family:var(--mono);font-size:.68rem;color:var(--accent);text-transform:uppercase;letter-spacing:.1em;margin-bottom:3px;}
.rurl{font-family:var(--mono);font-size:.83rem;color:var(--text);word-break:break-all;}
.copy-btn{font-family:var(--mono);font-size:.73rem;background:none;border:1px solid var(--accent);color:var(--accent);border-radius:var(--r);padding:7px 13px;cursor:pointer;white-space:nowrap;transition:background .15s,color .15s;}
.copy-btn:hover{background:var(--accent);color:#0a1a0a;}
.upload-zone{border:1.5px dashed var(--border);border-radius:var(--r);padding:32px 24px;text-align:center;cursor:pointer;transition:border-color .2s,background .2s;position:relative;margin-bottom:16px;}
.upload-zone:hover,.upload-zone.over{border-color:var(--accent);background:var(--accent-dim);}
.upload-zone input[type=file]{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;height:100%;}
.upload-zone-text{font-family:var(--mono);font-size:.78rem;color:var(--muted);line-height:1.6;}
.upload-zone-text strong{color:var(--text);display:block;margin-bottom:4px;}
.tabs{display:flex;border-bottom:1px solid var(--border);}
.tab{font-family:var(--mono);font-size:.76rem;padding:9px 18px;cursor:pointer;color:var(--muted);border:1px solid transparent;border-bottom:none;background:none;border-radius:var(--r) var(--r) 0 0;margin-bottom:-1px;transition:color .15s,border-color .15s,background .15s;}
.tab:hover{color:var(--text);}
.tab.active{color:var(--accent);border-color:var(--border);background:var(--surface);border-bottom-color:var(--surface);}
.panel{display:none;background:var(--surface);border:1px solid var(--border);border-top:none;border-radius:0 var(--r) var(--r) var(--r);padding:20px;}
.panel.active{display:block;}
footer{border-top:1px solid var(--border);padding:18px 0;font-family:var(--mono);font-size:.66rem;color:var(--muted);display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px;}
"""

DECK_PAGE_TMPL = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>slides &#8212; htmldrop</title>
  <style>%%CSS%%%%DECK_CSS%%</style>
</head>
<body>
<div class="layout">
  <header>
    <div style="display:flex;align-items:baseline;gap:14px">
      <div class="logo">html<span>drop</span></div>
      <div class="tagline">html slides</div>
    </div>
    <div class="header-nav">
      <a href="/" class="nav-link">&#8592; home</a>
    </div>
  </header>
  <main>
    %%ERROR%%
    %%RESULT%%
    <div class="sect">create a slide deck</div>

    <div class="tabs">
      <button class="tab active" onclick="switchTab('paste',this)">paste slides</button>
      <button class="tab" onclick="switchTab('upload',this)">upload files</button>
    </div>

    <!-- PASTE TAB -->
    <div id="panel-paste" class="panel active">
      <form id="paste-form" method="POST" action="/deck/create">
        <label class="field-label" style="margin-top:4px">deck title</label>
        <input type="text" name="title" placeholder="My Awesome Deck" maxlength="120"/>
        <div id="slides-area" class="slides-area"></div>
        <button type="button" class="add-slide-btn" onclick="addSlide()">+ add slide</button>
        <div class="row">
          <span class="hint">each slide is self-contained html · drag to reorder</span>
          <button type="submit">publish deck &#8594;</button>
        </div>
      </form>
    </div>

    <!-- UPLOAD TAB -->
    <div id="panel-upload" class="panel">
      <form method="POST" action="/deck/create" enctype="multipart/form-data">
        <label class="field-label">deck title</label>
        <input type="text" name="title" placeholder="My Awesome Deck" maxlength="120"/>
        <div class="upload-zone" id="udz">
          <input type="file" name="files" accept=".html,.htm" multiple onchange="filesChosen(this)"/>
          <span style="font-size:2rem;display:block;margin-bottom:8px">&#9707;</span>
          <div class="upload-zone-text">
            <strong>drop multiple .html files here</strong>
            files will become slides in alphabetical order
          </div>
          <div id="ufiles" style="font-family:var(--mono);font-size:.75rem;color:var(--accent);margin-top:10px;"></div>
        </div>
        <div class="row">
          <span class="hint">.html / .htm · up to 20 slides · max 10 MB total</span>
          <button type="submit">publish deck &#8594;</button>
        </div>
      </form>
    </div>

  </main>
  <footer><span>htmldrop slides &middot; <a href="https://github.com/gdhanush27/html-drop">github</a> &middot; <a href="https://github.com/gdhanush27">@gdhanush27</a></span><span>keyboard-navigable html decks &middot; no accounts needed</span></footer>
</div>

<script>
var slideCount = 0;
var dragSrc = null;

function switchTab(n, btn) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('panel-' + n).classList.add('active');
}

function addSlide(html, title) {
  slideCount++;
  var area = document.getElementById('slides-area');
  var div = document.createElement('div');
  div.className = 'slide-card';
  div.draggable = true;
  div.dataset.idx = slideCount;
  div.innerHTML =
    '<div class="slide-header">' +
      '<span class="drag-handle">&#8597;</span>' +
      '<span class="slide-num">' + String(slideCount).padStart(2,'0') + '</span>' +
      '<input class="slide-title-input" type="text" name="slide_title[]" placeholder="Slide ' + slideCount + ' title (optional)" value="' + (title||'') + '"/>' +
      '<button type="button" class="slide-remove" onclick="removeSlide(this)" title="Remove slide">&#215;</button>' +
    '</div>' +
    '<div class="slide-body">' +
      '<textarea class="slide-ta" name="slide_html[]" spellcheck="false" placeholder="<!-- Paste your slide HTML here -->&#10;<!DOCTYPE html><html><body>...</body></html>">' +
        escapeHtml(html || '') +
      '</textarea>' +
    '</div>';

  // drag events
  div.addEventListener('dragstart', function(e) {
    dragSrc = div;
    e.dataTransfer.effectAllowed = 'move';
    setTimeout(() => div.style.opacity = '0.4', 0);
  });
  div.addEventListener('dragend', function() {
    div.style.opacity = '';
    document.querySelectorAll('.slide-card').forEach(c => c.classList.remove('drag-over'));
    renumber();
  });
  div.addEventListener('dragover', function(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (dragSrc !== div) div.classList.add('drag-over');
  });
  div.addEventListener('dragleave', function() { div.classList.remove('drag-over'); });
  div.addEventListener('drop', function(e) {
    e.preventDefault();
    div.classList.remove('drag-over');
    if (dragSrc && dragSrc !== div) {
      var area = document.getElementById('slides-area');
      var cards = [...area.children];
      var fromIdx = cards.indexOf(dragSrc);
      var toIdx = cards.indexOf(div);
      if (fromIdx < toIdx) area.insertBefore(dragSrc, div.nextSibling);
      else area.insertBefore(dragSrc, div);
    }
  });

  area.appendChild(div);
  renumber();
}

function removeSlide(btn) {
  btn.closest('.slide-card').remove();
  renumber();
}

function renumber() {
  document.querySelectorAll('.slide-card').forEach(function(c, i) {
    var num = c.querySelector('.slide-num');
    if (num) num.textContent = String(i+1).padStart(2,'0');
  });
}

function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function filesChosen(input) {
  var names = [...input.files].map(f => '&#128196; ' + f.name).join('<br>');
  document.getElementById('ufiles').innerHTML = names || '';
}

var udz = document.getElementById('udz');
if (udz) {
  udz.addEventListener('dragover', () => udz.classList.add('over'));
  udz.addEventListener('dragleave', () => udz.classList.remove('over'));
  udz.addEventListener('drop', () => udz.classList.remove('over'));
}

// Add 3 starter slides
addSlide('', '');
addSlide('', '');
addSlide('', '');

function copyUrl() {
  var el = document.getElementById('rurl');
  if (!el) return;
  navigator.clipboard.writeText(el.textContent).then(() => {
    var b = document.querySelector('.copy-btn');
    b.textContent = 'copied!';
    setTimeout(() => b.textContent = 'copy link', 2000);
  });
}
</script>
</body></html>"""

def render_deck_page(error="", deck_id="", host=""):
    error_html  = f'<div class="error">&#9888; {error}</div>' if error else ""
    result_html = ""
    if deck_id:
        url = f"{host}d/{deck_id}"
        result_html = (f'<div class="result">'
                       f'<div><div class="rlabel">&#10003; your deck is live</div>'
                       f'<div class="rurl" id="rurl">{url}</div></div>'
                       f'<button class="copy-btn" onclick="copyUrl()">copy link</button>'
                       f'</div>')
    html = (DECK_PAGE_TMPL
            .replace("%%CSS%%", COMMON_CSS)
            .replace("%%DECK_CSS%%", DECK_CSS)
            .replace("%%ERROR%%", error_html)
            .replace("%%RESULT%%", result_html))
    return Response(html, mimetype="text/html")

# ---------------------------------------------------------------------------
# deck viewer
# ---------------------------------------------------------------------------

def build_deck_viewer(deck_id, slides, title):
    """Build a self-contained full-screen slide viewer."""
    # slides: list of {"title": str, "html": str}
    slides_json = json.dumps([{"title": s["title"], "html": s["html"]} for s in slides])
    # Escape sequences that would break embedding inside <script>: </script> and <!--
    slides_json = slides_json.replace("</", "<\\/")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>{title} &#8212; htmldrop slides</title>
  <style>
    {COMMON_CSS}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    body{{overflow:hidden;display:flex;flex-direction:column;height:100vh;background:var(--bg);}}
    body::before{{display:none !important;}}

    /* ---- top bar ---- */
    #topbar{{
      display:flex;align-items:center;justify-content:space-between;
      padding:0 20px;height:44px;flex-shrink:0;
      background:var(--surface);border-bottom:1px solid var(--border);
      animation:fadeD .3s ease both;z-index:10;
    }}
    #topbar-left{{display:flex;align-items:center;gap:14px;}}
    #deck-title{{font-size:.9rem;font-weight:700;letter-spacing:-.02em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:340px;}}
    #slide-title{{font-family:var(--mono);font-size:.72rem;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:220px;}}
    #topbar-right{{display:flex;align-items:center;gap:8px;}}
    .tb-btn{{font-family:var(--mono);font-size:.68rem;color:var(--muted);border:1px solid var(--border);border-radius:var(--r);padding:5px 10px;background:none;cursor:pointer;transition:color .15s,border-color .15s;white-space:nowrap;}}
    .tb-btn:hover{{color:var(--text);border-color:var(--border2);}}
    #progress-text{{font-family:var(--mono);font-size:.72rem;color:var(--muted);min-width:56px;text-align:right;}}

    /* ---- slide stage ---- */
    #stage{{
      flex:1;position:relative;overflow:hidden;
    }}
    .slide-frame{{
      position:absolute;top:0;left:0;
      border:none;background:#fff;
      transform-origin:0 0;
      transition:opacity .22s ease;
    }}
    .slide-frame.hidden{{opacity:0;pointer-events:none;}}
    .slide-frame.entering-right{{opacity:0;}}
    .slide-frame.entering-left{{opacity:0;}}

    /* ---- bottom nav bar ---- */
    #navbar{{
      display:flex;align-items:center;justify-content:center;gap:14px;
      padding:0 24px;height:52px;flex-shrink:0;
      background:var(--surface);border-top:1px solid var(--border);
      animation:fadeU .3s ease both;z-index:10;
    }}
    .nav-btn{{
      font-family:var(--mono);font-size:.8rem;color:var(--muted);
      border:1px solid var(--border);border-radius:var(--r);
      padding:7px 14px;background:none;cursor:pointer;
      transition:color .15s,border-color .15s,background .15s;
      display:flex;align-items:center;gap:6px;
    }}
    .nav-btn:hover{{color:var(--text);border-color:var(--border2);}}
    .nav-btn:disabled{{opacity:.3;cursor:default;}}
    .nav-btn:disabled:hover{{color:var(--muted);border-color:var(--border);background:none;}}
    #dot-nav{{display:flex;align-items:center;gap:6px;flex-wrap:wrap;justify-content:center;max-width:480px;}}
    .dot{{width:8px;height:8px;border-radius:50%;background:var(--border2);cursor:pointer;transition:background .2s,transform .2s;border:none;padding:0;flex-shrink:0;}}
    .dot:hover{{background:var(--muted);transform:scale(1.3);}}
    .dot.active{{background:var(--accent);transform:scale(1.25);}}

    /* ---- hotkey toast ---- */
    #toast{{
      position:fixed;bottom:72px;left:50%;transform:translateX(-50%);
      background:var(--surface2);border:1px solid var(--border2);
      border-radius:var(--r);padding:10px 18px;
      font-family:var(--mono);font-size:.75rem;color:var(--text);
      opacity:0;transition:opacity .25s;pointer-events:none;z-index:50;
      white-space:nowrap;
    }}
    #toast.show{{opacity:1;}}

    /* ---- hotkeys panel ---- */
    #hotkeys-panel{{
      position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:200;
      display:none;align-items:center;justify-content:center;
    }}
    #hotkeys-panel.open{{display:flex;animation:fadeIn .2s ease;}}
    .hk-box{{
      background:var(--surface);border:1px solid var(--border2);border-radius:var(--r);
      padding:32px 36px;max-width:420px;width:90%;
    }}
    .hk-box h3{{font-size:1rem;font-weight:700;margin-bottom:18px;}}
    .hk-row{{display:flex;justify-content:space-between;align-items:center;
             padding:7px 0;border-bottom:1px solid var(--border);font-family:var(--mono);font-size:.78rem;}}
    .hk-row:last-child{{border-bottom:none;}}
    .hk-key{{background:var(--bg);border:1px solid var(--border2);border-radius:4px;
             padding:2px 8px;font-size:.72rem;color:var(--accent);}}
    .hk-close{{margin-top:20px;width:100%;font-family:var(--mono);font-size:.78rem;
               background:none;border:1px solid var(--border);border-radius:var(--r);
               color:var(--muted);padding:8px;cursor:pointer;transition:color .15s;}}
    .hk-close:hover{{color:var(--text);}}

    /* fullscreen adjustments */
    :fullscreen #topbar, :fullscreen #navbar{{background:rgba(12,12,14,.92);backdrop-filter:blur(8px);}}
    :-webkit-full-screen #topbar, :-webkit-full-screen #navbar{{background:rgba(12,12,14,.92);}}
  </style>
</head>
<body>

<div id="topbar">
  <div id="topbar-left">
    <div id="deck-title">{title}</div>
    <div id="slide-title"></div>
  </div>
  <div id="topbar-right">
    <span id="progress-text">1 / 1</span>
    <button class="tb-btn" onclick="toggleHotkeys()">&#9000; keys</button>
    <button class="tb-btn" id="fs-btn" onclick="toggleFullscreen()">&#9645; fullscreen</button>
    <a href="/" class="tb-btn" style="color:var(--muted);text-decoration:none;">&#8592; home</a>
  </div>
</div>

<div id="stage"></div>

<div id="navbar">
  <button class="nav-btn" id="btn-prev" onclick="prev()" title="Previous (← or Backspace)">&#8592; prev</button>
  <div id="dot-nav"></div>
  <button class="nav-btn" id="btn-next" onclick="next()" title="Next (→ or Space)">next &#8594;</button>
</div>

<div id="toast"></div>

<div id="hotkeys-panel">
  <div class="hk-box">
    <h3>keyboard shortcuts</h3>
    <div class="hk-row"><span>next slide</span><span><span class="hk-key">→</span> &nbsp;<span class="hk-key">Space</span></span></div>
    <div class="hk-row"><span>previous slide</span><span><span class="hk-key">←</span> &nbsp;<span class="hk-key">Backspace</span></span></div>
    <div class="hk-row"><span>first slide</span><span><span class="hk-key">Home</span></span></div>
    <div class="hk-row"><span>last slide</span><span><span class="hk-key">End</span></span></div>
    <div class="hk-row"><span>fullscreen</span><span><span class="hk-key">F</span></span></div>
    <div class="hk-row"><span>close fullscreen</span><span><span class="hk-key">Esc</span></span></div>
    <div class="hk-row"><span>this help</span><span><span class="hk-key">?</span></span></div>
    <button class="hk-close" onclick="toggleHotkeys()">close</button>
  </div>
</div>

<script>
var SLIDES = {slides_json};
var current = 0;
var frames = [];
var dots = [];

function init() {{
  var stage = document.getElementById('stage');
  var dotNav = document.getElementById('dot-nav');

  SLIDES.forEach(function(slide, i) {{
    // create iframe
    var fr = document.createElement('iframe');
    fr.className = 'slide-frame' + (i === 0 ? '' : ' hidden');
    fr.setAttribute('sandbox', 'allow-scripts allow-same-origin');
    fr.setAttribute('title', slide.title || ('Slide ' + (i+1)));
    stage.appendChild(fr);
    frames.push(fr);

    // load content via srcdoc for full CSS/JS isolation
    fr.srcdoc = slide.html;

    // forward keyboard events from iframe to parent so hotkeys work
    (function(iframe) {{
      iframe.addEventListener('load', function() {{
        try {{
          var idoc = iframe.contentDocument || iframe.contentWindow.document;
          idoc.addEventListener('keydown', function(e) {{
            var evt = new KeyboardEvent('keydown', {{
              key: e.key, code: e.code, keyCode: e.keyCode,
              ctrlKey: e.ctrlKey, shiftKey: e.shiftKey, altKey: e.altKey, metaKey: e.metaKey
            }});
            document.dispatchEvent(evt);
            if (e.key === ' ') e.preventDefault();
          }});
        }} catch(ex) {{}}
      }});
    }})(fr);

    // dot
    var dot = document.createElement('button');
    dot.className = 'dot' + (i === 0 ? ' active' : '');
    dot.title = slide.title || ('Slide ' + (i+1));
    dot.onclick = (function(idx) {{ return function() {{ goTo(idx); }}; }})(i);
    dotNav.appendChild(dot);
    dots.push(dot);
  }});

  update();
}}

function goTo(idx, dir) {{
  if (idx < 0 || idx >= SLIDES.length) return;
  var oldFrame = frames[current];
  var newFrame = frames[idx];
  var direction = dir !== undefined ? dir : (idx > current ? 'right' : 'left');

  oldFrame.classList.add('hidden');
  newFrame.classList.remove('hidden');
  newFrame.classList.add('entering-' + direction);
  requestAnimationFrame(function() {{
    requestAnimationFrame(function() {{
      newFrame.classList.remove('entering-right', 'entering-left');
    }});
  }});

  dots[current].classList.remove('active');
  dots[idx].classList.add('active');
  current = idx;
  update();
}}

function next() {{ if (current < SLIDES.length-1) goTo(current+1, 'right'); }}
function prev() {{ if (current > 0) goTo(current-1, 'left'); }}

function update() {{
  var total = SLIDES.length;
  document.getElementById('progress-text').textContent = (current+1) + ' / ' + total;
  document.getElementById('slide-title').textContent = SLIDES[current].title || '';
  document.getElementById('btn-prev').disabled = current === 0;
  document.getElementById('btn-next').disabled = current === total-1;
}}

function toggleFullscreen() {{
  if (!document.fullscreenElement) {{
    document.documentElement.requestFullscreen().catch(function(){{}});
    document.getElementById('fs-btn').textContent = '\u25a1 exit full';
  }} else {{
    document.exitFullscreen();
    document.getElementById('fs-btn').textContent = '\u25ad fullscreen';
  }}
}}

function toggleHotkeys() {{
  var p = document.getElementById('hotkeys-panel');
  p.classList.toggle('open');
}}

document.addEventListener('keydown', function(e) {{
  if (document.getElementById('hotkeys-panel').classList.contains('open')) {{
    if (e.key === 'Escape' || e.key === '?') toggleHotkeys();
    return;
  }}
  switch(e.key) {{
    case 'ArrowRight': case 'ArrowDown': next(); break;
    case 'ArrowLeft':  case 'ArrowUp':  prev(); break;
    case ' ':  e.preventDefault(); next(); break;
    case 'Backspace': prev(); break;
    case 'Home': goTo(0); break;
    case 'End':  goTo(SLIDES.length-1); break;
    case 'f': case 'F': toggleFullscreen(); break;
    case '?': toggleHotkeys(); break;
  }}
}});

// swipe support
var touchStartX = 0;
document.addEventListener('touchstart', function(e) {{ touchStartX = e.touches[0].clientX; }}, {{passive:true}});
document.addEventListener('touchend', function(e) {{
  var dx = e.changedTouches[0].clientX - touchStartX;
  if (Math.abs(dx) > 50) {{ if (dx < 0) next(); else prev(); }}
}}, {{passive:true}});

function scaleFrames() {{
  var stage = document.getElementById('stage');
  var sw = stage.clientWidth, sh = stage.clientHeight;
  if (!sw || !sh) return;
  var nw = 1280, nh = 720;
  var scale = Math.min(sw / nw, sh / nh);
  var scaledW = nw * scale, scaledH = nh * scale;
  var ox = Math.round((sw - scaledW) / 2);
  var oy = Math.round((sh - scaledH) / 2);
  frames.forEach(function(fr) {{
    fr.style.width = nw + 'px';
    fr.style.height = nh + 'px';
    fr.style.left = ox + 'px';
    fr.style.top = oy + 'px';
    fr.style.transform = 'scale(' + scale + ')';
  }});
}}

window.addEventListener('resize', scaleFrames);
document.addEventListener('fullscreenchange', function() {{
  if (!document.fullscreenElement)
    document.getElementById('fs-btn').textContent = '\u25ad fullscreen';
  setTimeout(scaleFrames, 50);
}});

init();
scaleFrames();
</script>
</body>
</html>"""
    return html

# ---------------------------------------------------------------------------
# login page
# ---------------------------------------------------------------------------

LOGIN_TMPL = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Admin Login &#8212; htmldrop</title>
  <style>
    %%CSS%%
    body{display:flex;align-items:center;justify-content:center;min-height:100vh;}
    .box{width:100%;max-width:360px;padding:0 24px;animation:fadeU .4s ease both;}
    .logo{font-size:1.4rem;font-weight:800;letter-spacing:-.04em;text-align:center;margin-bottom:6px;}
    .logo span{color:var(--accent);}
    .sub{font-family:var(--mono);font-size:.7rem;color:var(--muted);text-align:center;margin-bottom:32px;text-transform:uppercase;letter-spacing:.08em;}
    .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:28px;}
    label{font-family:var(--mono);font-size:.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;display:block;margin-bottom:6px;}
    input[type=password]{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:var(--r);color:var(--text);font-family:var(--mono);font-size:.85rem;padding:10px 12px;outline:none;transition:border-color .2s;margin-bottom:16px;}
    input[type=password]:focus{border-color:var(--border2);}
    .submit{width:100%;font-family:var(--sans);font-weight:700;font-size:.9rem;background:var(--accent);color:#0a1a0a;border:none;border-radius:var(--r);padding:11px;cursor:pointer;transition:transform .15s,box-shadow .15s;}
    .submit:hover{transform:translateY(-1px);box-shadow:0 4px 18px rgba(127,255,127,.2);}
    .err{background:rgba(255,95,95,.1);border:1px solid rgba(255,95,95,.3);border-radius:var(--r);padding:9px 12px;font-family:var(--mono);font-size:.75rem;color:var(--accent2);margin-bottom:14px;}
    .back{text-align:center;margin-top:18px;font-family:var(--mono);font-size:.7rem;}
    .back a{color:var(--muted);}
  </style>
</head>
<body>
<div class="box">
  <div class="logo">html<span>drop</span></div>
  <div class="sub">admin access</div>
  <div class="card">
    %%ERROR%%
    <form method="POST" action="/admin/login">
      <label>password</label>
      <input type="password" name="password" autofocus placeholder="&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;"/>
      <button type="submit" class="submit">enter &#8594;</button>
    </form>
  </div>
  <div class="back"><a href="/">&#8592; back to htmldrop</a></div>
  <div style="text-align:center;margin-top:12px;font-family:var(--mono);font-size:.62rem;color:var(--muted2);">
    <a href="https://github.com/gdhanush27/html-drop" style="color:var(--muted);">github</a> &middot; <a href="https://github.com/gdhanush27" style="color:var(--muted);">@gdhanush27</a>
  </div>
</div>
</body></html>"""

# ---------------------------------------------------------------------------
# admin dashboard builder
# ---------------------------------------------------------------------------

ADMIN_CSS = """
.layout{min-height:100vh;display:flex;flex-direction:column;max-width:1200px;margin:0 auto;padding:0 28px;}
header{padding:26px 0 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;animation:fadeD .4s ease both;}
.logo{font-size:1.25rem;font-weight:800;letter-spacing:-.04em;}
.logo span{color:var(--accent);}
.logo .badge{font-family:var(--mono);font-size:.55rem;color:var(--muted);font-weight:400;letter-spacing:.07em;text-transform:uppercase;margin-left:8px;border:1px solid var(--border);border-radius:3px;padding:2px 6px;vertical-align:middle;}
.header-right{display:flex;gap:10px;align-items:center;}
.nav-link{font-family:var(--mono);font-size:.72rem;color:var(--muted);border:1px solid var(--border);border-radius:var(--r);padding:6px 12px;transition:color .15s,border-color .15s;}
.nav-link:hover{color:var(--text);border-color:var(--border2);text-decoration:none;}
.logout-btn{font-family:var(--mono);font-size:.72rem;color:var(--accent2);border:1px solid rgba(255,127,127,.3);border-radius:var(--r);padding:6px 12px;background:none;cursor:pointer;transition:background .15s;}
.logout-btn:hover{background:var(--accent2-dim);}
main{flex:1;padding:26px 0;animation:fadeU .4s ease .1s both;}

.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:28px;}
.stat-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:16px 20px;}
.stat-label{font-family:var(--mono);font-size:.63rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px;}
.stat-value{font-size:1.7rem;font-weight:800;letter-spacing:-.03em;}
.sv-green{color:var(--accent);}
.sv-red{color:var(--accent2);}
.sv-yellow{color:var(--warn);}
.sv-blue{color:var(--info);}

.toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px;}
.search-wrap{position:relative;flex:1;min-width:180px;}
.search-wrap input{width:100%;background:var(--surface);border:1px solid var(--border);border-radius:var(--r);color:var(--text);font-family:var(--mono);font-size:.8rem;padding:8px 12px 8px 34px;outline:none;transition:border-color .2s;}
.search-wrap input:focus{border-color:var(--border2);}
.search-wrap input::placeholder{color:var(--muted);}
.search-icon{position:absolute;left:11px;top:50%;transform:translateY(-50%);color:var(--muted);font-size:.8rem;pointer-events:none;}
select{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);color:var(--text);font-family:var(--mono);font-size:.78rem;padding:8px 10px;outline:none;cursor:pointer;transition:border-color .2s;}
select:focus{border-color:var(--border2);}
.result-count{font-family:var(--mono);font-size:.68rem;color:var(--muted);white-space:nowrap;margin-left:auto;}

.sel-controls{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;}
.sel-btn{font-family:var(--mono);font-size:.68rem;background:none;border:1px solid var(--border);border-radius:var(--r);color:var(--muted);padding:4px 10px;cursor:pointer;transition:color .15s,border-color .15s;}
.sel-btn:hover{color:var(--text);border-color:var(--border2);}

.bulk-bar{display:none;align-items:center;gap:10px;background:var(--surface2);border:1px solid var(--border2);border-radius:var(--r);padding:10px 14px;margin-bottom:12px;flex-wrap:wrap;}
.bulk-bar.visible{display:flex;animation:fadeIn .2s ease;}
.bulk-info{font-family:var(--mono);font-size:.78rem;color:var(--accent);flex:1;min-width:80px;}
.bulk-acts{display:flex;gap:8px;flex-wrap:wrap;}

.btn{font-family:var(--mono);font-size:.74rem;border-radius:var(--r);padding:7px 13px;cursor:pointer;border:1px solid;transition:background .15s,color .15s;white-space:nowrap;}
.btn-ghost{background:none;border-color:var(--border2);color:var(--muted);}
.btn-ghost:hover{color:var(--text);border-color:var(--border2);}
.btn-danger{background:none;border-color:rgba(255,127,127,.4);color:var(--accent2);}
.btn-danger:hover{background:var(--accent2-dim);}
.btn-warn{background:none;border-color:rgba(255,212,127,.4);color:var(--warn);}
.btn-warn:hover{background:var(--warn-dim);}
.btn-success{background:none;border-color:rgba(127,255,127,.4);color:var(--accent);}
.btn-success:hover{background:var(--accent-dim);}
.btn-info{background:none;border-color:rgba(127,207,255,.4);color:var(--info);}
.btn-info:hover{background:var(--info-dim);}

.table-wrap{border:1px solid var(--border);border-radius:var(--r);overflow:hidden;overflow-x:auto;}
table{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:.78rem;}
thead{background:var(--surface);}
th{padding:10px 14px;text-align:left;color:var(--muted);text-transform:uppercase;font-size:.63rem;letter-spacing:.08em;font-weight:500;border-bottom:1px solid var(--border);white-space:nowrap;}
th.sortable{cursor:pointer;user-select:none;transition:color .15s;}
th.sortable:hover{color:var(--text);}
th.sorted{color:var(--accent);}
td{padding:10px 14px;border-bottom:1px solid var(--border);vertical-align:middle;}
tr:last-child td{border-bottom:none;}
tr.is-blocked td{opacity:.45;}
tr:hover td{background:rgba(255,255,255,.02);}
tr.selected td{background:rgba(127,255,127,.04);}
tr.selected td:first-child{border-left:2px solid var(--accent);}

.cb{width:15px;height:15px;accent-color:var(--accent);cursor:pointer;}
.pid{color:var(--text);letter-spacing:.04em;}
.sz{color:var(--muted);}
.hits-bar{display:flex;align-items:center;gap:8px;}
.hits-val{min-width:36px;text-align:right;}
.hits-track{flex:1;height:4px;background:var(--border2);border-radius:2px;min-width:50px;max-width:90px;}
.hits-fill{height:100%;border-radius:2px;background:var(--accent);transition:width .3s;}
.bdg{display:inline-flex;align-items:center;gap:4px;font-family:var(--mono);font-size:.63rem;padding:3px 8px;border-radius:100px;border:1px solid;white-space:nowrap;}
.bdg-on{border-color:rgba(127,255,127,.3);color:var(--accent);background:var(--accent-dim);}
.bdg-off{border-color:rgba(255,127,127,.3);color:var(--accent2);background:var(--accent2-dim);}
.bdg-dot{width:5px;height:5px;border-radius:50%;background:currentColor;display:inline-block;}
.ts{color:var(--muted);white-space:nowrap;}
.acts{display:flex;gap:5px;flex-wrap:nowrap;}
.act{font-family:var(--mono);font-size:.67rem;padding:4px 9px;border-radius:var(--r);border:1px solid var(--border);background:none;color:var(--muted);cursor:pointer;white-space:nowrap;transition:color .15s,border-color .15s,background .15s;}
.act:hover{color:var(--text);border-color:var(--border2);}
.act.danger{border-color:rgba(255,127,127,.3);color:var(--accent2);}
.act.danger:hover{background:var(--accent2-dim);}
.act.warn{border-color:rgba(255,212,127,.3);color:var(--warn);}
.act.warn:hover{background:var(--warn-dim);}
.act.ok{border-color:rgba(127,255,127,.3);color:var(--accent);}
.act.ok:hover{background:var(--accent-dim);}
.act.info{border-color:rgba(127,207,255,.3);color:var(--info);}
.act.info:hover{background:var(--info-dim);}

.empty{padding:60px 24px;text-align:center;font-family:var(--mono);color:var(--muted);font-size:.82rem;line-height:1.8;}
.empty-icon{font-size:2.4rem;display:block;margin-bottom:12px;opacity:.4;}
.flash{border-radius:var(--r);padding:11px 15px;margin-bottom:18px;font-family:var(--mono);font-size:.78rem;}
.flash-ok{background:var(--accent-dim);border:1px solid rgba(127,255,127,.3);color:var(--accent);}
.flash-err{background:var(--accent2-dim);border:1px solid rgba(255,127,127,.3);color:var(--accent2);}

.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:100;align-items:center;justify-content:center;}
.modal-overlay.open{display:flex;animation:fadeIn .2s ease;}
.modal{background:var(--surface);border:1px solid var(--border2);border-radius:var(--r);padding:28px;max-width:420px;width:90%;animation:fadeU .25s ease;}
.modal h3{font-size:1rem;font-weight:700;margin-bottom:10px;}
.modal p{font-family:var(--mono);font-size:.78rem;color:var(--muted);line-height:1.6;margin-bottom:20px;}
.modal-acts{display:flex;gap:10px;justify-content:flex-end;}

.section-head{font-family:var(--mono);font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin:28px 0 10px;padding-bottom:8px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;}

footer{border-top:1px solid var(--border);padding:18px 0;font-family:var(--mono);font-size:.66rem;color:var(--muted);display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px;}
@media(max-width:900px){.stats{grid-template-columns:repeat(2,1fr);}th:nth-child(4),td:nth-child(4){display:none;}}
@media(max-width:600px){th:nth-child(5),td:nth-child(5){display:none;}}
"""

def build_admin_page(meta, flash_msg=None, flash_type="ok",
                     q="", status_filter="all", sort_by="created", sort_dir="desc"):

    # collect + filter
    pages = []
    for pid, info in meta.items():
        if not os.path.exists(os.path.join(PAGES_DIR, f"{pid}.html")):
            continue
        pages.append({**info, "id": pid})

    if q:
        pages = [p for p in pages if q.lower() in p["id"].lower()]
    if status_filter == "active":
        pages = [p for p in pages if not p.get("blocked")]
    elif status_filter == "blocked":
        pages = [p for p in pages if p.get("blocked")]

    rev = sort_dir == "desc"
    key_map = {
        "hits":    lambda p: p.get("hits", 0),
        "size":    lambda p: p.get("size", 0),
        "status":  lambda p: int(p.get("blocked", False)),
        "created": lambda p: p.get("created", ""),
    }
    pages.sort(key=key_map.get(sort_by, key_map["created"]), reverse=rev)

    total       = len(meta)
    total_hits  = sum(v.get("hits", 0) for v in meta.values())
    blocked_n   = sum(1 for v in meta.values() if v.get("blocked"))
    active_n    = total - blocked_n
    max_hits    = max((p.get("hits", 0) for p in pages), default=1) or 1

    # decks summary
    decks_meta = load_decks_meta()
    total_decks = len(decks_meta)

    def fmt_date(iso):
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return (iso or "—")[:16]

    def fmt_size(b):
        if b < 1024: return f"{b} B"
        if b < 1048576: return f"{b/1024:.1f} KB"
        return f"{b/1048576:.1f} MB"

    flash_html = ""
    if flash_msg:
        cls = "flash-ok" if flash_type == "ok" else "flash-err"
        flash_html = f'<div class="flash {cls}">{flash_msg}</div>'

    if not pages:
        empty_msg = ('No pages match your filters.' if (q or status_filter != "all")
                     else 'No pages yet. <a href="/">Share your first page &rarr;</a>')
        rows_html = f'<tr><td colspan="7"><div class="empty"><span class="empty-icon">&#128237;</span>{empty_msg}</div></td></tr>'
    else:
        rows = []
        for p in pages:
            pid     = p["id"]
            hits    = p.get("hits", 0)
            blocked = p.get("blocked", False)
            pct     = int(hits / max_hits * 100)
            badge   = (f'<span class="bdg bdg-off"><span class="bdg-dot"></span>blocked</span>'
                       if blocked else
                       f'<span class="bdg bdg-on"><span class="bdg-dot"></span>active</span>')
            block_btn = (
                f'<button class="act ok" onclick="doAction(\'unblock\',[&quot;{pid}&quot;])">unblock</button>'
                if blocked else
                f'<button class="act warn" onclick="doAction(\'block\',[&quot;{pid}&quot;])">block</button>'
            )
            rows.append(
                f'<tr id="row-{pid}" class="{"is-blocked" if blocked else ""}">'
                f'<td><input type="checkbox" class="cb row-cb" value="{pid}" onchange="updateBulk()"/></td>'
                f'<td><span class="pid">{pid}</span></td>'
                f'<td class="ts">{fmt_date(p.get("created",""))}</td>'
                f'<td class="sz">{fmt_size(p.get("size",0))}</td>'
                f'<td><div class="hits-bar"><span class="hits-val">{hits:,}</span>'
                f'<div class="hits-track"><div class="hits-fill" style="width:{pct}%"></div></div></div></td>'
                f'<td>{badge}</td>'
                f'<td class="acts">'
                f'<a class="act info" href="/p/{pid}" target="_blank">view</a>'
                f'<a class="act" href="/p/{pid}/source">source</a>'
                f'{block_btn}'
                f'<button class="act danger" onclick="confirmDelete([&quot;{pid}&quot;])">delete</button>'
                f'</td></tr>'
            )
        rows_html = "\n".join(rows)

    def th(label, key):
        active = ' sorted' if sort_by == key else ''
        nd = 'asc' if (sort_by == key and sort_dir == 'desc') else 'desc'
        arrow = (' &#8595;' if sort_dir == 'desc' else ' &#8593;') if sort_by == key else ''
        return (f'<th class="sortable{active}" onclick="sortBy(\'{key}\',\'{nd}\')">'
                f'{label}{arrow}</th>')

    state = (f'<input type="hidden" name="q" value="{q}"/>'
             f'<input type="hidden" name="status" value="{status_filter}"/>'
             f'<input type="hidden" name="sort_by" value="{sort_by}"/>'
             f'<input type="hidden" name="sort_dir" value="{sort_dir}"/>')

    sel_active = '' ; sel_blocked = '' ; sel_all = ''
    if status_filter == 'all':     sel_all = 'selected'
    elif status_filter == 'active':  sel_active = 'selected'
    elif status_filter == 'blocked': sel_blocked = 'selected'

    # decks summary stats
    total_deck_hits = sum(v.get("hits", 0) for v in decks_meta.values())
    blocked_decks   = sum(1 for v in decks_meta.values() if v.get("blocked"))
    active_decks    = total_decks - blocked_decks
    max_deck_hits   = max((v.get("hits", 0) for v in decks_meta.values()), default=1) or 1

    # decks rows
    if decks_meta:
        deck_rows = []
        for did, dinfo in sorted(decks_meta.items(),
                                  key=lambda x: x[1].get("created",""), reverse=True):
            deck_dir = os.path.join(DECKS_DIR, did)
            if not os.path.isdir(deck_dir):
                continue
            dtitle   = dinfo.get("title", "Untitled")
            dslides  = dinfo.get("slide_count", 0)
            dcreated = fmt_date(dinfo.get("created",""))
            dhits    = dinfo.get("hits", 0)
            dblocked = dinfo.get("blocked", False)
            dpct     = int(dhits / max_deck_hits * 100)
            dbadge   = (f'<span class="bdg bdg-off"><span class="bdg-dot"></span>blocked</span>'
                        if dblocked else
                        f'<span class="bdg bdg-on"><span class="bdg-dot"></span>active</span>')
            dblock_btn = (
                f'<button class="act ok" onclick="doDeckAction(\'unblock\',[\'{did}\'])">unblock</button>'
                if dblocked else
                f'<button class="act warn" onclick="doDeckAction(\'block\',[\'{did}\'])">block</button>'
            )
            deck_rows.append(
                f'<tr id="drow-{did}" class="{"is-blocked" if dblocked else ""}">'
                f'<td><input type="checkbox" class="cb deck-cb" value="{did}" onchange="updateDeckBulk()"/></td>'
                f'<td><span class="pid">{did}</span></td>'
                f'<td style="color:var(--text);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{dtitle}</td>'
                f'<td class="ts">{dcreated}</td>'
                f'<td style="color:var(--info)">{dslides}</td>'
                f'<td><div class="hits-bar"><span class="hits-val">{dhits:,}</span>'
                f'<div class="hits-track"><div class="hits-fill" style="width:{dpct}%"></div></div></div></td>'
                f'<td>{dbadge}</td>'
                f'<td class="acts">'
                f'<a class="act info" href="/d/{did}" target="_blank">view</a>'
                f'{dblock_btn}'
                f'<button class="act danger" onclick="confirmDeckDelete([\'{did}\'])">delete</button>'
                f'</td></tr>'
            )
        deck_rows_html = "\n".join(deck_rows)
    else:
        deck_rows_html = '<tr><td colspan="8"><div class="empty"><span class="empty-icon">&#9707;</span>No decks yet. <a href="/deck">Create your first deck &rarr;</a></div></td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Admin &#8212; htmldrop</title>
  <style>{COMMON_CSS}{ADMIN_CSS}</style>
</head>
<body>
<div class="layout">
  <header>
    <div class="logo">html<span>drop</span><span class="badge">admin</span></div>
    <div class="header-right">
      <a href="/" class="nav-link">&#8592; site</a>
      <a href="/deck" class="nav-link">&#9707; slides</a>
      <form method="POST" action="/admin/logout" style="display:inline">
        <button type="submit" class="logout-btn">logout</button>
      </form>
    </div>
  </header>

  <main>
    {flash_html}
    <div class="stats">
      <div class="stat-card"><div class="stat-label">total pages</div><div class="stat-value">{total:,}</div></div>
      <div class="stat-card"><div class="stat-label">total hits</div><div class="stat-value sv-blue">{total_hits:,}</div></div>
      <div class="stat-card"><div class="stat-label">active</div><div class="stat-value sv-green">{active_n}</div></div>
      <div class="stat-card"><div class="stat-label">decks</div><div class="stat-value sv-yellow">{total_decks}</div></div>
    </div>

    <div class="toolbar">
      <div class="search-wrap">
        <span class="search-icon">&#128269;</span>
        <input id="q-input" type="text" placeholder="search by id&#8230;" value="{q}" oninput="applyFilters()"/>
      </div>
      <select id="s-select" onchange="applyFilters()">
        <option value="all" {sel_all}>all pages</option>
        <option value="active" {sel_active}>active only</option>
        <option value="blocked" {sel_blocked}>blocked only</option>
      </select>
      <span class="result-count">{len(pages)} result{'s' if len(pages)!=1 else ''}</span>
    </div>

    <div class="sel-controls">
      <button class="sel-btn" onclick="selectAll()">select all</button>
      <button class="sel-btn" onclick="selectNone()">deselect all</button>
      <button class="sel-btn" onclick="invertSel()">invert selection</button>
    </div>

    <div class="bulk-bar" id="bulk-bar">
      <span class="bulk-info" id="bulk-info">0 selected</span>
      <div class="bulk-acts">
        <button class="btn btn-success" onclick="bulkAction('unblock')">&#8593; unblock</button>
        <button class="btn btn-warn" onclick="bulkAction('block')">&#8856; block</button>
        <button class="btn btn-danger" onclick="bulkAction('delete')">&#10005; delete</button>
        <button class="btn btn-ghost" onclick="selectNone()">cancel</button>
      </div>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th style="width:36px"><input type="checkbox" class="cb" id="cb-all" onchange="toggleAll(this)"/></th>
            <th>page id</th>
            {th("created", "created")}
            {th("size", "size")}
            {th("hits", "hits")}
            {th("status", "status")}
            <th>actions</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>

    <div class="section-head">
      <span>&#9707; slide decks ({total_decks}) &mdash; {active_decks} active, {blocked_decks} blocked, {total_deck_hits:,} total hits</span>
      <a href="/deck" style="font-size:.68rem;color:var(--accent);">+ new deck</a>
    </div>

    <div class="sel-controls">
      <button class="sel-btn" onclick="selectAllDecks()">select all decks</button>
      <button class="sel-btn" onclick="selectNoDecks()">deselect all</button>
    </div>

    <div class="bulk-bar" id="deck-bulk-bar">
      <span class="bulk-info" id="deck-bulk-info">0 selected</span>
      <div class="bulk-acts">
        <button class="btn btn-success" onclick="bulkDeckAction('unblock')">&#8593; unblock</button>
        <button class="btn btn-warn" onclick="bulkDeckAction('block')">&#8856; block</button>
        <button class="btn btn-danger" onclick="bulkDeckAction('delete')">&#10005; delete</button>
        <button class="btn btn-ghost" onclick="selectNoDecks()">cancel</button>
      </div>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th style="width:36px"><input type="checkbox" class="cb" id="dcb-all" onchange="toggleAllDecks(this)"/></th>
            <th>deck id</th>
            <th>title</th>
            <th>created</th>
            <th>slides</th>
            <th>hits</th>
            <th>status</th>
            <th>actions</th>
          </tr>
        </thead>
        <tbody>{deck_rows_html}</tbody>
      </table>
    </div>
  </main>

  <footer>
    <span>htmldrop admin &middot; <a href="https://github.com/gdhanush27/html-drop">github</a> &middot; <a href="https://github.com/gdhanush27">@gdhanush27</a></span>
    <span>managing {total} page{'s' if total!=1 else ''} &amp; {total_decks} deck{'s' if total_decks!=1 else ''}</span>
  </footer>
</div>

<form id="act-form" method="POST" action="/admin/action" style="display:none">
  {state}
  <input type="hidden" name="op" id="f-op"/>
  <input type="hidden" name="ids" id="f-ids"/>
</form>

<form id="deck-act-form" method="POST" action="/admin/deck/action" style="display:none">
  <input type="hidden" name="op" id="fd-op"/>
  <input type="hidden" name="ids" id="fd-ids"/>
</form>

<div class="modal-overlay" id="modal">
  <div class="modal">
    <h3 id="m-title">Confirm delete</h3>
    <p id="m-body">This will permanently remove the selected pages.</p>
    <div class="modal-acts">
      <button class="btn btn-ghost" onclick="closeModal()">cancel</button>
      <button class="btn btn-danger" onclick="submitAction()">delete</button>
    </div>
  </div>
</div>

<script>
var pendingOp='', pendingIds=[];

function getChecked(){{return [...document.querySelectorAll('.row-cb:checked')].map(c=>c.value);}}
function updateBulk(){{
  const sel=getChecked(), n=sel.length;
  const cbs=document.querySelectorAll('.row-cb');
  document.getElementById('bulk-bar').classList.toggle('visible',n>0);
  document.getElementById('bulk-info').textContent=n+' selected';
  const allCb=document.getElementById('cb-all');
  allCb.indeterminate=n>0&&n<cbs.length;
  allCb.checked=n===cbs.length&&cbs.length>0;
  cbs.forEach(cb=>{{
    const r=document.getElementById('row-'+cb.value);
    if(r)r.classList.toggle('selected',cb.checked);
  }});
}}
function toggleAll(cb){{document.querySelectorAll('.row-cb').forEach(c=>c.checked=cb.checked);updateBulk();}}
function selectAll(){{document.querySelectorAll('.row-cb').forEach(c=>c.checked=true);updateBulk();}}
function selectNone(){{document.querySelectorAll('.row-cb').forEach(c=>c.checked=false);updateBulk();}}
function invertSel(){{document.querySelectorAll('.row-cb').forEach(c=>c.checked=!c.checked);updateBulk();}}

function doAction(op,ids){{
  pendingOp=op; pendingIds=ids; pendingDeckOp=''; pendingDeckIds=[];
  if(op==='delete'){{showModal(ids);return;}}
  submit();
}}
function bulkAction(op){{
  const sel=getChecked();
  if(!sel.length)return;
  doAction(op,sel);
}}
function confirmDelete(ids){{pendingOp='delete';pendingIds=ids;pendingDeckOp='';pendingDeckIds=[];showModal(ids);}}
/* ----- deck bulk ops ----- */
var pendingDeckOp='', pendingDeckIds=[];

function getDeckChecked(){{return [...document.querySelectorAll('.deck-cb:checked')].map(c=>c.value);}}
function updateDeckBulk(){{
  const sel=getDeckChecked(), n=sel.length;
  const cbs=document.querySelectorAll('.deck-cb');
  document.getElementById('deck-bulk-bar').classList.toggle('visible',n>0);
  document.getElementById('deck-bulk-info').textContent=n+' selected';
  const allCb=document.getElementById('dcb-all');
  allCb.indeterminate=n>0&&n<cbs.length;
  allCb.checked=n===cbs.length&&cbs.length>0;
  cbs.forEach(cb=>{{
    const r=document.getElementById('drow-'+cb.value);
    if(r)r.classList.toggle('selected',cb.checked);
  }});
}}
function toggleAllDecks(cb){{document.querySelectorAll('.deck-cb').forEach(c=>c.checked=cb.checked);updateDeckBulk();}}
function selectAllDecks(){{document.querySelectorAll('.deck-cb').forEach(c=>c.checked=true);updateDeckBulk();}}
function selectNoDecks(){{document.querySelectorAll('.deck-cb').forEach(c=>c.checked=false);updateDeckBulk();}}

function doDeckAction(op,ids){{
  pendingDeckOp=op; pendingDeckIds=ids;
  if(op==='delete'){{confirmDeckDelete(ids);return;}}
  submitDeckAction();
}}
function bulkDeckAction(op){{
  const sel=getDeckChecked();
  if(!sel.length)return;
  doDeckAction(op,sel);
}}
function confirmDeckDelete(ids){{
  pendingDeckOp='delete'; pendingDeckIds=ids;
  var n=ids.length;
  document.getElementById('m-title').textContent='Delete '+(n===1?'this deck':n+' decks')+'?';
  document.getElementById('m-body').textContent='This will permanently remove '+(n===1?'this deck and all its slides':'these '+n+' decks and all their slides')+'. It cannot be undone.';
  document.getElementById('modal').classList.add('open');
}}
function submitDeckAction(){{
  document.getElementById('fd-op').value=pendingDeckOp;
  document.getElementById('fd-ids').value=pendingDeckIds.join(',');
  document.getElementById('deck-act-form').submit();
}}
function showModal(ids){{
  const n=ids.length;
  document.getElementById('m-title').textContent='Delete '+(n===1?'this page':n+' pages')+'?';
  document.getElementById('m-body').textContent='This will permanently remove '+(n===1?'this page':'these '+n+' pages')+'. It cannot be undone.';
  document.getElementById('modal').classList.add('open');
}}
function closeModal(){{document.getElementById('modal').classList.remove('open');pendingDeckOp='';pendingDeckIds=[];}}
function submitAction(){{
  var dOp=pendingDeckOp, dIds=pendingDeckIds.slice();
  closeModal();
  if(dOp && dIds.length){{
    document.getElementById('fd-op').value=dOp;
    document.getElementById('fd-ids').value=dIds.join(',');
    document.getElementById('deck-act-form').submit();
    return;
  }}
  submit();
}}
function submit(){{
  document.getElementById('f-op').value=pendingOp;
  document.getElementById('f-ids').value=pendingIds.join(',');
  document.getElementById('act-form').submit();
}}

function applyFilters(){{
  const url=new URL(window.location);
  url.searchParams.set('q',document.getElementById('q-input').value);
  url.searchParams.set('status',document.getElementById('s-select').value);
  url.searchParams.set('sort_by','{sort_by}');
  url.searchParams.set('sort_dir','{sort_dir}');
  window.location=url.toString();
}}
function sortBy(key,dir){{
  const url=new URL(window.location);
  url.searchParams.set('sort_by',key);
  url.searchParams.set('sort_dir',dir);
  window.location=url.toString();
}}
document.getElementById('modal').addEventListener('click',function(e){{if(e.target===this)closeModal();}});
</script>
</body></html>"""
    return html

# ---------------------------------------------------------------------------
# routes — pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_index()


@app.route("/share", methods=["POST"])
def share():
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
    upsert_meta(page_id, size=len(content.encode("utf-8")))
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


@app.route("/deck/create", methods=["POST"])
def deck_save():
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

    upsert_deck_meta(deck_id, title=title, slide_count=len(slides))
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
    viewer_html = build_deck_viewer(did, slides, title)
    return Response(viewer_html, mimetype="text/html")


# ---------------------------------------------------------------------------
# routes — admin
# ---------------------------------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password", "") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin"))
        err = '<div class="err">&#9888; incorrect password</div>'
        html = LOGIN_TMPL.replace("%%CSS%%", COMMON_CSS).replace("%%ERROR%%", err)
        return Response(html, mimetype="text/html")
    html = LOGIN_TMPL.replace("%%CSS%%", COMMON_CSS).replace("%%ERROR%%", "")
    return Response(html, mimetype="text/html")


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
@admin_required
def admin():
    q          = request.args.get("q", "")
    status     = request.args.get("status", "all")
    sort_by    = request.args.get("sort_by", "created")
    sort_dir   = request.args.get("sort_dir", "desc")
    flash_msg  = session.pop("flash", None)
    flash_type = session.pop("flash_type", "ok")
    html = build_admin_page(load_meta(),
                            flash_msg=flash_msg, flash_type=flash_type,
                            q=q, status_filter=status,
                            sort_by=sort_by, sort_dir=sort_dir)
    return Response(html, mimetype="text/html")


@app.route("/admin/action", methods=["POST"])
@admin_required
def admin_action():
    op       = request.form.get("op", "")
    raw      = request.form.get("ids", "")
    ids      = [i.strip() for i in raw.split(",")
                if re.match(r"^[a-zA-Z0-9]{1,20}$", i.strip())]
    q        = request.form.get("q", "")
    status   = request.form.get("status", "all")
    sort_by  = request.form.get("sort_by", "created")
    sort_dir = request.form.get("sort_dir", "desc")

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

    return redirect(url_for("admin", q=q, status=status,
                             sort_by=sort_by, sort_dir=sort_dir))


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

    return redirect(url_for("admin"))


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

# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    print(f"  Admin password : {ADMIN_PASSWORD}")
    print(f"  Set ADMIN_PASSWORD env var to change it.")
    print(f"  Pages stored in: {PAGES_DIR}")
    print(f"  Decks stored in: {DECKS_DIR}")
    app.run(debug="--debug" in sys.argv, port=5000)