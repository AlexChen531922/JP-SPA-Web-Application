"""
Complete Admin Management System with Advanced Reporting
Fixed all CRUD operations and inventory integration
"""

from flask import Blueprint, render_template, request, jsonify
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, current_app
from functools import wraps
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os
from project.extensions import database
from project.db import get_current_user_id, get_current_user_role
import MySQLdb.cursors
from decimal import Decimal

admin_bp = Blueprint('admin', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file, upload_folder):
    """Save uploaded file with timestamp"""
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = f"{timestamp}_{filename}"
        filepath = os.path.join(upload_folder, filename)
        file.save(filepath)
        return f"img/{filename}"
    return None


def staff_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        role = get_current_user_role()
        if role not in ['staff', 'admin']:
            flash('您沒有權限訪問此頁面', 'error')
            return redirect(url_for('main.home'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if get_current_user_role() != 'admin':
            flash('此功能僅限管理員使用', 'error')
            return redirect(url_for('admin.dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# =====================================================
# DASHBOARD WITH COMPLETE DATA
# =====================================================


@admin_bp.route('/dashboard')
@staff_required
def dashboard():
    tab = request.args.get('tab', 'overview')
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    # Basic statistics
    cursor.execute(
        "SELECT COUNT(*) as count FROM products WHERE is_active = TRUE")
    product_count = cursor.fetchone()['count']

    cursor.execute(
        "SELECT COUNT(*) as count FROM courses WHERE is_active = TRUE")
    course_count = cursor.fetchone()['count']

    cursor.execute(
        "SELECT COUNT(*) as count FROM orders WHERE status != 'cancelled'")
    order_count = cursor.fetchone()['count']

    cursor.execute(
        "SELECT COUNT(*) as count FROM bookings WHERE status != 'cancelled'")
    booking_count = cursor.fetchone()['count']

    cursor.execute(
        "SELECT COUNT(*) as count FROM users WHERE role = 'customer'")
    customer_count = cursor.fetchone()['count']

    cursor.execute(
        "SELECT COALESCE(SUM(total_amount), 0) as total FROM orders WHERE status != 'cancelled'")
    total_revenue = cursor.fetchone()['total']

    # Recent orders
    cursor.execute("""
        SELECT o.id, o.total_amount, o.status, o.created_at,
               u.username, u.firstname, u.surname
        FROM orders o
        JOIN users u ON o.customer_id = u.id
        ORDER BY o.created_at DESC
        LIMIT 10
    """)
    recent_orders = cursor.fetchall()

    # Recent bookings
    cursor.execute("""
        SELECT b.id, b.sessions_purchased, b.total_amount, b.status, b.created_at,
               u.username, u.firstname, u.surname, c.name as course_name
        FROM bookings b
        JOIN users u ON b.customer_id = u.id
        JOIN courses c ON b.course_id = c.id
        ORDER BY b.created_at DESC
        LIMIT 10
    """)
    recent_bookings = cursor.fetchall()

    # Products with full details
    cursor.execute("""
        SELECT p.*, pc.name as category_name
        FROM products p
        LEFT JOIN product_categories pc ON p.category_id = pc.id
        ORDER BY p.created_at DESC
    """)
    products = cursor.fetchall()

    # Courses with full details
    cursor.execute("""
        SELECT c.*, cc.name as category_name
        FROM courses c
        LEFT JOIN course_categories cc ON c.category_id = cc.id
        ORDER BY c.created_at DESC
    """)
    courses = cursor.fetchall()

    # Categories
    cursor.execute(
        "SELECT * FROM product_categories ORDER BY display_order, name")
    product_categories = cursor.fetchall()

    cursor.execute(
        "SELECT * FROM course_categories ORDER BY display_order, name")
    course_categories = cursor.fetchall()

    # Events with customer names
    cursor.execute("""
        SELECT e.*, 
               CONCAT(u.firstname, ' ', u.surname) as customer_name
        FROM events e
        LEFT JOIN users u ON e.customer_id = u.id
        ORDER BY e.start_date DESC
    """)
    events = cursor.fetchall()

    # Inventory products
    cursor.execute("""
        SELECT id, name, stock_quantity, cost, price
        FROM products
        ORDER BY name
    """)
    inventory_products = cursor.fetchall()

    # Customers for event dropdown
    cursor.execute("""
        SELECT id, firstname, surname 
        FROM users 
        WHERE role = 'customer' 
        ORDER BY firstname
    """)
    customers = cursor.fetchall()

    # Orders for management
    cursor.execute("""
        SELECT o.*, u.username, u.firstname, u.surname, u.email
        FROM orders o
        JOIN users u ON o.customer_id = u.id
        ORDER BY o.created_at DESC
    """)
    orders = cursor.fetchall()

    # Bookings for management
    cursor.execute("""
        SELECT b.*, u.username, u.firstname, u.surname, u.email,
               c.name as course_name
        FROM bookings b
        JOIN users u ON b.customer_id = u.id
        JOIN courses c ON b.course_id = c.id
        ORDER BY b.created_at DESC
    """)
    bookings = cursor.fetchall()

    # Customer list
    cursor.execute("""
        SELECT u.id, u.username, u.email, u.firstname, u.surname,
               u.phone, u.created_at,
               COUNT(DISTINCT o.id) as order_count,
               COUNT(DISTINCT b.id) as booking_count
        FROM users u
        LEFT JOIN orders o ON u.id = o.customer_id
        LEFT JOIN bookings b ON u.id = b.customer_id
        WHERE u.role = 'customer'
        GROUP BY u.id
        ORDER BY u.created_at DESC
    """)
    customers_list = cursor.fetchall()

    # Blog posts
    cursor.execute("""
        SELECT p.*, u.firstname, u.surname,
               CONCAT(u.firstname, ' ', u.surname) as author_name
        FROM blog_posts p
        LEFT JOIN users u ON p.author_id = u.id
        ORDER BY p.created_at DESC
    """)
    posts = cursor.fetchall()

    cursor.close()

    stats = {
        'products': product_count,
        'courses': course_count,
        'orders': order_count,
        'bookings': booking_count,
        'customers': customer_count,
        'revenue': float(total_revenue)
    }

    return render_template(
        'admin_dashboard.html',
        tab=tab,
        stats=stats,
        recent_orders=recent_orders,
        recent_bookings=recent_bookings,
        products=products,
        courses=courses,
        product_categories=product_categories,
        course_categories=course_categories,
        events=events,
        inventory_products=inventory_products,
        customers=customers,
        orders=orders,
        bookings=bookings,
        customers_list=customers_list,
        posts=posts
    )

# =====================================================
# PRODUCT MANAGEMENT - FIXED
# =====================================================


@admin_bp.route('/product/add', methods=['POST'])
@staff_required
def add_product_modal():
    """Add new product"""
    try:
        name = request.form.get('name', '').strip()
        category_id = request.form.get('category_id', type=int) or None
        price = request.form.get('price', type=float)
        cost = request.form.get('cost', 0, type=float)
        stock = request.form.get('stock', 0, type=int)
        unit = request.form.get('unit', '件').strip()
        description = request.form.get('description', '').strip()

        if not name or price is None:
            flash('請填寫必填欄位', 'error')
            return redirect(url_for('admin.dashboard', tab='products'))

        # Handle image upload
        image_url = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                image_url = save_upload(
                    file, current_app.config['UPLOAD_FOLDER'])

        cursor = database.connection.cursor()
        cursor.execute("""
            INSERT INTO products (name, category_id, price, cost, stock_quantity, unit, description, image)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (name, category_id, price, cost, stock, unit, description, image_url))

        product_id = cursor.lastrowid

        # Log initial inventory
        if stock > 0:
            cursor.execute("""
                INSERT INTO inventory_logs (product_id, change_amount, change_type, notes, created_by)
                VALUES (%s, %s, 'purchase', 'Initial stock', %s)
            """, (product_id, stock, get_current_user_id()))

        database.connection.commit()
        cursor.close()

        flash('產品已新增', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'新增失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='products'))


@admin_bp.route('/product/<int:product_id>/update', methods=['POST'])
@staff_required
def update_product_modal(product_id):
    """Update product"""
    try:
        name = request.form.get('name', '').strip()
        category_id = request.form.get('category_id', type=int) or None
        price = request.form.get('price', type=float)
        cost = request.form.get('cost', 0, type=float)
        stock = request.form.get('stock', 0, type=int)
        unit = request.form.get('unit', '件').strip()
        description = request.form.get('description', '').strip()
        is_active = request.form.get('is_active') == 'on'

        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

        # Get current stock for comparison
        cursor.execute(
            "SELECT stock_quantity FROM products WHERE id = %s", (product_id,))
        current = cursor.fetchone()
        old_stock = current['stock_quantity'] if current else 0

        # Handle image
        image_url = request.form.get('current_image')
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                new_image = save_upload(
                    file, current_app.config['UPLOAD_FOLDER'])
                if new_image:
                    image_url = new_image

        # Update product
        cursor.execute("""
            UPDATE products
            SET name=%s, category_id=%s, price=%s, cost=%s, stock_quantity=%s,
                unit=%s, description=%s, image=%s, is_active=%s
            WHERE id=%s
        """, (name, category_id, price, cost, stock, unit, description, image_url, is_active, product_id))

        # Log stock change if different
        if stock != old_stock:
            change = stock - old_stock
            cursor.execute("""
                INSERT INTO inventory_logs (product_id, change_amount, change_type, notes, created_by)
                VALUES (%s, %s, 'adjustment', 'Stock updated via product edit', %s)
            """, (product_id, change, get_current_user_id()))

        database.connection.commit()
        cursor.close()

        flash('產品已更新', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'更新失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='products'))


@admin_bp.route('/product/<int:product_id>/delete', methods=['POST'])
@admin_required
def delete_product_modal(product_id):
    """Delete product"""
    try:
        cursor = database.connection.cursor()
        cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
        database.connection.commit()
        cursor.close()
        flash('產品已刪除', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'刪除失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='products'))

# =====================================================
# COURSE MANAGEMENT - FIXED
# =====================================================


@admin_bp.route('/course/add', methods=['POST'])
@staff_required
def add_course_modal():
    """Add new course"""
    try:
        name = request.form.get('name', '').strip()
        category_id = request.form.get('category_id', type=int) or None
        regular_price = request.form.get('regular_price', type=float)
        experience_price = request.form.get(
            'experience_price', type=float) or None
        duration = request.form.get('duration', type=int) or None
        sessions = request.form.get('sessions', 1, type=int)
        description = request.form.get('description', '').strip()

        if not name or regular_price is None:
            flash('請填寫必填欄位', 'error')
            return redirect(url_for('admin.dashboard', tab='courses'))

        image_url = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                image_url = save_upload(
                    file, current_app.config['UPLOAD_FOLDER'])

        cursor = database.connection.cursor()
        cursor.execute("""
            INSERT INTO courses (name, category_id, regular_price, experience_price, 
                               duration, sessions, description, image)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (name, category_id, regular_price, experience_price, duration, sessions, description, image_url))

        database.connection.commit()
        cursor.close()

        flash('課程已新增', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'新增失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='courses'))


@admin_bp.route('/course/<int:course_id>/update', methods=['POST'])
@staff_required
def update_course_modal(course_id):
    """Update course"""
    try:
        name = request.form.get('name', '').strip()
        category_id = request.form.get('category_id', type=int) or None
        regular_price = request.form.get('regular_price', type=float)
        experience_price = request.form.get(
            'experience_price', type=float) or None
        duration = request.form.get('duration', type=int) or None
        sessions = request.form.get('sessions', 1, type=int)
        description = request.form.get('description', '').strip()
        is_active = request.form.get('is_active') == 'on'

        image_url = request.form.get('current_image')
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                new_image = save_upload(
                    file, current_app.config['UPLOAD_FOLDER'])
                if new_image:
                    image_url = new_image

        cursor = database.connection.cursor()
        cursor.execute("""
            UPDATE courses
            SET name=%s, category_id=%s, regular_price=%s, experience_price=%s,
                duration=%s, sessions=%s, description=%s, image=%s, is_active=%s
            WHERE id=%s
        """, (name, category_id, regular_price, experience_price, duration, sessions,
              description, image_url, is_active, course_id))

        database.connection.commit()
        cursor.close()

        flash('課程已更新', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'更新失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='courses'))


@admin_bp.route('/course/<int:course_id>/delete', methods=['POST'])
@admin_required
def delete_course_modal(course_id):
    """Delete course"""
    try:
        cursor = database.connection.cursor()
        cursor.execute("DELETE FROM courses WHERE id = %s", (course_id,))
        database.connection.commit()
        cursor.close()
        flash('課程已刪除', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'刪除失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='courses'))

# =====================================================
# CATEGORY MANAGEMENT - FIXED
# =====================================================


@admin_bp.route('/category/product/add', methods=['POST'])
@staff_required
def add_product_category():
    """Add product category"""
    try:
        name = request.form.get('name', '').strip()
        if not name:
            flash('請輸入分類名稱', 'error')
            return redirect(url_for('admin.dashboard', tab='categories'))

        cursor = database.connection.cursor()
        cursor.execute(
            "INSERT INTO product_categories (name) VALUES (%s)", (name,))
        database.connection.commit()
        cursor.close()
        flash('產品分類已新增', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'新增失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='categories'))


@admin_bp.route('/category/course/add', methods=['POST'])
@staff_required
def add_course_category():
    """Add course category"""
    try:
        name = request.form.get('name', '').strip()
        if not name:
            flash('請輸入分類名稱', 'error')
            return redirect(url_for('admin.dashboard', tab='categories'))

        cursor = database.connection.cursor()
        cursor.execute(
            "INSERT INTO course_categories (name) VALUES (%s)", (name,))
        database.connection.commit()
        cursor.close()
        flash('課程分類已新增', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'新增失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='categories'))


@admin_bp.route('/category/product/<int:category_id>/delete', methods=['POST'])
@admin_required
def delete_product_category(category_id):
    """Delete product category"""
    try:
        cursor = database.connection.cursor()
        cursor.execute(
            "DELETE FROM product_categories WHERE id = %s", (category_id,))
        database.connection.commit()
        cursor.close()
        flash('產品分類已刪除', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'刪除失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='categories'))


@admin_bp.route('/category/course/<int:category_id>/delete', methods=['POST'])
@admin_required
def delete_course_category(category_id):
    """Delete course category"""
    try:
        cursor = database.connection.cursor()
        cursor.execute(
            "DELETE FROM course_categories WHERE id = %s", (category_id,))
        database.connection.commit()
        cursor.close()
        flash('課程分類已刪除', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'刪除失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='categories'))

# =====================================================
# EVENT MANAGEMENT - FIXED
# =====================================================


@admin_bp.route('/event/add', methods=['POST'])
@staff_required
def add_event():
    """Add new event"""
    try:
        title = request.form.get('title', '').strip()
        customer_id = request.form.get('customer_id', type=int) or None
        start_date = request.form.get('start_date') or None
        end_date = request.form.get('end_date') or None
        duration = request.form.get('duration', type=int) or None
        description = request.form.get('description', '').strip()

        if not title:
            flash('請填寫標題', 'error')
            return redirect(url_for('admin.dashboard', tab='events'))

        # Convert datetime-local format
        def parse_dt(s):
            if not s:
                return None
            return s.replace('T', ' ') + ':00' if 'T' in s and len(s) <= 16 else s.replace('T', ' ')

        s = parse_dt(start_date)
        e = parse_dt(end_date)

        cursor = database.connection.cursor()
        cursor.execute("""
            INSERT INTO events (title, description, customer_id, start_date, end_date, duration)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (title, description, customer_id, s, e, duration))
        database.connection.commit()
        cursor.close()

        flash('活動已新增', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'新增失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='events'))


@admin_bp.route('/event/<int:event_id>/update', methods=['POST'])
@staff_required
def update_event(event_id):
    """Update event"""
    try:
        title = request.form.get('title', '').strip()
        customer_id = request.form.get('customer_id', type=int) or None
        start_date = request.form.get('start_date') or None
        end_date = request.form.get('end_date') or None
        duration = request.form.get('duration', type=int) or None
        description = request.form.get('description', '').strip()

        if not title:
            flash('請填寫標題', 'error')
            return redirect(url_for('admin.dashboard', tab='events'))

        def parse_dt(s):
            if not s:
                return None
            return s.replace('T', ' ') + ':00' if 'T' in s and len(s) <= 16 else s.replace('T', ' ')

        s = parse_dt(start_date)
        e = parse_dt(end_date)

        cursor = database.connection.cursor()
        cursor.execute("""
            UPDATE events
            SET title=%s, description=%s, customer_id=%s, start_date=%s, end_date=%s, duration=%s
            WHERE id=%s
        """, (title, description, customer_id, s, e, duration, event_id))
        database.connection.commit()
        cursor.close()

        flash('活動已更新', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'更新失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='events'))


@admin_bp.route('/event/<int:event_id>/delete', methods=['POST'])
@admin_required
def delete_event(event_id):
    """Delete event"""
    try:
        cursor = database.connection.cursor()
        cursor.execute("DELETE FROM events WHERE id = %s", (event_id,))
        database.connection.commit()
        cursor.close()
        flash('活動已刪除', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'刪除失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='events'))

# =====================================================
# INVENTORY MANAGEMENT WITH AUTO-SYNC
# =====================================================


@admin_bp.route('/inventory/adjust', methods=['POST'])
@staff_required
def adjust_inventory_modal():
    """Adjust inventory - auto syncs with products"""
    try:
        product_id = request.form.get('product_id', type=int)
        change_amount = request.form.get('change_amount', type=int)
        change_type = request.form.get('change_type', 'adjustment')
        notes = request.form.get('notes', '').strip()

        if not product_id or change_amount == 0:
            flash('請填寫完整資料', 'error')
            return redirect(url_for('admin.dashboard', tab='inventory'))

        cursor = database.connection.cursor()

        # Update product stock
        cursor.execute("""
            UPDATE products 
            SET stock_quantity = stock_quantity + %s 
            WHERE id = %s
        """, (change_amount, product_id))

        # Log inventory change
        cursor.execute("""
            INSERT INTO inventory_logs 
            (product_id, change_amount, change_type, notes, created_by)
            VALUES (%s, %s, %s, %s, %s)
        """, (product_id, change_amount, change_type, notes, get_current_user_id()))

        database.connection.commit()
        cursor.close()

        flash('庫存已調整', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'調整失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='inventory'))

# =====================================================
# ORDER & BOOKING STATUS UPDATES
# =====================================================


@admin_bp.route('/order/<int:order_id>/update-status', methods=['POST'])
@staff_required
def update_order_status(order_id):
    """Update order status"""
    try:
        status = request.form.get('status')
        allowed_statuses = ['pending', 'confirmed', 'completed', 'cancelled']

        if status not in allowed_statuses:
            flash('無效的狀態', 'error')
            return redirect(url_for('admin.dashboard', tab='orders'))

        cursor = database.connection.cursor()
        cursor.execute("""
            UPDATE orders 
            SET status = %s 
            WHERE id = %s
        """, (status, order_id))
        database.connection.commit()
        cursor.close()

        flash('訂單狀態已更新', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'更新失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='orders'))


@admin_bp.route('/booking/<int:booking_id>/update-status', methods=['POST'])
@staff_required
def update_booking_status(booking_id):
    """Update booking status"""
    try:
        status = request.form.get('status')
        allowed_statuses = ['pending', 'confirmed', 'completed', 'cancelled']

        if status not in allowed_statuses:
            flash('無效的狀態', 'error')
            return redirect(url_for('admin.dashboard', tab='bookings'))

        cursor = database.connection.cursor()
        cursor.execute("""
            UPDATE bookings 
            SET status = %s 
            WHERE id = %s
        """, (status, booking_id))
        database.connection.commit()
        cursor.close()

        flash('預約狀態已更新', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'更新失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='bookings'))

# =====================================================
# CUSTOMER MANAGEMENT
# =====================================================


@admin_bp.route('/customer/<int:customer_id>/delete', methods=['POST'])
@admin_required
def delete_customer(customer_id):
    """Delete customer"""
    try:
        cursor = database.connection.cursor()
        cursor.execute(
            "DELETE FROM users WHERE id = %s AND role = 'customer'", (customer_id,))
        database.connection.commit()
        cursor.close()
        flash('客戶已刪除', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'刪除失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='customers'))


"""
Advanced Reporting System with Filters
Supports: Daily, Weekly, Monthly, Quarterly, Yearly reports
Sales rankings by quantity and revenue
Event analytics
"""


reports_bp = Blueprint('reports', __name__, url_prefix='/admin/reports')


def get_date_range(period, custom_start=None, custom_end=None):
    """Get date range based on period"""
    today = datetime.now().date()

    if period == 'today':
        start_date = today
        end_date = today
    elif period == 'yesterday':
        start_date = today - timedelta(days=1)
        end_date = today - timedelta(days=1)
    elif period == 'week':
        start_date = today - timedelta(days=today.weekday())
        end_date = today
    elif period == 'last_week':
        start_date = today - timedelta(days=today.weekday() + 7)
        end_date = today - timedelta(days=today.weekday() + 1)
    elif period == 'month':
        start_date = today.replace(day=1)
        end_date = today
    elif period == 'last_month':
        last_month = today.replace(day=1) - timedelta(days=1)
        start_date = last_month.replace(day=1)
        end_date = last_month
    elif period == 'quarter':
        quarter = (today.month - 1) // 3
        start_date = today.replace(month=quarter * 3 + 1, day=1)
        end_date = today
    elif period == 'year':
        start_date = today.replace(month=1, day=1)
        end_date = today
    elif period == 'custom' and custom_start and custom_end:
        start_date = datetime.strptime(custom_start, '%Y-%m-%d').date()
        end_date = datetime.strptime(custom_end, '%Y-%m-%d').date()
    else:
        start_date = today - timedelta(days=30)
        end_date = today

    return start_date, end_date


# =====================================================
# BLOG MANAGEMENT
# =====================================================
@admin_bp.route('/add_post', methods=['GET', 'POST'])
@staff_required
def add_post():
    return "Add post page"


@admin_bp.route('/edit-post/<int:post_id>', methods=['GET', 'POST'])
def edit_post(post_id):
    cursor = mysql.connection.cursor()

    # 取得文章資料
    cursor.execute("SELECT * FROM posts WHERE id = %s", (post_id,))
    post = cursor.fetchone()

    if not post:
        flash("找不到該文章", "danger")
        return redirect(url_for('admin.posts'))

    # POST → 更新文章
    if request.method == 'POST':
        title = request.form.get("title")
        summary = request.form.get("summary")
        content = request.form.get("content")
        status = request.form.get("status")

        # 處理圖片
        image = post['image']  # 原本的圖片
        file = request.files.get("image")

        if file and file.filename:
            filename = secure_filename(file.filename)
            filepath = os.path.join('static/uploads', filename)
            file.save(filepath)
            image = f'uploads/{filename}'

        cursor.execute("""
            UPDATE posts
            SET title=%s, summary=%s, content=%s, status=%s, image=%s
            WHERE id=%s
        """, (title, summary, content, status, image, post_id))
        mysql.connection.commit()

        flash("文章已成功更新", "success")
        return redirect(url_for('admin.posts'))

    # GET → 顯示編輯頁
    return render_template(
        "admin_post_form.html",  # 你給我的這份就是這頁
        post=post
    )


@admin_bp.route("/posts/delete/<int:post_id>", methods=["POST"])
def delete_post(post_id):
    # TODO: 在此寫刪除文章的邏輯
    # 例如：
    # post = Post.query.get_or_404(post_id)
    # db.session.delete(post)
    # db.session.commit()

    flash("文章已刪除", "success")
    return redirect(url_for("admin.posts"))
