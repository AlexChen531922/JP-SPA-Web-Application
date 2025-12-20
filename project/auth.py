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
    if form.validate_on_submit():
        username = form.username.data
        email = form.email.data
        password = form.password.data
        firstname = form.firstname.data
        surname = form.surname.data
        line_id = form.line_id.data
        role = form.role.data

        # 1. 驗證密碼強度
        is_valid, error_msg = validate_password_strength(password)
        if not is_valid:
            flash(error_msg, 'error')
            return render_template('register.html', form=form)

        # 2. 檢查帳號是否重複
        cursor = database.connection.cursor()
        cursor.execute(
            "SELECT id FROM users WHERE username = %s OR email = %s", (username, email))
        account = cursor.fetchone()

        if account:
            flash('帳號或 Email 已被註冊', 'error')
            cursor.close()
            return render_template('register.html', form=form)

        # 3. 建立新帳號 (修正 SQL 欄位名稱)
        # ⭐ 修正：資料庫欄位是 password_hash，不是 password
        hashed_password = generate_password_hash(password)

        try:
            sql = """
                INSERT INTO users 
                (username, email, password_hash, firstname, surname, phone, line_id, role, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """
            cursor.execute(sql, (username, email, hashed_password,
                           firstname, surname, line_id, role))
            database.connection.commit()

            flash('註冊成功！請登入。', 'success')
            return redirect(url_for('auth.login'))

        except Exception as e:
            database.connection.rollback()
            # 發生錯誤時印出 Log 以便除錯
            print(f"Register Error: {e}")
            flash(f'註冊失敗，請稍後再試: {str(e)}', 'error')

        finally:
            cursor.close()

    return render_template('register.html', form=form)

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
        return redirect(url_for('main.home'))

    code = request.args.get('code')
    if not code:
        flash('取消登入', 'warning')
        return redirect(url_for('main.home'))

    # 2. 換取 Access Token
    token_url = "https://api.line.me/oauth2/v2.1/token"
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    payload = {
        'grant_type': 'authorization_code',
        'code': code,
        # 這裡也要移除 https
        'redirect_uri': url_for('auth.line_callback', _external=True),
        'client_id': current_app.config.get('LINE_CHANNEL_ID'),
        'client_secret': current_app.config.get('LINE_CHANNEL_SECRET')
    }

    try:
        r = requests.post(token_url, headers=headers, data=payload)
        token_data = r.json()

        if 'error' in token_data:
            flash(f"LINE 登入錯誤: {token_data.get('error_description')}", 'error')
            return redirect(url_for('main.home'))

        access_token = token_data.get('access_token')
        # id_token = token_data.get('id_token')

    except Exception as e:
        flash(f"連線錯誤: {str(e)}", 'error')
        return redirect(url_for('main.home'))

    # 3. 取得使用者個資 (Profile)
    profile_url = "https://api.line.me/v2/profile"
    headers = {'Authorization': f'Bearer {access_token}'}
    r_profile = requests.get(profile_url, headers=headers)
    profile_data = r_profile.json()

    line_user_id = profile_data.get('userId')
    display_name = profile_data.get('displayName')

    # 4. 資料庫比對
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM users WHERE line_id = %s", (line_user_id,))
    user = cursor.fetchone()
    cursor.close()

    if user:
        # A. 找到人 -> 登入
        session['logged_in'] = True
        session['user'] = user
        flash(f'歡迎回來，{user["firstname"]}！', 'success')

        if user['role'] in ['admin', 'staff']:
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('main.home'))

    else:
        # B. 沒找到 -> 導向註冊頁面進行綁定
        session['binding_line_id'] = line_user_id
        session['binding_line_name'] = display_name

        flash('請完成註冊以綁定 LINE 帳號', 'info')
        # 導回首頁並打開註冊視窗 (需搭配 base.html 的 JS)
        return redirect(url_for('main.home', open_register='true'))
