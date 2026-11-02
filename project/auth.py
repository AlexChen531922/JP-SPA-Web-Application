"""
Authentication Blueprint
Handles Login, Register, Logout, Password Reset, and LINE Login
"""
from flask import Blueprint, render_template, request, session, flash, redirect, url_for, current_app
from werkzeug.security import check_password_hash, generate_password_hash
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from urllib.parse import quote
import secrets
import requests
import re
import MySQLdb.cursors
import traceback
from project.extensions import database
from project.forms import LoginForm, RegisterForm, ForgotPasswordForm, ResetPasswordForm


auth_bp = Blueprint('auth', __name__)

# ==========================================
# 🛠️ 輔助函式
# ==========================================


def get_user_val(user, key):
    """Safely get value from user dict or object"""
    if user is None:
        return None
    if isinstance(user, dict):
        return user.get(key)
    return getattr(user, key, None)


def validate_password_strength(password):
    """驗證密碼強度"""
    if len(password) < 10:
        return False, "密碼長度需至少 10 個字元"
    if not re.search(r"[a-z]", password):
        return False, "密碼需包含至少一個小寫字母"
    if not re.search(r"[A-Z]", password):
        return False, "密碼需包含至少一個大寫字母"
    if not re.search(r"\d", password):
        return False, "密碼需包含至少一個數字"
    if not re.search(r"[ !@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?]", password):
        return False, "密碼需包含至少一個特殊符號"
    return True, ""

# ==========================================
# 🔐 登入與登出
# ==========================================


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Handle User Login"""
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data

        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        cursor.close()

        # 驗證帳號與密碼
        if user and check_password_hash(user['password_hash'], password):
            session.permanent = True
            session['logged_in'] = True
            session['user'] = user  # 存入完整 user 字典

            flash('登入成功！', 'success')

            # 根據角色導向
            if user['role'] in ['admin', 'staff']:
                return redirect(url_for('admin.dashboard'))
            else:
                return redirect(url_for('main.home'))
        else:
            flash('帳號或密碼錯誤', 'error')
            return redirect(url_for('main.home'))

    # 表單驗證失敗
    for field, errors in form.errors.items():
        for error in errors:
            flash(f'{error}', 'error')

    return redirect(url_for('main.home', open_login='true'))


@auth_bp.route('/logout')
def logout():
    """Handle User Logout"""
    username = session.get('user', {}).get('firstname') or '使用者'
    session.clear()
    flash(f'{username}，您已成功登出', 'info')
    return redirect(url_for('main.home'))

# ==========================================
# 📝 註冊 (整合 LINE 綁定)
# ==========================================


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    cursor = None

    if form.validate_on_submit():
        # ⭐ 將所有邏輯包進 try，確保錯誤能被捕捉並顯示
        try:
            username = form.username.data
            email = form.email.data
            password = form.password.data
            firstname = form.firstname.data
            surname = form.surname.data
            # Public registration may not grant staff/admin privileges even if form is tampered with.
            role = 'customer'
            line_id = session.get('binding_line_id') or form.line_id.data

            # 1. 驗證密碼強度
            is_valid, error_msg = validate_password_strength(password)
            if not is_valid:
                flash(error_msg, 'error')
                return redirect(url_for('main.home', open_register='true'))

            # 2. 檢查帳號是否重複
            cursor = database.connection.cursor()
            cursor.execute(
                "SELECT id FROM users WHERE username = %s OR email = %s", (username, email))
            account = cursor.fetchone()

            if account:
                flash('帳號或 Email 已被註冊', 'error')
                return redirect(url_for('main.home', open_register='true'))

            # 3. 建立新帳號
            hashed_password = generate_password_hash(password)

            sql = """
                INSERT INTO users
                (username, email, password_hash, firstname,
                 surname, phone, line_id, role, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """

            # 參數順序確認：
            # 1.username, 2.email, 3.hashed_pw, 4.firstname, 5.surname,
            # 6.phone(空值), 7.line_id, 8.role
            cursor.execute(sql, (username, email, hashed_password,
                                 firstname, surname, '', line_id, role))

            database.connection.commit()

            # ⭐ 4. 如果有使用到暫存的 LINE 資料，註冊成功後要清除 Session
            if session.get('binding_line_id'):
                session.pop('binding_line_id', None)
                session.pop('binding_line_name', None)
                flash('註冊成功！您的 LINE 帳號已自動連結。', 'success')
            else:
                flash('註冊成功！請登入。', 'success')

            return redirect(url_for('auth.login'))

        except Exception as e:
            # ... (rollback 與 print 錯誤保持不變) ...
            flash(f'註冊失敗 (系統錯誤): {str(e)}', 'error')
            # ⭕ 這裡也要改成導回首頁
            return redirect(url_for('main.home', open_register='true'))

        finally:
            if cursor:
                cursor.close()

    # 如果表單驗證失敗 (例如密碼不一致)
    if form.errors:
        for field, errors in form.errors.items():
            for error in errors:
                # 嘗試取得欄位名稱
                label = getattr(form, field).label.text if hasattr(
                    form, field) else field
                flash(f'{label}: {error}', 'error')

    # ❌ 最後這一行非常重要，絕對不能是 render_template
    return redirect(url_for('main.home', open_register='true'))

# ==========================================
# 🔑 忘記密碼 & 重設密碼
# ==========================================


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    form = ForgotPasswordForm(request.form)
    if request.method == 'POST' and form.validate():
        try:
            # ⭐ 關鍵修正：延遲引用
            from project.db import get_user_by_email
            from project.notifications import send_password_reset_email

            email = form.email.data
            user = get_user_by_email(email)
            if user:
                s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
                token = s.dumps(email, salt='password-reset-salt')
                send_password_reset_email(email, token)
                flash('重設密碼連結已發送。', 'success')
                return redirect(url_for('auth.login'))
            else:
                flash('如果 Email 存在，我們將發送重設連結。', 'info')
                return redirect(url_for('auth.login'))
        except Exception as e:
            flash(f'系統錯誤: {str(e)}', 'error')
            return redirect(url_for('auth.login'))
    return render_template('forgotpassword.html', form=form)


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """處理重設密碼連結"""
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])

    try:
        # 驗證 Token (15 分鐘有效)
        email = s.loads(token, salt='password-reset-salt', max_age=900)
    except SignatureExpired:
        flash('連結已過期，請重新申請。', 'error')
        return redirect(url_for('auth.forgot_password'))
    except BadSignature:
        flash('無效的連結。', 'error')
        return redirect(url_for('auth.forgot_password'))

    form = ResetPasswordForm(request.form)

    if request.method == 'POST' and form.validate():
        new_password = form.password.data

        # 驗證密碼強度
        is_valid, msg = validate_password_strength(new_password)
        if not is_valid:
            flash(msg, 'error')
            return render_template('reset_password.html', form=form, token=token)

        hashed_password = generate_password_hash(new_password)

        try:
            cursor = database.connection.cursor()
            cursor.execute("UPDATE users SET password_hash = %s WHERE email = %s",
                           (hashed_password, email))
            database.connection.commit()
            cursor.close()

            flash('密碼重設成功！請使用新密碼登入。', 'success')
            return redirect(url_for('main.home'))

        except Exception as e:
            database.connection.rollback()
            flash(f'重設失敗: {str(e)}', 'error')

    return render_template('reset_password.html', form=form, token=token)

# ==========================================
# 💬 LINE LOGIN
# ==========================================


@auth_bp.route('/line/login')
def line_login():
    """Redirect to LINE Login Page"""
    line_channel_id = current_app.config.get('LINE_CHANNEL_ID')
    if not line_channel_id:
        flash('系統未設定 LINE Channel ID', 'error')
        return redirect(url_for('auth.login'))

    # 產生隨機 state 防止 CSRF
    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state

    # 回呼網址 (移除 _scheme='https' 以兼容本機開發)
    callback_url = url_for('auth.line_callback', _external=True)

    scope = "profile openid email"

    authorization_url = (
        f"https://access.line.me/oauth2/v2.1/authorize?"
        f"response_type=code&"
        f"client_id={line_channel_id}&"
        f"redirect_uri={quote(callback_url)}&"
        f"state={state}&"
        f"scope={scope}"
    )

    return redirect(authorization_url)


@auth_bp.route('/line/callback')
def line_callback():
    """Handle LINE Login Callback"""
    # 1. 驗證 State
    if request.args.get('state') != session.get('oauth_state'):
        flash('登入驗證失敗 (State Mismatch)', 'error')
        return redirect(url_for('main.home'))  # 修正為 main.home

    code = request.args.get('code')
    if not code:
        flash('取消登入', 'warning')
        return redirect(url_for('main.home'))  # 修正為 main.home

    # 2. 換取 Access Token
    token_url = "https://api.line.me/oauth2/v2.1/token"
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': url_for('auth.line_callback', _external=True),
        'client_id': current_app.config.get('LINE_CHANNEL_ID'),
        'client_secret': current_app.config.get('LINE_CHANNEL_SECRET')
    }

    try:
        r = requests.post(token_url, headers=headers, data=payload)
        token_data = r.json()

        if 'error' in token_data:
            flash(f"LINE 登入錯誤: {token_data.get('error_description')}", 'error')
            return redirect(url_for('main.home'))  # 修正為 main.home

        access_token = token_data.get('access_token')

    except Exception as e:
        flash(f"連線錯誤: {str(e)}", 'error')
        return redirect(url_for('main.home'))  # 修正為 main.home

    # 3. 取得使用者個資 (Profile)
    profile_url = "https://api.line.me/v2/profile"
    headers = {'Authorization': f'Bearer {access_token}'}
    r_profile = requests.get(profile_url, headers=headers)
    profile_data = r_profile.json()

    line_user_id = profile_data.get('userId')
    display_name = profile_data.get('displayName')

    # 4. 資料庫比對
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        # === 邏輯 A：綁定模式 (使用者已登入，想連結 LINE) ===
        if session.get('is_binding_mode'):
            session.pop('is_binding_mode', None)

            current_user = session.get('user')
            if not current_user:
                return redirect(url_for('auth.login'))

            # 檢查此 LINE ID 是否已被其他人使用
            cursor.execute(
                "SELECT id FROM users WHERE line_id = %s", (line_user_id,))
            existing = cursor.fetchone()

            if existing and existing['id'] != current_user['id']:
                flash('此 LINE 帳號已被其他用戶綁定，無法重複使用。', 'error')
            else:
                # 執行綁定
                cursor.execute("UPDATE users SET line_id = %s WHERE id = %s",
                               (line_user_id, current_user['id']))
                database.connection.commit()

                # 更新 Session 中的使用者資料
                current_user['line_id'] = line_user_id
                session['user'] = current_user
                flash('LINE 帳號綁定成功！', 'success')

            # 依角色導向
            if current_user.get('role') in ['admin', 'staff']:
                return redirect(url_for('admin.dashboard'))
            else:
                return redirect(url_for('customer.dashboard'))

        # === 邏輯 B：登入模式 (使用者未登入，想用 LINE 登入) ===
        else:
            cursor.execute(
                "SELECT * FROM users WHERE line_id = %s", (line_user_id,))
            user = cursor.fetchone()

            if user:
                # 帳號存在 -> 直接登入
                session['logged_in'] = True
                session['user'] = user
                flash(f'歡迎回來，{user["firstname"]}！', 'success')

                if user['role'] in ['admin', 'staff']:
                    return redirect(url_for('admin.dashboard'))

                # 一般顧客導向首頁或會員中心
                return redirect(url_for('main.home'))  # 修正為 main.home
            else:
                # 帳號不存在 -> 引導去註冊 (並暫存 LINE 資料)
                session['binding_line_id'] = line_user_id
                session['binding_line_name'] = display_name
                flash('此 LINE 帳號尚未綁定，請完成註冊或登入現有帳號進行連結。', 'info')

                # 修正為 main.home，並帶參數開啟註冊視窗
                return redirect(url_for('main.home', open_register='true'))

    except Exception as e:
        if database.connection:
            database.connection.rollback()

        print(f"LINE Callback Error: {e}")
        flash(f'操作失敗: {str(e)}', 'error')

        # 錯誤發生時的導向
        role = session.get('user', {}).get('role')
        if role in ['admin', 'staff']:
            return redirect(url_for('admin.dashboard'))
        elif role == 'customer':
            return redirect(url_for('customer.dashboard'))
        else:
            return redirect(url_for('auth.login'))

    finally:
        if cursor:
            cursor.close()


@auth_bp.route('/connect/line')
def connect_line():
    """已登入用戶點擊此連結來綁定 LINE"""
    if 'user' not in session:
        flash('請先登入後再進行綁定', 'warning')
        return redirect(url_for('auth.login'))

    # 設定一個 session 標記，告訴 Callback 這次是來「綁定」不是「登入」
    session['is_binding_mode'] = True

    # 接著導向原本的 LINE 登入流程 (去取得 UID)
    return redirect(url_for('auth.line_login'))
