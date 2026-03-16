from flask import Flask, request, Response

from app.config import SECRET_KEY, MAX_CONTENT_LENGTH
from app.errors import error_page
from app.routes import register_blueprints


def create_app():
    app = Flask(__name__)
    app.secret_key = SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

    register_blueprints(app)

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

    return app
