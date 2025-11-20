from flask import Blueprint, render_template, request, session, flash, redirect, url_for
from hashlib import sha256
from .forms import LoginForm, RegisterForm
from .db import (check_for_user, add_user, check_username_exists,
                 check_email_exists, get_user_by_email, create_reset_token,
                 verify_reset_token, reset_password, set_user_session, clear_user_session)
from .notifications import send_email

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['POST'])
def login():
    """Handle user login - SESSION BASED"""
    form = LoginForm()

    if form.validate_on_submit():
        password_hash = sha256(form.password.data.encode()).hexdigest()
        user, role = check_for_user(form.username.data, password_hash)

        if not user:
            flash('帳號或密碼錯誤', 'error')
            return redirect(url_for('main.home'))

        # Set session using helper function
        set_user_session(user, role)

        flash('登入成功！', 'success')

        # Redirect based on role
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
    """Handle user registration - SESSION BASED"""
    form = RegisterForm()

    if form.validate_on_submit():
        # Check if username exists
        if check_username_exists(form.username.data):
            flash('此帳號已被使用', 'error')
            return redirect(url_for('main.home'))

        # Check if email exists
        if check_email_exists(form.email.data):
            flash('此 Email 已被註冊', 'error')
            return redirect(url_for('main.home'))

        # Hash password
        form.password.data = sha256(form.password.data.encode()).hexdigest()

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
    """Handle user logout - SESSION BASED"""
    # Get username before clearing session
    username = session.get('user', {}).get('firstname', '使用者')

    # Clear session using helper function
    clear_user_session()

    flash(f'{username}，您已成功登出', 'info')
    return redirect(url_for('main.home'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Handle forgot password request"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip()

        if not email:
            flash('請輸入 Email', 'error')
            return redirect(url_for('auth.forgot_password'))

        user = get_user_by_email(email)

        if user:
            token = create_reset_token(user['id'])
            reset_link = url_for('auth.reset_password_form',
                                 token=token, _external=True)

            # Send email
            try:
                send_email(
                    to=email,
                    subject='晶品芳療 - 重設密碼',
                    body=f'''
您好 {user['firstname']}，

您已申請重設密碼，請點擊以下連結：
{reset_link}

此連結將在 1 小時後失效。

如果這不是您的操作，請忽略此郵件。

晶品芳療團隊
                    '''
                )
                flash('重設密碼連結已發送至您的 Email', 'success')
            except:
                flash('發送郵件失敗，請稍後再試', 'error')
        else:
            # Don't reveal if email exists
            flash('如果該 Email 存在，重設密碼連結將會發送', 'info')

        return redirect(url_for('main.home'))

    return render_template('forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password_form(token):
    """Handle password reset with token"""
    user = verify_reset_token(token)

    if not user:
        flash('重設密碼連結無效或已過期', 'error')
        return redirect(url_for('main.home'))

    if request.method == 'POST':
        password = request.form.get('password', '').strip()
        confirm = request.form.get('confirm_password', '').strip()

        if not password or len(password) < 6:
            flash('密碼至少需要 6 個字元', 'error')
            return redirect(url_for('auth.reset_password_form', token=token))

        if password != confirm:
            flash('密碼確認不符', 'error')
            return redirect(url_for('auth.reset_password_form', token=token))

        password_hash = sha256(password.encode()).hexdigest()
        reset_password(user['id'], password_hash)

        flash('密碼已成功重設，請登入', 'success')
        return redirect(url_for('main.home'))

    return render_template('reset_password.html', token=token)


@auth_bp.route('/check-session')
def check_session():
    """Debug route to check session (REMOVE IN PRODUCTION)"""
    from flask import jsonify
    from .db import is_logged_in, get_current_user_role, get_current_user

    return jsonify({
        'logged_in': is_logged_in(),
        'role': get_current_user_role(),
        'user': get_current_user(),
        'session': dict(session)
    })
