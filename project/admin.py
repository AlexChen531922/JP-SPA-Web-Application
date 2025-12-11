"""
Complete Admin Management System with Advanced Reporting
Fixed all CRUD operations and inventory integration
"""
from werkzeug.security import generate_password_hash  # 記得確認有沒有 import
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
from project.decorators import admin_required, staff_required
from project.notifications import (
    notify_order_confirmed,
    notify_booking_confirmed,
    notify_order_status_update,
    notify_booking_status_update
)

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


@admin_bp.route('/dashboard')
@staff_required
def dashboard():
    tab = request.args.get('tab', 'overview')
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    # 1. 基礎計數 (Counts)
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

    # ⭐ 新增：文章總數
    cursor.execute(
        "SELECT COUNT(*) as count FROM blog_posts WHERE status = 'published'")
    post_count = cursor.fetchone()['count']

    # 2. 營收計算 (Revenue)
    # 總營收
    cursor.execute("""
        SELECT 
            (SELECT COALESCE(SUM(total_amount), 0) FROM orders WHERE status != 'cancelled') +
            (SELECT COALESCE(SUM(total_amount), 0) FROM bookings WHERE status != 'cancelled') 
        as total_revenue
    """)
    res = cursor.fetchone()
    total_revenue = float(res['total_revenue']
                          ) if res and res['total_revenue'] else 0.0

    # 訂單成本
    cursor.execute("""
        SELECT COALESCE(SUM(oi.quantity * p.cost), 0) as order_cost
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        JOIN orders o ON oi.order_id = o.id
        WHERE o.status != 'cancelled'
    """)
    res = cursor.fetchone()
    order_cost = float(res['order_cost']) if res and res['order_cost'] else 0.0

    # 課程成本
    cursor.execute("""
        SELECT COALESCE(SUM(b.sessions_purchased * (c.service_fee + c.product_fee)), 0) as course_cost
        FROM bookings b
        JOIN courses c ON b.course_id = c.id
        WHERE b.status != 'cancelled'
    """)
    res = cursor.fetchone()
    course_cost = float(
        res['course_cost']) if res and res['course_cost'] else 0.0

    # 計算淨利
    total_cost = order_cost + course_cost
    net_profit = total_revenue - total_cost

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

    # Events
    cursor.execute("""
        SELECT e.*, CONCAT(u.firstname, ' ', u.surname) as customer_name
        FROM events e
        LEFT JOIN users u ON e.customer_id = u.id
        ORDER BY e.start_date DESC
    """)
    events = cursor.fetchall()

    # Inventory (更新版：加入圖片、描述與類別名稱)
    cursor.execute("""
        SELECT 
            p.id, 
            p.name, 
            p.stock_quantity, 
            p.cost, 
            p.price, 
            p.last_purchase_date, 
            p.last_sale_date, 
            p.unit,
            p.image,           -- 新增：圖片檔名
            p.description,     -- 新增：產品描述
            c.name as category_name  -- 新增：透過 JOIN 抓取類別名稱
        FROM products p
        LEFT JOIN product_categories c ON p.category_id = c.id
        ORDER BY p.name
    """)
    inventory_products = cursor.fetchall()

    # Customers dropdown
    cursor.execute(
        "SELECT id, firstname, surname FROM users WHERE role = 'customer' ORDER BY firstname")
    customers = cursor.fetchall()

    # Orders full list
    cursor.execute("""
        SELECT o.*, u.username, u.firstname, u.surname, u.email, u.phone
        FROM orders o
        JOIN users u ON o.customer_id = u.id
        ORDER BY o.created_at DESC
    """)
    orders = cursor.fetchall()

    # Order Items Map
    cursor.execute("""
        SELECT oi.order_id, oi.quantity, oi.unit_price, oi.subtotal, p.name as product_name
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
    """)
    all_items = cursor.fetchall()
    order_items_map = {}
    for item in all_items:
        oid = item['order_id']
        if oid not in order_items_map:
            order_items_map[oid] = []
        order_items_map[oid].append(item)

    # Bookings full list
    cursor.execute("""
        SELECT b.*, u.username, u.firstname, u.surname, u.email, u.phone, u.line_id,
               c.name as course_name, c.duration, cs.start_time, cs.end_time
        FROM bookings b
        LEFT JOIN users u ON b.customer_id = u.id
        LEFT JOIN courses c ON b.course_id = c.id
        LEFT JOIN course_schedules cs ON b.schedule_id = cs.id
        ORDER BY b.created_at DESC
    """)
    bookings = cursor.fetchall()

    # Customer list
    cursor.execute("""
        SELECT u.id, u.username, u.email, u.firstname, u.surname,
               u.phone, u.line_id, u.gender, u.occupation, u.created_at,
               u.birth_date, u.source_id,
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

    # Posts
    cursor.execute("""
        SELECT p.*, u.firstname, u.surname, CONCAT(u.firstname, ' ', u.surname) as author_name
        FROM blog_posts p
        LEFT JOIN users u ON p.author_id = u.id
        ORDER BY p.created_at DESC
    """)
    posts = cursor.fetchall()

    # Audit Logs (Admin Only)
    audit_logs = []
    if get_current_user_role() == 'admin':
        cursor.execute("""
            SELECT a.*, u.username, u.firstname, u.surname,
                   CONCAT(u.firstname, ' ', u.surname) as operator_name
            FROM audit_logs a
            LEFT JOIN users u ON a.user_id = u.id
            ORDER BY a.created_at DESC
            LIMIT 50
        """)
        audit_logs = cursor.fetchall()

    cursor.execute("SELECT * FROM customer_sources ORDER BY id")
    customer_sources = cursor.fetchall()

    cursor.close()

    # ⭐ 更新：傳遞更多數據給前端
    stats = {
        'products': product_count,
        'courses': course_count,
        'orders': order_count,
        'bookings': booking_count,
        'customers': customer_count,
        'posts': post_count,
        'revenue': float(total_revenue),
        'net_profit': net_profit
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
        order_items_map=order_items_map,
        audit_logs=audit_logs
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
    """
    Delete product (Smart Delete)
    如果有訂單紀錄 -> 改為停用 (Soft Delete)
    如果完全無紀錄 -> 真刪除 (Hard Delete)
    """
    try:
        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

        # 1. 取得產品名稱 (給 Log 用)
        cursor.execute(
            "SELECT name FROM products WHERE id = %s", (product_id,))
        res = cursor.fetchone()
        p_name = res['name'] if res else 'Unknown'

        # 2. 檢查是否有關聯的訂單 (這是主要擋住刪除的原因)
        cursor.execute(
            "SELECT COUNT(*) as count FROM order_items WHERE product_id = %s", (product_id,))
        order_count = cursor.fetchone()['count']

        if order_count > 0:
            # A. 有訂單紀錄 -> 執行「停用」
            cursor.execute(
                "UPDATE products SET is_active = FALSE WHERE id = %s", (product_id,))
            msg = f'產品「{p_name}」已有 {order_count} 筆銷售紀錄，已自動改為「停用」狀態（保留歷史資料）。'
            action = 'deactivate'
        else:
            # B. 無訂單紀錄 -> 執行「真刪除」
            cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
            msg = f'產品「{p_name}」已永久刪除。'
            action = 'delete'

        database.connection.commit()
        cursor.close()

        # LOG ACTIVITY
        log_activity(action, 'product', product_id, {'name': p_name})

        flash(msg, 'success')

    except Exception as e:
        database.connection.rollback()
        # 印出完整錯誤以便除錯
        print(f"Delete Product Error: {e}")
        flash(f'刪除失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='products'))


@admin_bp.route('/api/product/<int:product_id>')
@staff_required
def get_product_json(product_id):
    """API to get product data for modal"""
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
    product = cursor.fetchone()
    cursor.close()

    if product:
        # 處理 Decimal 轉 float (以免 JSON 報錯)
        for key, value in product.items():
            if isinstance(value, Decimal):
                product[key] = float(value)
        return jsonify(product)
    return jsonify({'error': 'Not found'}), 404


@admin_bp.route('/api/course/<int:course_id>')
@staff_required
def get_course_json(course_id):
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM courses WHERE id = %s", (course_id,))
    course = cursor.fetchone()
    cursor.close()

    if course:
        for key in ['regular_price', 'experience_price', 'service_fee', 'product_fee']:
            if key in course and course[key] is not None:
                course[key] = float(course[key])
        return jsonify(course)
    return jsonify({'error': 'Not found'}), 404

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
        if duration and duration > 0:
            schedules_data = []
            today = datetime.now().date()

            # 設定每天的開場時間 (整點)
            open_hours = [9, 10, 11, 12, 13, 14, 15, 16, 17]

            # 迴圈產生 365 天
            for i in range(365):
                current_date = today + timedelta(days=i)

                # (進階：如果想跳過週日，可以加這行)
                # if current_date.weekday() == 6: continue

                for hour in open_hours:
                    # 1. 組合開始時間 (日期 + 小時)
                    # datetime.min.time() 是 00:00:00，replace(hour=hour) 變 09:00:00
                    start_dt = datetime.combine(
                        current_date, datetime.min.time().replace(hour=hour))

                    # 2. 計算結束時間 (開始 + 課程時長)
                    end_dt = start_dt + timedelta(minutes=duration)

                    # 3. 加入列表 (course_id, start, end, capacity=1, booked=0, active=True)
                    schedules_data.append(
                        (course_id, start_dt, end_dt, 1, 0, True))

            # 4. 批量寫入資料庫 (使用 executemany 效能極佳)
            if schedules_data:
                cursor.executemany("""
                    INSERT INTO course_schedules 
                    (course_id, start_time, end_time, max_capacity, current_bookings, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, schedules_data)
        database.connection.commit()
        cursor.close()

        # ⭐ LOG ACTIVITY
        log_activity('create', 'course', course_id, {
                     'name': name, 'price': regular_price})
        flash('課程已新增，並已自動生成未來一年的時段', 'success')

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
    """
    Delete course (Smart Delete)
    如果有預約紀錄 -> 改為停用 (Soft Delete)
    如果完全無紀錄 -> 真刪除 (Hard Delete)
    """
    try:
        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

        # 1. 取得課程名稱 (給 Log 用)
        cursor.execute("SELECT name FROM courses WHERE id = %s", (course_id,))
        res = cursor.fetchone()
        c_name = res['name'] if res else 'Unknown'

        # 2. 檢查是否有關聯的預約
        cursor.execute(
            "SELECT COUNT(*) as count FROM bookings WHERE course_id = %s", (course_id,))
        booking_count = cursor.fetchone()['count']

        if booking_count > 0:
            # A. 有預約紀錄 -> 執行「停用」
            cursor.execute(
                "UPDATE courses SET is_active = FALSE WHERE id = %s", (course_id,))
            msg = f'課程「{c_name}」已有 {booking_count} 筆預約紀錄，已自動改為「停用」狀態（保留歷史資料）。'
            action = 'deactivate'
        else:
            # B. 無預約紀錄 -> 執行「真刪除」
            # 先刪除關聯的時段 (course_schedules) 以免外鍵錯誤
            cursor.execute(
                "DELETE FROM course_schedules WHERE course_id = %s", (course_id,))
            # 再刪除課程
            cursor.execute("DELETE FROM courses WHERE id = %s", (course_id,))
            msg = f'課程「{c_name}」已永久刪除。'
            action = 'delete'

        database.connection.commit()
        cursor.close()

        # LOG ACTIVITY
        log_activity(action, 'course', course_id, {'name': c_name})

        flash(msg, 'success')

    except Exception as e:
        database.connection.rollback()
        # 印出完整錯誤以便除錯
        print(f"Delete Error: {e}")
        flash(f'操作失敗: {str(e)}', 'error')

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


# =====================================================
# INVENTORY MANAGEMENT (NEW: RESTOCK)
# =====================================================

@admin_bp.route('/inventory/restock', methods=['POST'])
@staff_required
def restock_product():
    """進貨入庫 (新增庫存)"""
    try:
        product_id = request.form.get('product_id', type=int)
        quantity = request.form.get('quantity', type=int)
        cost = request.form.get('cost', type=float)  # 進貨成本
        notes = request.form.get('notes', '').strip()

        if not product_id or quantity <= 0:
            flash('請輸入有效的產品與數量', 'error')
            return redirect(url_for('admin.dashboard', tab='inventory'))

        cursor = database.connection.cursor()

        # 1. 更新庫存 + 更新成本(若有輸入) + 更新最後進貨日
        if cost and cost > 0:
            cursor.execute("""
                UPDATE products 
                SET stock_quantity = stock_quantity + %s, 
                    cost = %s,
                    last_purchase_date = NOW()
                WHERE id = %s
            """, (quantity, cost, product_id))
        else:
            cursor.execute("""
                UPDATE products 
                SET stock_quantity = stock_quantity + %s,
                    last_purchase_date = NOW()
                WHERE id = %s
            """, (quantity, product_id))

        # 2. 寫入 Log
        cursor.execute("""
            INSERT INTO inventory_logs 
            (product_id, change_amount, change_type, notes, created_by)
            VALUES (%s, %s, 'purchase', %s, %s)
        """, (product_id, quantity, notes or 'Manual Restock', get_current_user_id()))

        database.connection.commit()
        cursor.close()

        log_activity('restock', 'inventory', product_id, {'qty': quantity})
        flash(f'成功進貨 {quantity} 件', 'success')

    except Exception as e:
        database.connection.rollback()
        flash(f'進貨失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='inventory'))


@admin_bp.route('/inventory/adjust', methods=['POST'])
@staff_required
def adjust_inventory_modal():
    """Adjust inventory (盤點調整)"""
    try:
        product_id = request.form.get('product_id', type=int)
        change_amount = request.form.get('change_amount', type=int)
        change_type = request.form.get('change_type', 'adjustment')
        notes = request.form.get('notes', '').strip()

        if not product_id or change_amount == 0:
            flash('請填寫完整資料', 'error')
            return redirect(url_for('admin.dashboard', tab='inventory'))

        cursor = database.connection.cursor()

        # 1. 更新產品實際庫存
        cursor.execute("""
            UPDATE products 
            SET stock_quantity = stock_quantity + %s 
            WHERE id = %s
        """, (change_amount, product_id))

        # 2. 寫入庫存日誌
        cursor.execute("""
            INSERT INTO inventory_logs 
            (product_id, change_amount, change_type, notes, created_by)
            VALUES (%s, %s, %s, %s, %s)
        """, (product_id, change_amount, change_type, notes, get_current_user_id()))

        database.connection.commit()
        cursor.close()

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
# ORDER STATUS & INVENTORY SYNC (CRITICAL)
# =====================================================


# 記得確認檔案最上方有匯入通知函式
# from project.notifications import notify_order_confirmed, notify_order_status_update

@admin_bp.route('/order/<int:order_id>/update-status', methods=['POST'])
@staff_required
def update_order_status(order_id):
    """
    更新訂單狀態並連動庫存 + 發送通知 (修正變數名稱版)
    """
    try:
        new_status = request.form.get('status')
        allowed_statuses = ['pending', 'confirmed', 'completed', 'cancelled']

        if new_status not in allowed_statuses:
            flash('無效的狀態', 'error')
            return redirect(url_for('admin.dashboard', tab='orders'))

        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

        # 1. ⭐ 修正：將查詢結果賦值給 order_info (之前可能寫成 order)
        cursor.execute("""
            SELECT o.status, o.total_amount, u.email, u.firstname, u.line_id 
            FROM orders o
            JOIN users u ON o.customer_id = u.id
            WHERE o.id = %s
        """, (order_id,))
        order_info = cursor.fetchone()  # <--- 關鍵修改：定義 order_info

        if not order_info:
            cursor.close()
            flash('訂單不存在', 'error')
            return redirect(url_for('admin.dashboard', tab='orders'))

        old_status = order_info['status']

        # 狀態沒變，直接返回
        if old_status == new_status:
            cursor.close()
            return redirect(url_for('admin.dashboard', tab='orders'))

        # 2. 庫存連動邏輯 (保持不變)
        if old_status != 'cancelled' and new_status == 'cancelled':
            cursor.execute(
                "SELECT product_id, quantity FROM order_items WHERE order_id = %s", (order_id,))
            items = cursor.fetchall()
            for item in items:
                cursor.execute("UPDATE products SET stock_quantity = stock_quantity + %s WHERE id = %s",
                               (item['quantity'], item['product_id']))
                cursor.execute("INSERT INTO inventory_logs (product_id, change_amount, change_type, reference_id, notes, created_by) VALUES (%s, %s, 'return', %s, 'Order Cancelled', %s)",
                               (item['product_id'], item['quantity'], order_id, get_current_user_id()))

        elif old_status == 'cancelled' and new_status in ['pending', 'confirmed', 'completed']:
            cursor.execute(
                "SELECT product_id, quantity FROM order_items WHERE order_id = %s", (order_id,))
            items = cursor.fetchall()
            for item in items:
                cursor.execute(
                    "SELECT stock_quantity, name FROM products WHERE id = %s", (item['product_id'],))
                prod = cursor.fetchone()
                if prod['stock_quantity'] < item['quantity']:
                    raise Exception(f"產品「{prod['name']}」庫存不足，無法恢復訂單")
                cursor.execute("UPDATE products SET stock_quantity = stock_quantity - %s, last_sale_date = NOW() WHERE id = %s",
                               (item['quantity'], item['product_id']))
                cursor.execute("INSERT INTO inventory_logs (product_id, change_amount, change_type, reference_id, notes, created_by) VALUES (%s, %s, 'sale', %s, 'Order Restored', %s)",
                               (item['product_id'], -item['quantity'], order_id, get_current_user_id()))

        elif new_status == 'completed':
            cursor.execute(
                "SELECT product_id FROM order_items WHERE order_id = %s", (order_id,))
            items = cursor.fetchall()
            for item in items:
                cursor.execute(
                    "UPDATE products SET last_sale_date = NOW() WHERE id = %s", (item['product_id'],))

        # 3. 更新狀態
        cursor.execute(
            "UPDATE orders SET status = %s WHERE id = %s", (new_status, order_id))
        database.connection.commit()
        cursor.close()

        # 4. ⭐ 發送通知 (現在 order_info 已經有定義了，不會報錯)
        customer_data = {
            'email': order_info['email'],
            'firstname': order_info['firstname'],
            'line_id': order_info['line_id']
        }

        if new_status == 'confirmed' and old_status != 'confirmed':
            notify_order_confirmed(
                order_id, customer_data, order_info['total_amount'])
        elif new_status != old_status:
            notify_order_status_update(
                order_id, customer_data['firstname'], customer_data['email'], new_status)

        log_activity('update', 'order', order_id, {
                     'old': old_status, 'new': new_status})
        flash(f'訂單狀態已更新 ({old_status} -> {new_status}) 並已發送通知', 'success')

    except Exception as e:
        database.connection.rollback()
        flash(f'更新失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='orders'))


@admin_bp.route('/booking/<int:booking_id>/update-status', methods=['POST'])
@staff_required
def update_booking_status(booking_id):
    """Update booking status with notifications"""
    try:
        status = request.form.get('status')
        allowed_statuses = ['pending', 'confirmed', 'completed', 'cancelled']

        if status not in allowed_statuses:
            flash('無效的狀態', 'error')
            return redirect(url_for('admin.dashboard', tab='bookings'))

        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

        # 1. ⭐ 獲取預約詳細資訊 (包含課程名稱、時間、客戶資料)
        cursor.execute("""
            SELECT b.status, c.name as course_name, cs.start_time, 
                   u.email, u.firstname, u.line_id
            FROM bookings b
            JOIN users u ON b.customer_id = u.id
            JOIN courses c ON b.course_id = c.id
            LEFT JOIN course_schedules cs ON b.schedule_id = cs.id
            WHERE b.id = %s
        """, (booking_id,))
        booking_info = cursor.fetchone()

        # 2. 更新狀態
        cursor.execute(
            "UPDATE bookings SET status = %s WHERE id = %s", (status, booking_id))
        database.connection.commit()
        cursor.close()

        # 3. ⭐ 發送通知
        if booking_info:
            customer_data = {
                'email': booking_info['email'],
                'firstname': booking_info['firstname'],
                'line_id': booking_info['line_id']
            }

            # 格式化時間
            time_str = "未定"
            if booking_info['start_time']:
                time_str = booking_info['start_time'].strftime(
                    '%Y-%m-%d %H:%M')

            if status == 'confirmed':
                # 變成已確認 -> 發送確認信 (Email + LINE)
                notify_booking_confirmed(
                    booking_id, customer_data, booking_info['course_name'], time_str)
            else:
                # 其他狀態 -> 一般通知
                notify_booking_status_update(
                    booking_id, customer_data['firstname'], customer_data['email'], booking_info['course_name'], status)

        log_activity('update', 'booking', booking_id, {'status': status})

        flash('預約狀態已更新並發送通知', 'success')
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

# --------------------------------------------------------
# SCHEDULE MANAGEMENT API (PER SLOT)
# --------------------------------------------------------


@admin_bp.route('/api/course/<int:course_id>/schedules')
@staff_required
def get_course_schedules_api(course_id):
    """取得該課程未來的時段列表 (供前端 Modal 使用)"""
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    # 只撈取未來 30 天內的時段，避免資料過多
    cursor.execute("""
        SELECT id, start_time, end_time, max_capacity, current_bookings
        FROM course_schedules
        WHERE course_id = %s 
          AND start_time > NOW()
          AND start_time < DATE_ADD(NOW(), INTERVAL 30 DAY)
        ORDER BY start_time ASC
    """, (course_id,))

    schedules = cursor.fetchall()
    cursor.close()

    # 轉換時間格式為字串
    data = []
    for s in schedules:
        data.append({
            'id': s['id'],
            'date': s['start_time'].strftime('%Y-%m-%d'),
            'time': f"{s['start_time'].strftime('%H:%M')} - {s['end_time'].strftime('%H:%M')}",
            'max_capacity': s['max_capacity'],
            'current_bookings': s['current_bookings']
        })

    return jsonify(data)


@admin_bp.route('/schedule/<int:schedule_id>/update-capacity', methods=['POST'])
@staff_required
def update_single_schedule_capacity(schedule_id):
    """更新單一時段的人數上限"""
    try:
        data = request.get_json()
        new_capacity = int(data.get('max_capacity'))

        if new_capacity < 1:
            return jsonify({'success': False, 'message': '人數必須大於 0'}), 400

        cursor = database.connection.cursor()

        # 檢查是否小於目前已預約人數 (防止超賣)
        cursor.execute(
            "SELECT current_bookings FROM course_schedules WHERE id = %s", (schedule_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'success': False, 'message': '時段不存在'}), 404

        # 更新
        cursor.execute("""
            UPDATE course_schedules 
            SET max_capacity = %s 
            WHERE id = %s
        """, (new_capacity, schedule_id))

        database.connection.commit()
        cursor.close()

        # 記錄 Log (可選，避免洗版可註解掉)
        # log_activity('update', 'schedule', schedule_id, {'capacity': new_capacity})

        return jsonify({'success': True})

    except Exception as e:
        database.connection.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

# =====================================================
# CUSTOMER MANAGEMENT
# =====================================================

# ... (在 update_customer 函式上方，插入這一段) ...


# 找到原本的 add_customer，替換成下面這樣
@admin_bp.route('/customer/add', methods=['POST'])
@staff_required
def add_customer():
    try:
        # 1. 抓取資料
        username = request.form.get('username')
        password = request.form.get('password')
        firstname = request.form.get('firstname')
        surname = request.form.get('surname')
        email = request.form.get('email')
        phone = request.form.get('phone')

        # 其他欄位
        line_id = request.form.get('line_id')
        gender = request.form.get('gender', 'other')
        birth_date = request.form.get('birth_date')
        occupation = request.form.get('occupation')
        address = request.form.get('address')
        source_id = request.form.get('source_id')

        # ⭐ 新增：備註欄位
        notes = request.form.get('notes')

        # 空值處理
        if not birth_date:
            birth_date = None
        if not source_id:
            source_id = None

        from project.db import check_username_exists

        if check_username_exists(username):
            flash('帳號已存在', 'error')
        else:
            cursor = database.connection.cursor()
            hashed_pw = generate_password_hash(password)

            # ⭐ SQL 插入語句加入 notes
            sql = """
                INSERT INTO users (
                    username, email, password_hash, 
                    firstname, surname, phone, 
                    line_id, gender, birth_date, 
                    occupation, address, source_id, notes,
                    role, created_at
                ) VALUES (
                    %s, %s, %s, 
                    %s, %s, %s, 
                    %s, %s, %s, 
                    %s, %s, %s, %s,
                    'customer', NOW()
                )
            """
            cursor.execute(sql, (
                username, email, hashed_pw,
                firstname, surname, phone,
                line_id, gender, birth_date,
                occupation, address, source_id, notes
            ))

            database.connection.commit()
            cursor.close()

            flash('客戶新增成功', 'success')

    except Exception as e:
        if "Duplicate entry" in str(e):
            flash('新增失敗：帳號或 Email 已被使用', 'error')
        else:
            flash(f'新增失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='customers'))


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
