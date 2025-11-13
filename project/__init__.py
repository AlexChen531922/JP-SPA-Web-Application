import os
from flask import Flask, render_template

from project.db import get_current_user_role
from .extensions import database, csrf, bootstrap


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")


def _fetch_categories():
    cursor = database.connection.cursor()
    cursor.execute("SELECT * FROM categories ORDER BY name")
    categories = [row['name'] for row in cursor.fetchall()]
    return categories


def create_app():
    app = Flask(
        __name__,
        template_folder=TEMPLATE_DIR,
        static_folder=STATIC_DIR,
    )

    app.config.update(
        SECRET_KEY="G5SECRETKEY",
        MYSQL_HOST="localhost",
        MYSQL_USER="root",
        MYSQL_PASSWORD="ifn582pw",
        MYSQL_DB="ifn582",
        MYSQL_CURSORCLASS="DictCursor",
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        UPLOAD_FOLDER=os.path.join(STATIC_DIR, "img"),
    )

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    database.init_app(app)
    csrf.init_app(app)
    bootstrap.init_app(app)

    @app.context_processor
    def inject_categories():
        return dict(categories=_fetch_categories())

    @app.context_processor
    def inject_user_role():
        return dict(current_user_role=get_current_user_role())

    @app.errorhandler(404)
    def handle_404(e):
        return render_template("error.html", code=404, message=e.description or "Page not found"), 404

    @app.errorhandler(500)
    def handle_500(e):
        return render_template("error.html", code=500, message="Internal server error"), 500

    from .views import bp as main_bp
    app.register_blueprint(main_bp)
    from .vendor import bp as vendor_bp
    app.register_blueprint(vendor_bp, url_prefix="/vendor")

    return app
