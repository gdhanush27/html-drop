import sys

from app import create_app
from app.config import ADMIN_PASSWORD, PAGES_DIR, DECKS_DIR

app = create_app()

if __name__ == "__main__":
    print(f"  Admin password : {ADMIN_PASSWORD}")
    print(f"  Set ADMIN_PASSWORD env var to change it.")
    print(f"  Pages stored in: {PAGES_DIR}")
    print(f"  Decks stored in: {DECKS_DIR}")
    app.run(debug="--debug" in sys.argv, port=5000)
