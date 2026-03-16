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
