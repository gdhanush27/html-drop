from flask import Response

from app.styles import COMMON_CSS


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
</div>
</body></html>"""
    return Response(html, status=code, mimetype="text/html")
