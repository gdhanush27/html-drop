# htmldrop

Instant HTML sharing and slide deck hosting. Paste or upload self-contained HTML pages and get a shareable link - no accounts needed.

![Python](https://img.shields.io/badge/python-3.9+-blue)
![Flask](https://img.shields.io/badge/flask-3.x-green)
![License](https://img.shields.io/badge/license-MIT-yellow)

## Features

- **Paste or upload** any self-contained HTML and get a permanent shareable URL
- **Slide decks** - combine multiple HTML pages into a keyboard-navigable presentation with fullscreen support
- **Admin dashboard** - view stats, search, block/unblock, and bulk-delete pages and decks
- **Source remix** - append `/source` to any page URL to load it back into the editor
- **Zero dependencies** beyond Flask - no database, no build step, no accounts
- **Dark themed UI** with custom design system

## Quick Start

```bash
# Clone the repo
git clone https://github.com/gdhanush27/html-drop.git
cd html-drop

# Install Flask
pip install flask

# Run the app
python run.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

## Configuration

Set these environment variables to override defaults:

| Variable         | Default               | Description             |
| ---------------- | --------------------- | ----------------------- |
| `SECRET_KEY`     | `dev-secret-change-me`| Flask session secret    |
| `ADMIN_PASSWORD` | `password`            | Admin dashboard password|

```bash
# Example
export SECRET_KEY="your-production-secret"
export ADMIN_PASSWORD="a-strong-password"
python run.py
```

Pass `--debug` to enable Flask debug mode:

```bash
python run.py --debug
```

## Routes

| Route              | Description                        |
| ------------------ | ---------------------------------- |
| `/`                | Upload / paste HTML                |
| `/p/<id>`          | View a shared page                 |
| `/p/<id>/source`   | Remix - loads source back in editor|
| `/deck`            | Create a slide deck                |
| `/d/<id>`          | View a slide deck                  |
| `/admin`           | Admin dashboard (password-protected)|

## Project Structure

```
htmldrop/
├── run.py                  # Entry point
├── app/
│   ├── __init__.py         # App factory
│   ├── config.py           # Paths, env vars, constants
│   ├── meta.py             # JSON-file metadata for pages & decks
│   ├── auth.py             # Admin auth decorator
│   ├── styles.py           # Shared CSS variables
│   ├── errors.py           # Styled error pages
│   └── routes/
│       ├── __init__.py     # Blueprint registration
│       ├── pages.py        # Page upload, view, source remix
│       ├── decks.py        # Deck creation, viewer
│       └── admin.py        # Dashboard, bulk actions
├── pages/                  # Uploaded HTML pages (gitignored)
├── decks/                  # Slide deck folders (gitignored)
├── flask_app.py            # Legacy single-file version
└── .gitignore
```

## Storage

All data is stored on the local filesystem:

- **Pages** are saved as `pages/<id>.html`
- **Decks** are saved as `decks/<id>/` with a `manifest.json` and individual slide HTML files
- **Metadata** is kept in `meta.json` (pages) and `decks_meta.json` (decks)

No database required.

## License

[GNU GENERAL PUBLIC LICENSE](LICENSE)
