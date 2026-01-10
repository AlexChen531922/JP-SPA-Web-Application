"""
Updated Application Initialization
Registers all blueprints including new reports system
"""

import os
from flask import Flask, render_template, session
from werkzeug.middleware.proxy_fix import ProxyFix
from project.extensions import database, csrf, bootstrap, mail
from dotenv import load_dotenv
from datetime import timedelta
from flask_wtf.csrf import CSRFError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_FOLDER = os.path.join(STATIC_DIR, "img")

# 依照 Railway 的環境變數判斷是否為生產環境
is_production = os.environ.get('FLASK_ENV') == 'production'

load_dotenv()


def create_app():
    app = Flask(
        __name__,
        template_folder=TEMPLATE_DIR,
        static_folder=STATIC_DIR,
        static_url_path='/static'
    )

    # ⭐ 確保上傳目錄存在
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-key"),

        # 設定 UPLOAD_FOLDER
        UPLOAD_FOLDER=UPLOAD_FOLDER,

        # Cloudinary Configuration
        cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
        api_key=os.environ.get('CLOUDINARY_API_KEY'),
        api_secret=os.environ.get('CLOUDINARY_API_SECRET'),

        MYSQL_HOST=os.environ.get("MYSQL_HOST", "localhost"),
        MYSQL_USER=os.environ.get("MYSQL_USER", "root"),
        MYSQL_PASSWORD=os.environ.get("MYSQL_PASSWORD"),
        MYSQL_DB=os.environ.get("MYSQL_DB", "ecommerce_booking_system"),
        MYSQL_CURSORCLASS="DictCursor",

        # 時區台灣時間
        MYSQL_INIT_COMMAND="SET time_zone = '+08:00'",

        # Email configuration
        MAIL_SERVER="smtp.gmail.com",
        MAIL_PORT=587,
        MAIL_USE_TLS=True,
        MAIL_USERNAME=os.environ.get("MAIL_USERNAME"),
        MAIL_PASSWORD=os.environ.get("MAIL_PASSWORD"),
        MAIL_DEFAULT_SENDER=("晶品芳療", os.environ.get("MAIL_USERNAME")),

        # LINE Configuration
        LINE_CHANNEL_ID=os.environ.get("LINE_CHANNEL_ID"),
        LINE_CHANNEL_SECRET=os.environ.get("LINE_CHANNEL_SECRET"),
        LINE_BOT_CHANNEL_SECRET=os.environ.get("LINE_BOT_CHANNEL_SECRET"),
        LINE_CHANNEL_ACCESS_TOKEN=os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"),
        LINE_ADMIN_USER_ID=os.environ.get("LINE_ADMIN_USER_ID"),
        LINE_ADMIN_GROUP_ID=os.environ.get("LINE_ADMIN_GROUP_ID"),

        # Session Security
        # 1. 改名 v3：讓舊的 v2 或預設 session 餅乾全部作廢，解決登入鬼打牆
        SESSION_COOKIE_NAME='jparomatic_session_v2',

        # 2. 閒置超時：120 分鐘後伺服器拒絕該餅乾
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=120),

        # 3. 安全設定：依賴您的 Railway 環境變數
        SESSION_COOKIE_SECURE=is_production,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
    )

    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
    )

    # Initialize extensions
    database.init_app(app)
    csrf.init_app(app)
    bootstrap.init_app(app)
    mail.init_app(app)

    # Context processors
    @app.context_processor
    def inject_common_data():
        from project.db import get_current_user_role, get_current_user_id

        try:
            cursor = database.connection.cursor()
            cursor.execute(
                "SELECT id, name FROM product_categories ORDER BY display_order, name")
            product_categories = cursor.fetchall()

            cursor.execute(
                "SELECT id, name FROM course_categories ORDER BY display_order, name")
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

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        return render_template("error.html", code=400, message="頁面停留過久導致驗證過期，請重新整理或重新登入"), 400

    # ⭐ 重點新增：強制設定 Session 為非永久 (瀏覽器關閉即消失)
    @app.before_request
    def make_session_temporary():
        session.permanent = False

    # Register blueprints (您原本這段在 return 之後，那是錯的，一定要移上來)
    from project.views import main_bp
    app.register_blueprint(main_bp)

    from project.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from project.admin import admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')

    from project.customer import customer_bp
    app.register_blueprint(customer_bp, url_prefix='/customer')

    from project.advanced_reports import reports_bp
    app.register_blueprint(reports_bp)

    from project.webhook import webhook_bp
    app.register_blueprint(webhook_bp)

    return app
