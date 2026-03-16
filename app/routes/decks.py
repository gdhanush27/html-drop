import os
import re
import uuid
import json

from flask import Blueprint, request, Response

from app.config import DECKS_DIR
from app.styles import COMMON_CSS
from app.meta import get_deck_meta, upsert_deck_meta, inc_deck_hits
from app.errors import error_page

decks_bp = Blueprint("decks_bp", __name__)

# ---------------------------------------------------------------------------
# deck creation page CSS
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

# ---------------------------------------------------------------------------
# deck creation page template
# ---------------------------------------------------------------------------

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
  <footer><span>htmldrop slides</span><span>keyboard-navigable html decks · no accounts needed</span></footer>
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
    error_html = f'<div class="error">&#9888; {error}</div>' if error else ""
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
# deck viewer builder
# ---------------------------------------------------------------------------

def build_deck_viewer(deck_id, slides, title):
    """Build a self-contained full-screen slide viewer."""
    slides_json = json.dumps([{"title": s["title"], "html": s["html"]} for s in slides])
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
  <button class="nav-btn" id="btn-prev" onclick="prev()" title="Previous (\u2190 or Backspace)">&#8592; prev</button>
  <div id="dot-nav"></div>
  <button class="nav-btn" id="btn-next" onclick="next()" title="Next (\u2192 or Space)">next &#8594;</button>
</div>

<div id="toast"></div>

<div id="hotkeys-panel">
  <div class="hk-box">
    <h3>keyboard shortcuts</h3>
    <div class="hk-row"><span>next slide</span><span><span class="hk-key">\u2192</span> &nbsp;<span class="hk-key">Space</span></span></div>
    <div class="hk-row"><span>previous slide</span><span><span class="hk-key">\u2190</span> &nbsp;<span class="hk-key">Backspace</span></span></div>
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
    var fr = document.createElement('iframe');
    fr.className = 'slide-frame' + (i === 0 ? '' : ' hidden');
    fr.setAttribute('sandbox', 'allow-scripts allow-same-origin');
    fr.setAttribute('title', slide.title || ('Slide ' + (i+1)));
    stage.appendChild(fr);
    frames.push(fr);

    fr.srcdoc = slide.html;

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
# routes
# ---------------------------------------------------------------------------

@decks_bp.route("/deck")
def deck_create():
    return render_deck_page()


@decks_bp.route("/deck/create", methods=["POST"])
def deck_save():
    title = request.form.get("title", "").strip() or "Untitled Deck"
    slides = []

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
        html_list = request.form.getlist("slide_html[]")
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

    upsert_deck_meta(deck_id, title=title, slide_count=len(slides))
    return render_deck_page(deck_id=deck_id, host=request.host_url)


@decks_bp.route("/d/<deck_id>")
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
                    "html": fh.read()
                })

    if not slides:
        return error_page(404, "Deck is empty",
                          "This deck has no slides.",
                          f"id: {did}")

    title = manifest.get("title", "Untitled Deck")
    viewer_html = build_deck_viewer(did, slides, title)
    return Response(viewer_html, mimetype="text/html")
