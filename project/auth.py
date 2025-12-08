from flask import Blueprint, render_template, request, session, flash, redirect, url_for
from .forms import LoginForm, RegisterForm
# 移除 sha256 import，因為已經不需要了
from .db import (check_for_user, add_user, check_username_exists,
                 check_email_exists, get_user_by_email, create_reset_token,
                 verify_reset_token, reset_password)
from .notifications import send_email
import re

auth_bp = Blueprint('auth', __name__)


def get_user_val(user, key):
    if user is None:
        return None
    if isinstance(user, dict):
        return user.get(key)
    return getattr(user, key, None)


def validate_password_strength(password):
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


@auth_bp.route('/login', methods=['POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        # ⭐ 修改：直接傳明碼進去，db.py 會負責比對 hash
        result = check_for_user(form.username.data, form.password.data)

        if not result:
            flash('帳號或密碼錯誤', 'error')
            return redirect(url_for('main.home'))

        try:
            user, role = result
        except TypeError:
            user = result
            role = get_user_val(user, 'role')

        if not user:
            flash('帳號或密碼錯誤', 'error')
            return redirect(url_for('main.home'))

        session.permanent = True
        session['logged_in'] = True
        session['user'] = {
            'id': get_user_val(user, 'id'),
            'user_id': get_user_val(user, 'id'),
            'username': get_user_val(user, 'username'),
            'role': role,
            'firstname': get_user_val(user, 'firstname'),
            'surname': get_user_val(user, 'surname'),
            'email': get_user_val(user, 'email')
        }
        flash('登入成功！', 'success')

        if role == 'admin' or role == 'staff':
            return redirect(url_for('admin.dashboard'))
        else:
            return redirect(url_for('main.home'))
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{error}', 'error')
    return redirect(url_for('main.home'))


@auth_bp.route('/register', methods=['POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        if check_username_exists(form.username.data):
            flash('此帳號已被使用', 'error')
            return redirect(url_for('main.home'))
        if check_email_exists(form.email.data):
            flash('此 Email 已被註冊', 'error')
            return redirect(url_for('main.home'))

        is_valid, msg = validate_password_strength(form.password.data)
        if not is_valid:
            flash(msg, 'error')
            return redirect(url_for('main.home'))

        # ⭐ 修改：不需要在此加密，直接傳 form 給 add_user，它會負責加密
        try:
            add_user(form)
            flash('註冊成功！請登入', 'success')
        except Exception as e:
            flash(f'註冊失敗：{str(e)}', 'error')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{error}', 'error')
    return redirect(url_for('main.home'))


@auth_bp.route('/logout')
def logout():
    username = session.get('user', {}).get('firstname') or '使用者'
    session.clear()
    flash(f'{username}，您已成功登出', 'info')
    return redirect(url_for('main.home'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        if not email:
            flash('請輸入 Email', 'error')
            return redirect(url_for('auth.forgot_password'))

        user = get_user_by_email(email)
        if user:
            user_id = get_user_val(user, 'id')
            user_firstname = get_user_val(user, 'firstname')
            token = create_reset_token(user_id)
            reset_link = url_for('auth.reset_password_form',
                                 token=token, _external=True)
            subject = '晶品芳療 - 重設密碼通知'
            html_body = f'''
            <html><body style="font-family: Arial, sans-serif;">
                <div style="padding: 20px; border: 1px solid #eee; border-radius: 8px;">
                    <h2 style="color: #2c5aa0;">重設密碼請求</h2>
                    <p>親愛的 {user_firstname}，請點擊下方按鈕以重設密碼：</p>
                    <a href="{reset_link}" style="background-color: #2c5aa0; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">重設密碼</a>
                </div>
            </body></html>
            '''
            try:
                send_email(to=email, subject=subject,
                           body=reset_link, html=html_body)
                flash('重設密碼連結已發送', 'success')
            except:
                flash('發送失敗', 'error')
        else:
            flash('如果該 Email 存在，連結將會發送', 'info')
        return redirect(url_for('main.home'))
    return render_template('forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password_form(token):
    user = verify_reset_token(token)
    if not user:
        flash('連結無效或已過期', 'error')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '').strip()
        confirm = request.form.get('confirm_password', '').strip()

        if password != confirm:
            flash('密碼不符', 'error')
            return redirect(url_for('auth.reset_password_form', token=token))

        is_valid, msg = validate_password_strength(password)
        if not is_valid:
            flash(msg, 'error')
            return redirect(url_for('auth.reset_password_form', token=token))

        # ⭐ 修改：傳明碼進去，由 reset_password 負責加密
        user_id = get_user_val(user, 'id')
        reset_password(user_id, password)

        flash('密碼已重設，請登入', 'success')
        return redirect(url_for('main.home'))

    return render_template('reset_password.html', token=token)
