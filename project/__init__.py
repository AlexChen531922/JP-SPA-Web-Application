"""
Updated Application Initialization
Registers all blueprints including new reports system
"""

import os
from flask import Flask, render_template
from project.extensions import database, csrf, bootstrap

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")


def create_app():
    app = Flask(
        __name__,
        template_folder=TEMPLATE_DIR,
        static_folder=STATIC_DIR,
        static_url_path='/static'
    )

    app.config.update(
        SECRET_KEY=os.environ.get(
            "SECRET_KEY", "G5SECRETKEY-CHANGE-IN-PRODUCTION"),
        MYSQL_HOST=os.environ.get("MYSQL_HOST", "localhost"),
        MYSQL_USER=os.environ.get("MYSQL_USER", "root"),
        MYSQL_PASSWORD=os.environ.get("MYSQL_PASSWORD", "ifn582pw"),
        MYSQL_DB=os.environ.get("MYSQL_DB", "ecommerce_booking_system"),
        MYSQL_CURSORCLASS="DictCursor",
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        UPLOAD_FOLDER=os.path.join(STATIC_DIR, "img"),

        # Email configuration
        MAIL_SERVER=os.environ.get("MAIL_SERVER", "smtp.gmail.com"),
        MAIL_PORT=int(os.environ.get("MAIL_PORT", 587)),
        MAIL_USE_TLS=True,
        MAIL_USERNAME=os.environ.get("MAIL_USERNAME"),
        MAIL_PASSWORD=os.environ.get("MAIL_PASSWORD"),
        MAIL_DEFAULT_SENDER=os.environ.get(
            "MAIL_DEFAULT_SENDER", "noreply@jparomatic.com"),

        # LINE Notify Token
        LINE_NOTIFY_TOKEN=os.environ.get("LINE_NOTIFY_TOKEN"),
    )

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Initialize extensions
    database.init_app(app)
    csrf.init_app(app)
    bootstrap.init_app(app)

    # Context processors
    @app.context_processor
    def inject_common_data():
        from project.db import get_current_user_role, get_current_user_id

        try:
            cursor = database.connection.cursor()

            # Get product categories
            cursor.execute(
                "SELECT id, name FROM product_categories ORDER BY display_order, name"
            )
            product_categories = cursor.fetchall()

            # Get course categories
            cursor.execute(
                "SELECT id, name FROM course_categories ORDER BY display_order, name"
            )
            course_categories = cursor.fetchall()

            cursor.close()

            return dict(
                product_categories=product_categories,
                course_categories=course_categories,
                current_user_role=get_current_user_role(),
                current_user_id=get_current_user_id() if get_current_user_role() else None
            )
        except:
            return dict(
                product_categories=[],
                course_categories=[],
                current_user_role=None,
                current_user_id=None
            )

    # Error handlers
    @app.errorhandler(404)
    def handle_404(e):
        return render_template("error.html", code=404, message="找不到頁面"), 404

    @app.errorhandler(500)
    def handle_500(e):
        return render_template("error.html", code=500, message="伺服器錯誤,請稍後再試"), 500

    @app.errorhandler(403)
    def handle_403(e):
        return render_template("error.html", code=403, message="您沒有權限訪問此頁面"), 403

    # Register blueprints
    from project.views import main_bp
    app.register_blueprint(main_bp)

    from project.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from project.admin import admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')

    from project.customer import customer_bp
    app.register_blueprint(customer_bp, url_prefix='/customer')

    # ⭐ Register new reports blueprint
    from project.advanced_reports import reports_bp
    app.register_blueprint(reports_bp)

    return app
