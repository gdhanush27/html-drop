from app.routes.pages import pages_bp
from app.routes.decks import decks_bp
from app.routes.admin import admin_bp


def register_blueprints(app):
    app.register_blueprint(pages_bp)
    app.register_blueprint(decks_bp)
    app.register_blueprint(admin_bp)
