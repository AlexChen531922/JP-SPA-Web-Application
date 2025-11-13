from os import abort
from flask import session
from .models import UserAccount, UserInfo
from .extensions import database
from datetime import datetime

def check_for_user(username, password):
    cursor = database.connection.cursor()
    cursor.execute("""
        SELECT id, username, password_hash, email, firstName, surname, role
        FROM users
        WHERE username = %s AND password_hash = %s
    """, (username, password))
    row = cursor.fetchone()
    cursor.close()
    if row:
        user = UserAccount(row['username'], row['password_hash'], row['email'],
                           UserInfo(str(row['id']), row['firstName'], row['surname'],
                                    row['email'], row['role']))

        return user, row['role']
    return None, None


def check_username_exists(username):
    """Check if username already exists"""
    cursor = database.connection.cursor()
    cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
    row = cursor.fetchone()
    cursor.close()
    exists = row is not None
    return exists


def get_user_role(user_id):
    """Get user role"""
    cursor = database.connection.cursor()
    cursor.execute("SELECT role FROM users WHERE id = %s", (user_id,))
    row = cursor.fetchone()
    cursor.close()
    return row['role'] if row else None


def add_user(form):
    cursor = database.connection.cursor()
    try:
        user = cursor.execute("""
        INSERT INTO users (username, password_hash, email, firstName, surname, role)
        VALUES (%s, %s, %s, %s, %s, %s)
        """, (form.username.data, form.password.data, form.email.data,
              form.firstname.data, form.surname.data, form.role.data))
        
        # Fetch user_id for new user
        user_id = cursor.lastrowid

        # Auto add a new cart for a new user
        cursor.execute("""
            INSERT INTO carts (user_id,created_at)
            VALUES (%s,%s)
        """, (user_id,datetime.now()))

        database.connection.commit()
        cursor.close()
        return True
    except Exception as e:
        database.connection.rollback()
        cursor.close()
        raise e


def get_all_users():
    """Get all users (For admin view)"""
    cursor = database.connection.cursor()
    cursor.execute(
        """SELECT id, username, email, firstName, surname, role FROM users ORDER BY id DESC""")
    users = cursor.fetchall()
    cursor.close()
    return users


def get_current_user():
    return session.get('user')


def get_current_user_id():
    uid = session.get('user', {}).get('user_id')
    if not uid:
        abort(403)
    return uid


def get_current_user_role():
    user = get_current_user()
    if not user:
        return None
    return user['role']
