from flask import Blueprint, render_template, request, session, flash, redirect, url_for
from functools import wraps
from hashlib import sha256
from . import database
from .db import get_current_user_id, get_current_user_role, update_user_profile, get_user_details
import MySQLdb.cursors

customer_bp = Blueprint('customer', __name__)


def customer_required(f):
    """Decorator to require customer role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if get_current_user_role() != 'customer':
            flash('此功能僅限會員使用', 'error')
            return redirect(url_for('main.home'))
        return f(*args, **kwargs)
    return decorated_function


@customer_bp.route('/dashboard')
@customer_required
def dashboard():
    """Customer dashboard"""
    user_id = get_current_user_id()
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    # Get user info
    user = get_user_details(user_id)

    # Get active bookings (courses with remaining sessions)
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
        GROUP BY o.id
        ORDER BY o.created_at DESC
        LIMIT 5
    """, (user_id,))
    recent_orders = cursor.fetchall()

    # Get products from recent orders (not yet fully used)
    cursor.execute("""
        SELECT oi.product_id, p.name, SUM(oi.quantity) as total_quantity
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.id
        JOIN products p ON oi.product_id = p.id
        WHERE o.customer_id = %s AND o.status IN ('confirmed', 'completed')
        GROUP BY oi.product_id, p.name
        ORDER BY o.created_at DESC
    """, (user_id,))
    purchased_products = cursor.fetchall()

    cursor.close()

    return render_template(
        'customer_dashboard.html',
        user=user,
        active_courses=active_courses,
        recent_orders=recent_orders,
        purchased_products=purchased_products
    )


@customer_bp.route('/profile/update', methods=['POST'])
@customer_required
def update_profile():
    """Update customer profile"""
    user_id = get_current_user_id()

    data = {
        'firstname': request.form.get('firstname', '').strip(),
        'surname': request.form.get('surname', '').strip(),
        'email': request.form.get('email', '').strip(),
        'phone': request.form.get('phone', '').strip(),
        'line_id': request.form.get('line_id', '').strip(),
        'address': request.form.get('address', '').strip()
    }

    # Handle password change
    new_password = request.form.get('password', '').strip()
    if new_password:
        if len(new_password) < 6:
            flash('密碼至少需要 6 個字元', 'error')
            return redirect(url_for('customer.dashboard'))
        data['password_hash'] = sha256(new_password.encode()).hexdigest()

    try:
        update_user_profile(user_id, data)

        # Update session
        session['user'].update({
            'firstname': data['firstname'],
            'surname': data['surname'],
            'email': data['email']
        })

        flash('個人資料已更新', 'success')
    except Exception as e:
        flash(f'更新失敗：{str(e)}', 'error')

    return redirect(url_for('customer.dashboard'))


@customer_bp.route('/bookings')
@customer_required
def bookings():
    """View all bookings"""
    user_id = get_current_user_id()
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

    return render_template('customer_bookings.html', bookings=bookings)


@customer_bp.route('/orders')
@customer_required
def orders():
    """View all orders"""
    user_id = get_current_user_id()
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

    return render_template(
        'customer_orders.html',
        orders=orders,
        order_items=order_items
    )


@customer_bp.route('/order/<int:order_id>')
@customer_required
def order_detail(order_id):
    """View order details"""
    user_id = get_current_user_id()
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    # Get order
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

    # Get order items
    cursor.execute("""
        SELECT oi.quantity, oi.unit_price, oi.subtotal,
               p.name, p.image, p.description
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id = %s
    """, (order_id,))
    items = cursor.fetchall()

    cursor.close()

    return render_template(
        'customer_order_detail.html',
        order=order,
        items=items
    )
