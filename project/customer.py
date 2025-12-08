from flask import Blueprint, render_template, request, session, flash, redirect, url_for
from .decorators import login_required, customer_required
from project.extensions import database
from .db import get_current_user_id, get_user_details, update_user_profile
import MySQLdb.cursors
import re  # 引入正則表達式用於密碼驗證

customer_bp = Blueprint('customer', __name__, url_prefix='/customer')


def validate_password_strength(password):
    """
    驗證密碼強度：
    1. 至少 10 個字元
    2. 包含大寫字母
    3. 包含小寫字母
    4. 包含數字
    5. 包含特殊符號
    """
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


@customer_bp.route('/dashboard')
@customer_required
def dashboard():
    """Customer dashboard"""
    user_id = get_current_user_id()
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    # ⭐ 關鍵：取得使用者詳細資料 (用於填寫 Modal)
    user = get_user_details(user_id)

    # Get active bookings
    cursor.execute("""
        SELECT b.id, b.sessions_purchased, b.sessions_remaining, b.total_amount,
               b.created_at, c.name as course_name, c.duration
        FROM bookings b
        JOIN courses c ON b.course_id = c.id
        WHERE b.customer_id = %s AND b.sessions_remaining > 0
        ORDER BY b.created_at DESC
    """, (user_id,))
    active_courses = cursor.fetchall()

    # Get recent orders
    cursor.execute("""
        SELECT o.id, o.total_amount, o.status, o.created_at,
               COUNT(oi.id) as item_count
        FROM orders o
        LEFT JOIN order_items oi ON o.id = oi.order_id
        WHERE o.customer_id = %s
        GROUP BY o.id, o.total_amount, o.status, o.created_at
        ORDER BY o.created_at DESC
        LIMIT 5
    """, (user_id,))
    recent_orders = cursor.fetchall()

    # Get products from recent orders
    cursor.execute("""
        SELECT oi.product_id, p.name, SUM(oi.quantity) as total_quantity
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.id
        JOIN products p ON oi.product_id = p.id
        WHERE o.customer_id = %s AND o.status IN ('confirmed', 'completed')
        GROUP BY oi.product_id, p.name
        ORDER BY MAX(o.created_at) DESC
    """, (user_id,))
    purchased_products = cursor.fetchall()

    cursor.close()

    return render_template(
        'customer_dashboard.html',
        user=user,  # 確保這裡有傳入 user
        active_courses=active_courses,
        recent_orders=recent_orders,
        purchased_products=purchased_products
    )


@customer_bp.route('/bookings')
@customer_required
def bookings():
    """View all bookings"""
    user_id = get_current_user_id()
    user = get_user_details(user_id)  # 取得 user 資料
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    cursor.execute("""
        SELECT b.id, b.sessions_purchased, b.sessions_remaining, b.total_amount,
               b.is_first_time, b.status, b.created_at,
               c.name as course_name, c.duration
        FROM bookings b
        JOIN courses c ON b.course_id = c.id
        WHERE b.customer_id = %s
        ORDER BY b.created_at DESC
    """, (user_id,))
    bookings = cursor.fetchall()

    cursor.close()
    return render_template('customer_bookings.html', bookings=bookings, user=user)


@customer_bp.route('/orders')
@customer_required
def orders():
    """View all orders"""
    user_id = get_current_user_id()
    user = get_user_details(user_id)  # 取得 user 資料
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    cursor.execute("""
        SELECT o.id, o.total_amount, o.status, o.created_at,
               o.payment_method, o.notes
        FROM orders o
        WHERE o.customer_id = %s
        ORDER BY o.created_at DESC
    """, (user_id,))
    orders = cursor.fetchall()

    # Get items for each order
    order_items = {}
    for order in orders:
        cursor.execute("""
            SELECT oi.quantity, oi.unit_price, oi.subtotal,
                   p.name, p.image
            FROM order_items oi
            JOIN products p ON oi.product_id = p.id
            WHERE oi.order_id = %s
        """, (order['id'],))
        order_items[order['id']] = cursor.fetchall()

    cursor.close()
    return render_template('customer_orders.html', orders=orders, order_items=order_items, user=user)


@customer_bp.route('/order/<int:order_id>')
@customer_required
def order_detail(order_id):
    """View order details"""
    user_id = get_current_user_id()
    user = get_user_details(user_id)  # 取得 user 資料
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    cursor.execute("""
        SELECT o.*
        FROM orders o
        WHERE o.id = %s AND o.customer_id = %s
    """, (order_id, user_id))
    order = cursor.fetchone()

    if not order:
        cursor.close()
        flash('訂單不存在', 'error')
        return redirect(url_for('customer.orders'))

    cursor.execute("""
        SELECT oi.quantity, oi.unit_price, oi.subtotal,
               p.name, p.image, p.description
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id = %s
    """, (order_id,))
    items = cursor.fetchall()

    cursor.close()
    return render_template('customer_order_detail.html', order=order, items=items, user=user)


@customer_bp.route('/profile/update', methods=['POST'])
@customer_required
def update_profile():
    """Handle profile update"""
    user_id = get_current_user_id()

    # 檢查密碼規則 (如果有填寫新密碼)
    new_password = request.form.get('password')
    if new_password:
        is_valid, error_msg = validate_password_strength(new_password)
        if not is_valid:
            flash(error_msg, 'error')
            return redirect(request.referrer or url_for('customer.dashboard'))

    if update_user_profile(user_id, request.form):
        flash('個人資料已更新', 'success')
    else:
        flash('更新失敗，請稍後再試', 'error')

    return redirect(request.referrer or url_for('customer.dashboard'))
