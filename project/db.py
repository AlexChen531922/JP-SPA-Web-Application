from flask import session, abort
from .extensions import database
from .models import UserAccount, UserInfo
from datetime import datetime
import secrets


def check_for_user(username, password):
    """Check if user exists with given credentials"""
    cursor = database.connection.cursor()
    cursor.execute("""
        SELECT id, username, password_hash, email, firstname, surname, role
        FROM users
        WHERE username = %s AND password_hash = %s
    """, (username, password))
    row = cursor.fetchone()
    cursor.close()

    if row:
        user = UserAccount(
            username=row['username'],
            password=row['password_hash'],
            email=row['email'],
            info=UserInfo(
                id=str(row['id']),
                firstname=row['firstname'],
                surname=row['surname'],
                email=row['email'],
                role=row['role']
            )
        )
        return user, row['role']
    return None, None


def check_username_exists(username):
    """Check if username already exists"""
    cursor = database.connection.cursor()
    cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
    row = cursor.fetchone()
    cursor.close()
    return row is not None


def check_email_exists(email):
    """Check if email already exists"""
    cursor = database.connection.cursor()
    cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
    row = cursor.fetchone()
    cursor.close()
    return row is not None


def add_user(form):
    """Add new user to database"""
    cursor = database.connection.cursor()
    try:
        cursor.execute("""
            INSERT INTO users (username, password_hash, email, firstname, surname, role)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            form.username.data,
            form.password.data,
            form.email.data,
            form.firstname.data,
            form.surname.data,
            form.role.data if hasattr(form, 'role') else 'customer'
        ))

        user_id = cursor.lastrowid

        # Auto-create cart for customer
        if not hasattr(form, 'role') or form.role.data == 'customer':
            cursor.execute("""
                INSERT INTO carts (customer_id, created_at)
                VALUES (%s, %s)
            """, (user_id, datetime.now()))

        database.connection.commit()
        cursor.close()
        return True
    except Exception as e:
        database.connection.rollback()
        cursor.close()
        raise e


def get_user_by_email(email):
    """Get user by email"""
    cursor = database.connection.cursor()
    cursor.execute("""
        SELECT id, username, email, firstname, surname, role
        FROM users WHERE email = %s
    """, (email,))
    row = cursor.fetchone()
    cursor.close()
    return row


def create_reset_token(user_id):
    """Create password reset token"""
    token = secrets.token_urlsafe(32)
    expiry = datetime.now() + datetime.timedelta(hours=1)

    cursor = database.connection.cursor()
    cursor.execute("""
        UPDATE users 
        SET reset_token = %s, reset_token_expiry = %s
        WHERE id = %s
    """, (token, expiry, user_id))
    database.connection.commit()
    cursor.close()

    return token


def verify_reset_token(token):
    """Verify password reset token"""
    cursor = database.connection.cursor()
    cursor.execute("""
        SELECT id, email FROM users
        WHERE reset_token = %s AND reset_token_expiry > NOW()
    """, (token,))
    row = cursor.fetchone()
    cursor.close()
    return row


def reset_password(user_id, new_password_hash):
    """Reset user password"""
    cursor = database.connection.cursor()
    cursor.execute("""
        UPDATE users
        SET password_hash = %s, reset_token = NULL, reset_token_expiry = NULL
        WHERE id = %s
    """, (new_password_hash, user_id))
    database.connection.commit()
    cursor.close()


def get_all_users():
    """Get all users (for admin view)"""
    cursor = database.connection.cursor()
    cursor.execute("""
        SELECT id, username, email, firstname, surname, role, created_at
        FROM users 
        ORDER BY created_at DESC
    """)
    users = cursor.fetchall()
    cursor.close()
    return users


def get_user_role(user_id):
    """Get user role"""
    cursor = database.connection.cursor()
    cursor.execute("SELECT role FROM users WHERE id = %s", (user_id,))
    row = cursor.fetchone()
    cursor.close()
    return row['role'] if row else None


# ==========================================
# SESSION-BASED AUTHORIZATION FUNCTIONS
# ==========================================

def get_current_user():
    """Get current logged-in user from session"""
    return session.get('user')


def get_current_user_id():
    """Get current user ID, returns None if not logged in"""
    user = session.get('user')
    if not user:
        return None
    return user.get('user_id')


def get_current_user_role():
    """Get current user role"""
    user = get_current_user()
    if not user:
        return None
    return user.get('role')


def is_logged_in():
    """Check if user is logged in"""
    return session.get('logged_in', False) and 'user' in session


def is_admin():
    """Check if current user is admin"""
    return is_logged_in() and get_current_user_role() == 'admin'


def is_staff():
    """Check if current user is staff or admin"""
    role = get_current_user_role()
    return is_logged_in() and role in ['staff', 'admin']


def is_customer():
    """Check if current user is customer"""
    return is_logged_in() and get_current_user_role() == 'customer'


def require_login():
    """Require user to be logged in, abort if not"""
    if not is_logged_in():
        abort(403, description="請先登入")


def require_role(required_role):
    """Require specific role, abort if not authorized"""
    if not is_logged_in():
        abort(403, description="請先登入")

    current_role = get_current_user_role()

    # Admin can access everything
    if current_role == 'admin':
        return True

    # Check if user has required role
    if isinstance(required_role, list):
        if current_role not in required_role:
            abort(403, description="您沒有權限訪問此頁面")
    else:
        if current_role != required_role:
            abort(403, description="您沒有權限訪問此頁面")

    return True


def require_admin():
    """Require admin role"""
    require_role('admin')


def require_staff():
    """Require staff or admin role"""
    require_role(['staff', 'admin'])


def require_customer():
    """Require customer role"""
    require_role('customer')


def has_permission(action, resource=None):
    """
    Check if current user has permission for action

    Actions:
    - 'view': Can view resource
    - 'create': Can create new resource
    - 'update': Can update resource
    - 'delete': Can delete resource

    Resources:
    - 'product', 'course', 'order', 'booking', 'customer', 'category'
    """
    if not is_logged_in():
        return False

    role = get_current_user_role()

    # Admin has all permissions
    if role == 'admin':
        return True

    # Staff permissions
    if role == 'staff':
        if action == 'delete':
            return False  # Staff cannot delete
        if action in ['view', 'create', 'update']:
            return True  # Staff can view, create, update

    # Customer permissions
    if role == 'customer':
        # Customers can only manage their own data
        if resource in ['cart', 'booking', 'order']:
            return action in ['view', 'create']
        return False

    return False


def set_user_session(user, role):
    """Set user session data"""
    session['user'] = {
        'user_id': user.info.id,
        'username': user.username,
        'firstname': user.info.firstname,
        'surname': user.info.surname,
        'email': user.info.email,
        'role': role
    }
    session['logged_in'] = True
    session.permanent = True  # Make session permanent (31 days by default)


def clear_user_session():
    """Clear user session"""
    session.pop('user', None)
    session.pop('logged_in', None)
    session.clear()


def update_user_profile(user_id, data):
    """Update user profile"""
    cursor = database.connection.cursor()

    fields = []
    values = []

    if 'firstname' in data and data['firstname']:
        fields.append("firstname = %s")
        values.append(data['firstname'])

    if 'surname' in data and data['surname']:
        fields.append("surname = %s")
        values.append(data['surname'])

    if 'email' in data and data['email']:
        fields.append("email = %s")
        values.append(data['email'])

    if 'phone' in data:
        fields.append("phone = %s")
        values.append(data['phone'])

    if 'line_id' in data:
        fields.append("line_id = %s")
        values.append(data['line_id'])

    if 'address' in data:
        fields.append("address = %s")
        values.append(data['address'])

    if 'password_hash' in data and data['password_hash']:
        fields.append("password_hash = %s")
        values.append(data['password_hash'])

    if not fields:
        return False

    values.append(user_id)
    sql = f"UPDATE users SET {', '.join(fields)} WHERE id = %s"

    try:
        cursor.execute(sql, values)
        database.connection.commit()
        cursor.close()
        return True
    except Exception as e:
        database.connection.rollback()
        cursor.close()
        raise e


def get_user_details(user_id):
    """Get detailed user information"""
    cursor = database.connection.cursor()
    cursor.execute("""
        SELECT id, username, email, firstname, surname, phone, line_id, 
               address, role, created_at
        FROM users
        WHERE id = %s
    """, (user_id,))
    user = cursor.fetchone()
    cursor.close()
    return user


def delete_user(user_id):
    """Delete user (admin only)"""
    cursor = database.connection.cursor()
    try:
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        database.connection.commit()
        cursor.close()
        return True
    except Exception as e:
        database.connection.rollback()
        cursor.close()
        raise e
