from flask import session, flash, redirect, url_for, abort
from functools import wraps


def login_required(f):
    """Decorator to require user to be logged in"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('請先登入', 'error')
            return redirect(url_for('main.home'))
        return f(*args, **kwargs)
    return decorated_function


def customer_required(f):
    """Decorator to require customer role OR admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('請先登入', 'error')
            return redirect(url_for('main.home'))

        user = session.get('user', {})
        # 修改：允許 customer 或 admin 或 staff
        if user.get('role') not in ['customer', 'admin', 'staff']:
            flash('此功能僅限會員使用', 'error')
            return redirect(url_for('main.home'))
        return f(*args, **kwargs)
    return decorated_function


def staff_required(f):
    """Decorator to require staff or admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('請先登入', 'error')
            return redirect(url_for('main.home'))

        user = session.get('user', {})
        if user.get('role') not in ['staff', 'admin']:
            flash('您沒有權限訪問此頁面', 'error')
            return redirect(url_for('main.home'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash('請先登入', 'error')
            return redirect(url_for('main.home'))

        user = session.get('user', {})
        if user.get('role') != 'admin':
            flash('此功能僅限管理員使用', 'error')
            return redirect(url_for('admin.dashboard'))
        return f(*args, **kwargs)
    return decorated_function
