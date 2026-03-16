import os
import re
from datetime import datetime

from flask import Blueprint, request, redirect, url_for, Response, session

from app.config import ADMIN_PASSWORD, PAGES_DIR, DECKS_DIR
from app.styles import COMMON_CSS
from app.auth import admin_required
from app.meta import (
    load_meta, save_meta, delete_page,
    load_decks_meta, save_decks_meta, delete_deck,
)

admin_bp = Blueprint("admin_bp", __name__)

# ---------------------------------------------------------------------------
# login template
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
</div>
</body></html>"""

# ---------------------------------------------------------------------------
# admin CSS
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


# ---------------------------------------------------------------------------
# admin page builder
# ---------------------------------------------------------------------------

def _fmt_date(iso):
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return (iso or "\u2014")[:16]


def _fmt_size(b):
    if b < 1024:
        return f"{b} B"
    if b < 1048576:
        return f"{b/1024:.1f} KB"
    return f"{b/1048576:.1f} MB"


def build_admin_page(meta, flash_msg=None, flash_type="ok",
                     q="", status_filter="all", sort_by="created", sort_dir="desc"):

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

    total      = len(meta)
    total_hits = sum(v.get("hits", 0) for v in meta.values())
    blocked_n  = sum(1 for v in meta.values() if v.get("blocked"))
    active_n   = total - blocked_n
    max_hits   = max((p.get("hits", 0) for p in pages), default=1) or 1

    decks_meta  = load_decks_meta()
    total_decks = len(decks_meta)

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
                f'<td class="ts">{_fmt_date(p.get("created",""))}</td>'
                f'<td class="sz">{_fmt_size(p.get("size",0))}</td>'
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
    if status_filter == 'all':       sel_all = 'selected'
    elif status_filter == 'active':  sel_active = 'selected'
    elif status_filter == 'blocked': sel_blocked = 'selected'

    total_deck_hits = sum(v.get("hits", 0) for v in decks_meta.values())
    blocked_decks   = sum(1 for v in decks_meta.values() if v.get("blocked"))
    active_decks    = total_decks - blocked_decks
    max_deck_hits   = max((v.get("hits", 0) for v in decks_meta.values()), default=1) or 1

    if decks_meta:
        deck_rows = []
        for did, dinfo in sorted(decks_meta.items(),
                                  key=lambda x: x[1].get("created",""), reverse=True):
            deck_dir = os.path.join(DECKS_DIR, did)
            if not os.path.isdir(deck_dir):
                continue
            dtitle   = dinfo.get("title", "Untitled")
            dslides  = dinfo.get("slide_count", 0)
            dcreated = _fmt_date(dinfo.get("created",""))
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
    <span>htmldrop admin</span>
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
# routes
# ---------------------------------------------------------------------------

@admin_bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password", "") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin_bp.admin"))
        err = '<div class="err">&#9888; incorrect password</div>'
        html = LOGIN_TMPL.replace("%%CSS%%", COMMON_CSS).replace("%%ERROR%%", err)
        return Response(html, mimetype="text/html")
    html = LOGIN_TMPL.replace("%%CSS%%", COMMON_CSS).replace("%%ERROR%%", "")
    return Response(html, mimetype="text/html")


@admin_bp.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_bp.admin_login"))


@admin_bp.route("/admin")
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


@admin_bp.route("/admin/action", methods=["POST"])
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

    return redirect(url_for("admin_bp.admin", q=q, status=status,
                             sort_by=sort_by, sort_dir=sort_dir))


@admin_bp.route("/admin/deck/action", methods=["POST"])
@admin_required
def admin_deck_action():
    op  = request.form.get("op", "")
    raw = request.form.get("ids", "")
    ids = [i.strip() for i in raw.split(",")
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

    return redirect(url_for("admin_bp.admin"))
