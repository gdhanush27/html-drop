import os
import re
import uuid

from flask import Blueprint, request, Response, send_from_directory

from app.config import PAGES_DIR
from app.styles import COMMON_CSS
from app.meta import get_page_meta, upsert_meta, inc_hits
from app.errors import error_page

pages_bp = Blueprint("pages_bp", __name__)

# ---------------------------------------------------------------------------
# index template
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
  <footer><span>htmldrop</span><span>pages stored locally &#183; no accounts needed</span></footer>
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
    error_html = f'<div class="error">&#9888; {error}</div>' if error else ""
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
# routes
# ---------------------------------------------------------------------------

@pages_bp.route("/")
def index():
    return render_index()


@pages_bp.route("/share", methods=["POST"])
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


@pages_bp.route("/p/<page_id>")
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


@pages_bp.route("/p/<page_id>/source")
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
