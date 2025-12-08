from flask import current_app, session
from . import database
import MySQLdb.cursors
from datetime import datetime, timedelta
import secrets
# ⭐ 修改：改用 werkzeug.security
from werkzeug.security import generate_password_hash, check_password_hash

# ... (SESSION HELPERS 保持不變) ...


def get_current_user_id():
    user = session.get('user')
    if user and isinstance(user, dict):
        return user.get('id') or user.get('user_id')
    return session.get('user_id')


def get_current_user_role():
    user = session.get('user')
    if user and isinstance(user, dict):
        return user.get('role')
    return None


def is_logged_in():
    return session.get('logged_in', False)


def get_current_user():
    return session.get('user')

# ... (get_user_details 保持不變) ...


def get_user_details(user_id):
    if not user_id:
        return None
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        cursor.execute("""
            SELECT id, username, email, firstname, surname, 
                   phone, line_id, address, role, 
                   gender, birth_date, occupation, source_id
            FROM users WHERE id = %s
        """, (user_id,))
        return cursor.fetchone()
    finally:
        cursor.close()

# ⭐ 修改：update_user_profile 使用 generate_password_hash


def update_user_profile(user_id, form_data):
    cursor = database.connection.cursor()
    try:
        # 1. Update basic info
        query = """
            UPDATE users
            SET firstname = %s, surname = %s, email = %s,
                phone = %s, line_id = %s, address = %s
            WHERE id = %s
        """
        params = (
            form_data.get('firstname'),
            form_data.get('surname'),
            form_data.get('email'),
            form_data.get('phone'),
            form_data.get('line_id'),
            form_data.get('address'),
            user_id
        )
        cursor.execute(query, params)

        # 2. Update password securely
        new_password = form_data.get('password')
        if new_password and len(new_password) >= 6:
            # ⭐ 安全加密
            password_hash = generate_password_hash(new_password)
            cursor.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s", (password_hash, user_id))

        database.connection.commit()
        return True
    except Exception as e:
        database.connection.rollback()
        print(f"Update profile error: {e}")
        return False
    finally:
        cursor.close()

# ⭐ 修改：check_for_user 使用 check_password_hash


def check_for_user(username, password_plaintext):
    """
    登入檢查 (使用安全 Hash 比對)
    Returns: (user_dict, role) or None
    """
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        # 先只撈出該使用者的 hash
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()

        if user and user['password_hash']:
            # ⭐ 比對明碼與資料庫的 Hash
            # 注意：這會兼容舊的 SHA256 (如果原本就是存 SHA256 格式可能需要重設密碼)
            # 但建議您所有用戶都重設一次密碼，或是寫一個腳本批次轉換
            try:
                if check_password_hash(user['password_hash'], password_plaintext):
                    return user, user['role']
            except ValueError:
                # 如果資料庫存的是舊的 SHA256，這裡做個臨時相容 (不建議長期保留)
                from hashlib import sha256
                old_hash = sha256(password_plaintext.encode()).hexdigest()
                if old_hash == user['password_hash']:
                    # 登入成功順便升級成新 Hash
                    new_hash = generate_password_hash(password_plaintext)
                    cursor.execute(
                        "UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, user['id']))
                    database.connection.commit()
                    return user, user['role']

        return None
    finally:
        cursor.close()

# ... (check_username_exists, check_email_exists, get_user_by_email 保持不變) ...


def check_username_exists(username):
    cursor = database.connection.cursor()
    cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
    exists = cursor.fetchone() is not None
    cursor.close()
    return exists


def check_email_exists(email):
    cursor = database.connection.cursor()
    cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
    exists = cursor.fetchone() is not None
    cursor.close()
    return exists


def get_user_by_email(email):
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()
    cursor.close()
    return user

# ⭐ 修改：add_user 使用 generate_password_hash


def add_user(form):
    """註冊新用戶"""
    cursor = database.connection.cursor()
    try:
        role = getattr(form, 'role', None)
        if hasattr(role, 'data'):
            role = role.data
        if not role:
            role = 'customer'

        # ⭐ 安全加密
        hashed_password = generate_password_hash(form.password.data)

        cursor.execute("""
            INSERT INTO users (username, email, password_hash, firstname, surname, role)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            form.username.data,
            form.email.data,
            hashed_password,  # 使用新 Hash
            form.firstname.data,
            form.surname.data,
            role
        ))
        database.connection.commit()
    finally:
        cursor.close()

# ... (create_reset_token, verify_reset_token 保持不變) ...


def create_reset_token(user_id):
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(hours=1)
    cursor = database.connection.cursor()
    cursor.execute("INSERT INTO password_resets (user_id, token, expires_at) VALUES (%s, %s, %s)",
                   (user_id, token, expires_at))
    database.connection.commit()
    cursor.close()
    return token


def verify_reset_token(token):
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        cursor.execute("""
            SELECT u.* FROM password_resets pr
            JOIN users u ON pr.user_id = u.id
            WHERE pr.token = %s AND pr.expires_at > NOW() AND pr.is_used = FALSE
        """, (token,))
        return cursor.fetchone()
    finally:
        cursor.close()

# ⭐ 修改：reset_password 使用 generate_password_hash


def reset_password(user_id, password_plaintext):
    """重設密碼"""
    cursor = database.connection.cursor()
    try:
        # ⭐ 安全加密
        new_hash = generate_password_hash(password_plaintext)

        cursor.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, user_id))
        cursor.execute(
            "UPDATE password_resets SET is_used = TRUE WHERE user_id = %s", (user_id,))
        database.connection.commit()
    finally:
        cursor.close()
