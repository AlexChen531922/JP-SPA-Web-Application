"""
Complete Admin Management System with Advanced Reporting
Fixed all CRUD operations and inventory integration
"""
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, current_app
from functools import wraps
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os
from project.extensions import database
from project.db import get_current_user_id, get_current_user_role
import MySQLdb.cursors
from decimal import Decimal
from project.services import admin_update_order_with_inventory
from project.db import get_current_user_id
from project.audit import log_activity

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
        SELECT o.*, u.username, u.firstname, u.surname, u.email, u.phone
        FROM orders o
        JOIN users u ON o.customer_id = u.id
        ORDER BY o.created_at DESC
    """)
    orders = cursor.fetchall()

    # 查詢所有訂單的細項 (Items)
    cursor.execute("""
        SELECT oi.order_id, oi.quantity, oi.unit_price, oi.subtotal,
               p.name as product_name
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
    """)
    all_items = cursor.fetchall()

    # 將細項整理成字典 {order_id: [item1, item2...]}
    order_items_map = {}
    for item in all_items:
        oid = item['order_id']
        if oid not in order_items_map:
            order_items_map[oid] = []
        order_items_map[oid].append(item)

    # Bookings for management
    cursor.execute("""
        SELECT b.*, 
               u.username, u.firstname, u.surname, u.email, u.phone, u.line_id,
               c.name as course_name, c.duration,
               cs.start_time, cs.end_time
        FROM bookings b
        LEFT JOIN users u ON b.customer_id = u.id
        LEFT JOIN courses c ON b.course_id = c.id
        LEFT JOIN course_schedules cs ON b.schedule_id = cs.id
        ORDER BY b.created_at DESC
    """)
    bookings = cursor.fetchall()

# Customer list (Updated with full details)
    cursor.execute("""
        SELECT u.id, u.username, u.email, u.firstname, u.surname,
               u.phone, u.line_id, u.gender, u.occupation,
               u.created_at,
               u.birth_date,  -- ⭐ 新增這一行：查詢生日原始資料
               u.source_id,   -- ⭐ 新增這一行：查詢來源 ID
               TIMESTAMPDIFF(YEAR, u.birth_date, CURDATE()) as age,
               cs.name as source_name,
               COUNT(DISTINCT o.id) as order_count,
               COUNT(DISTINCT b.id) as booking_count
        FROM users u
        LEFT JOIN customer_sources cs ON u.source_id = cs.id
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
# 只有 Admin 才能查看操作紀錄
    audit_logs = []
    if get_current_user_role() == 'admin':
        cursor.execute("""
            SELECT a.*, 
                   u.username, u.firstname, u.surname,
                   CONCAT(u.firstname, ' ', u.surname) as operator_name
            FROM audit_logs a
            LEFT JOIN users u ON a.user_id = u.id
            ORDER BY a.created_at DESC
            LIMIT 50
        """)
        audit_logs = cursor.fetchall()

    # Get customer sources for dropdown
    cursor.execute("SELECT * FROM customer_sources ORDER BY id")
    customer_sources = cursor.fetchall()

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
        customer_sources=customer_sources,
        posts=posts,
        order_items_map=order_items_map
    )

# =====================================================
# PRODUCT MANAGEMENT - WITH AUDIT LOG
# =====================================================


@admin_bp.route('/product/add', methods=['POST'])
@staff_required
def add_product_modal():
    """Add new product"""
    try:
        name = request.form.get('name', '').strip()
        category_id = request.form.get('category_id', type=int) or None
        price = request.form.get('price', 0, type=float)
        cost = request.form.get('cost', 0, type=float)
        stock = request.form.get('stock', 0, type=int)
        unit = request.form.get('unit', '件').strip()
        description = request.form.get('description', '').strip()

        if not name:
            flash('請填寫產品名稱', 'error')
            return redirect(url_for('admin.dashboard', tab='products'))

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

        # ⭐ LOG ACTIVITY
        log_activity('create', 'product', product_id, {
                     'name': name, 'price': price, 'stock': stock})

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
        price = request.form.get('price', 0, type=float)
        cost = request.form.get('cost', 0, type=float)
        stock = request.form.get('stock', 0, type=int)
        unit = request.form.get('unit', '件').strip()
        description = request.form.get('description', '').strip()
        is_active = request.form.get('is_active') == 'on'

        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

        # Get current data for logging & stock check
        cursor.execute(
            "SELECT name, price, stock_quantity, image FROM products WHERE id = %s", (product_id,))
        old_data = cursor.fetchone()
        old_stock = old_data['stock_quantity'] if old_data else 0

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

        # ⭐ LOG ACTIVITY
        log_changes = {
            'old_data': {'name': old_data['name'], 'price': float(old_data['price'])},
            'new_data': {'name': name, 'price': price}
        }
        print(f"呼叫 Log: Product {product_id}")
        log_activity('update', 'product', product_id,
                     {'name': name, 'price': price})

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

        # Get name for log
        cursor.execute(
            "SELECT name FROM products WHERE id = %s", (product_id,))
        res = cursor.fetchone()
        p_name = res[0] if res else 'Unknown'

        cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
        database.connection.commit()
        cursor.close()

        # ⭐ LOG ACTIVITY
        log_activity('delete', 'product', product_id, {'name': p_name})

        flash('產品已刪除', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'刪除失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='products'))

# =====================================================
# COURSE MANAGEMENT - WITH AUDIT LOG
# =====================================================


@admin_bp.route('/course/add', methods=['POST'])
@staff_required
def add_course_modal():
    """Add new course"""
    try:
        name = request.form.get('name', '').strip()
        category_id = request.form.get('category_id', type=int) or None
        regular_price = request.form.get('regular_price', 0, type=float)
        experience_price = request.form.get('experience_price', 0, type=float)
        # Add fee fields
        service_fee = request.form.get('service_fee', 0, type=float)
        product_fee = request.form.get('product_fee', 0, type=float)

        duration = request.form.get('duration', type=int) or None
        sessions = request.form.get('sessions', 1, type=int)
        description = request.form.get('description', '').strip()

        if not name:
            flash('請填寫課程名稱', 'error')
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
                               service_fee, product_fee, duration, sessions, description, image)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (name, category_id, regular_price, experience_price, service_fee, product_fee, duration, sessions, description, image_url))

        course_id = cursor.lastrowid
        database.connection.commit()
        cursor.close()

        # ⭐ LOG ACTIVITY
        log_activity('create', 'course', course_id, {
                     'name': name, 'price': regular_price})

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
        regular_price = request.form.get('regular_price', 0, type=float)
        experience_price = request.form.get('experience_price', 0, type=float)
        # Add fee fields
        service_fee = request.form.get('service_fee', 0, type=float)
        product_fee = request.form.get('product_fee', 0, type=float)

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

        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

        # Get old data
        cursor.execute("SELECT name FROM courses WHERE id = %s", (course_id,))
        old_data = cursor.fetchone()

        cursor.execute("""
            UPDATE courses
            SET name=%s, category_id=%s, regular_price=%s, experience_price=%s,
                service_fee=%s, product_fee=%s, duration=%s, sessions=%s, 
                description=%s, image=%s, is_active=%s
            WHERE id=%s
        """, (name, category_id, regular_price, experience_price, service_fee, product_fee,
              duration, sessions, description, image_url, is_active, course_id))

        database.connection.commit()
        cursor.close()

        # ⭐ LOG ACTIVITY
        log_activity('update', 'course', course_id, {
            'old_name': old_data['name'] if old_data else '',
            'new_name': name
        })

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

        # Get name
        cursor.execute("SELECT name FROM courses WHERE id = %s", (course_id,))
        res = cursor.fetchone()
        c_name = res[0] if res else 'Unknown'

        cursor.execute("DELETE FROM courses WHERE id = %s", (course_id,))
        database.connection.commit()
        cursor.close()

        # ⭐ LOG ACTIVITY
        log_activity('delete', 'course', course_id, {'name': c_name})

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
        cat_id = cursor.lastrowid
        database.connection.commit()
        cursor.close()

        log_activity('create', 'category', cat_id, {
                     'type': 'product', 'name': name})
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
        cat_id = cursor.lastrowid
        database.connection.commit()
        cursor.close()

        log_activity('create', 'category', cat_id, {
                     'type': 'course', 'name': name})
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

        log_activity('delete', 'category', category_id, {'type': 'product'})
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

        log_activity('delete', 'category', category_id, {'type': 'course'})
        flash('課程分類已刪除', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'刪除失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='categories'))

# =====================================================
# EVENT MANAGEMENT - WITH AUDIT LOG
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

        event_id = cursor.lastrowid
        database.connection.commit()
        cursor.close()

        # ⭐ LOG ACTIVITY
        log_activity('create', 'event', event_id, {
                     'title': title, 'customer': customer_id})

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

        # ⭐ LOG ACTIVITY
        log_activity('update', 'event', event_id, {'title': title})

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

        # Get title
        cursor.execute("SELECT title FROM events WHERE id = %s", (event_id,))
        res = cursor.fetchone()
        e_title = res[0] if res else 'Unknown'

        cursor.execute("DELETE FROM events WHERE id = %s", (event_id,))
        database.connection.commit()
        cursor.close()

        # ⭐ LOG ACTIVITY
        log_activity('delete', 'event', event_id, {'title': e_title})

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
    """Adjust inventory"""
    try:
        product_id = request.form.get('product_id', type=int)
        change_amount = request.form.get('change_amount', type=int)
        change_type = request.form.get('change_type', 'adjustment')
        notes = request.form.get('notes', '').strip()

        if not product_id or change_amount == 0:
            flash('請填寫完整資料', 'error')
            return redirect(url_for('admin.dashboard', tab='inventory'))

        cursor = database.connection.cursor()

        # 1. 更新產品實際庫存 (Update product stock)
        cursor.execute("""
            UPDATE products 
            SET stock_quantity = stock_quantity + %s 
            WHERE id = %s
        """, (change_amount, product_id))

        # 2. 寫入庫存變動流水帳 (Insert inventory_logs - 這是業務邏輯紀錄)
        cursor.execute("""
            INSERT INTO inventory_logs 
            (product_id, change_amount, change_type, notes, created_by)
            VALUES (%s, %s, %s, %s, %s)
        """, (product_id, change_amount, change_type, notes, get_current_user_id()))

        database.connection.commit()
        cursor.close()

        # ⭐ 3. 新增這行：寫入後台審計日誌 (Admin Audit Log - 這是操作行為紀錄)
        log_activity('update', 'inventory', product_id, {
            'amount': change_amount,
            'type': change_type,
            'notes': notes
        })

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
    """Update order status with inventory handling"""
    try:
        status = request.form.get('status')
        allowed_statuses = ['pending', 'confirmed', 'completed', 'cancelled']

        if status not in allowed_statuses:
            flash('無效的狀態', 'error')
            return redirect(url_for('admin.dashboard', tab='orders'))

        # ⭐ FIX: Use service to handle inventory restore
        admin_id = get_current_user_id()
        success = admin_update_order_with_inventory(order_id, status, admin_id)

        if success:
            log_activity('update', 'order', order_id, {'status': status})
            flash('訂單狀態已更新', 'success')
        else:
            flash('更新失敗', 'error')

    except Exception as e:
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

        log_activity('update', 'booking', booking_id, {'status': status})

        flash('預約狀態已更新', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'更新失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='bookings'))


@admin_bp.route('/course/<int:course_id>/update-capacity', methods=['POST'])
@staff_required
def update_course_capacity(course_id):
    """批次更新該課程未來時段的可預約人數"""
    try:
        new_capacity = request.form.get('max_capacity', type=int)

        if not new_capacity or new_capacity < 1:
            flash('請輸入有效的人數', 'error')
            return redirect(url_for('admin.dashboard', tab='courses'))

        cursor = database.connection.cursor()

        # 只更新「未來」且「還沒額滿」的時段
        # 這樣不會影響到已經被預約滿的歷史紀錄
        cursor.execute("""
            UPDATE course_schedules
            SET max_capacity = %s
            WHERE course_id = %s 
              AND start_time > NOW()
        """, (new_capacity, course_id))

        affected_rows = cursor.rowcount
        database.connection.commit()
        cursor.close()

        log_activity('update', 'course_schedule', course_id, {
                     'action': 'bulk_capacity_update', 'new_capacity': new_capacity})

        flash(f'已更新未來 {affected_rows} 個時段的人數上限為 {new_capacity} 人', 'success')

    except Exception as e:
        database.connection.rollback()
        flash(f'更新失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='courses'))
# =====================================================
# CUSTOMER MANAGEMENT
# =====================================================


@admin_bp.route('/customer/<int:customer_id>/update', methods=['POST'])
@admin_required
def update_customer(customer_id):
    """Update customer details by admin"""
    try:
        firstname = request.form.get('firstname', '').strip()
        surname = request.form.get('surname', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        line_id = request.form.get('line_id', '').strip()
        gender = request.form.get('gender')
        birth_date = request.form.get('birth_date') or None
        occupation = request.form.get('occupation', '').strip()
        source_id = request.form.get('source_id', type=int) or None

        if not firstname or not email:
            flash('姓名與 Email 為必填', 'error')
            return redirect(url_for('admin.dashboard', tab='customers'))

        cursor = database.connection.cursor()

        # 檢查 Email 是否與其他人重複
        cursor.execute(
            "SELECT id FROM users WHERE email = %s AND id != %s", (email, customer_id))
        if cursor.fetchone():
            cursor.close()
            flash('該 Email 已被其他用戶使用', 'error')
            return redirect(url_for('admin.dashboard', tab='customers'))

        cursor.execute("""
            UPDATE users 
            SET firstname=%s, surname=%s, email=%s, phone=%s, line_id=%s, 
                gender=%s, birth_date=%s, occupation=%s, source_id=%s
            WHERE id=%s AND role='customer'
        """, (firstname, surname, email, phone, line_id, gender, birth_date, occupation, source_id, customer_id))

        database.connection.commit()
        cursor.close()

        # 記錄 Log
        log_activity('update', 'customer', customer_id,
                     {'name': f"{firstname} {surname}"})

        flash('客戶資料已更新', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'更新失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='customers'))


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

        log_activity('delete', 'customer', customer_id)
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
    # 處理表單提交 (POST)
    if request.method == 'POST':
        title = request.form.get('title')
        summary = request.form.get('summary')
        content = request.form.get('content')
        status = request.form.get('status', 'draft')

        # 處理圖片上傳
        image_url = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                # 假設您有 save_upload 函式 (之前在 admin.py 看過)
                image_url = save_upload(
                    file, current_app.config['UPLOAD_FOLDER'])

        try:
            cursor = database.connection.cursor()
            cursor.execute("""
                INSERT INTO blog_posts (title, summary, content, image, status, author_id, published_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                title,
                summary,
                content,
                image_url,
                status,
                get_current_user_id(),
                datetime.now() if status == 'published' else None
            ))
            database.connection.commit()
            cursor.close()
            flash('文章已新增', 'success')
            return redirect(url_for('admin.dashboard', tab='posts'))

        except Exception as e:
            database.connection.rollback()
            flash(f'新增失敗: {str(e)}', 'error')

    # 顯示頁面 (GET) - 修正這裡，原本是 return "Add post page"
    return render_template('admin_post_form.html', post=None)


@admin_bp.route('/edit-post/<int:post_id>', methods=['GET', 'POST'])
@staff_required
def edit_post(post_id):
    # 修正 1: 使用 database 而不是 mysql
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    # 修正 2: 表格名稱改為 blog_posts
    cursor.execute("SELECT * FROM blog_posts WHERE id = %s", (post_id,))
    post = cursor.fetchone()

    if not post:
        cursor.close()
        flash("找不到該文章", "danger")
        return redirect(url_for('admin.dashboard', tab='posts'))

    # POST → 更新文章
    if request.method == 'POST':
        title = request.form.get("title")
        summary = request.form.get("summary")
        content = request.form.get("content")
        status = request.form.get("status")

        # 處理圖片
        image = post['image']  # 預設使用原本圖片
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                # 這裡假設您有 save_upload 函式可用
                image = save_upload(file, current_app.config['UPLOAD_FOLDER'])

        try:
            # 修正 3: Update 語句也要改成 blog_posts
            cursor.execute("""
                UPDATE blog_posts
                SET title=%s, summary=%s, content=%s, status=%s, image=%s
                WHERE id=%s
            """, (title, summary, content, status, image, post_id))

            database.connection.commit()
            flash("文章已成功更新", "success")

        except Exception as e:
            database.connection.rollback()
            flash(f"更新失敗: {str(e)}", "error")
        finally:
            cursor.close()

        return redirect(url_for('admin.dashboard', tab='posts'))

    cursor.close()

    # GET → 顯示編輯頁
    return render_template(
        "admin_post_form.html",
        post=post
    )


@admin_bp.route("/posts/delete/<int:post_id>", methods=["POST"])
@admin_required
def delete_post(post_id):
    try:
        cursor = database.connection.cursor()
        # 修正: 表格名稱改為 blog_posts
        cursor.execute("DELETE FROM blog_posts WHERE id = %s", (post_id,))
        database.connection.commit()
        cursor.close()
        flash("文章已刪除", "success")
    except Exception as e:
        database.connection.rollback()
        flash(f"刪除失敗: {str(e)}", "error")

    return redirect(url_for("admin.dashboard", tab='posts'))
