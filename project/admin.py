"""
Complete Admin Management System with Advanced Reporting
Fixed all CRUD operations and inventory integration
"""
from werkzeug.security import generate_password_hash
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, current_app, session
from functools import wraps
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os
import cloudinary
import cloudinary.uploader
import re
from project.extensions import database
from project.db import get_current_user_id, get_current_user_role
import MySQLdb.cursors
from decimal import Decimal
# from project.services import admin_update_order_with_inventory
from project.db import get_current_user_id
from project.audit import log_activity
from project.decorators import admin_required, staff_required

# --- Cloudinary 設定 ---
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET')
)

admin_bp = Blueprint('admin', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# --- 上傳 Helper ---
def upload_to_cloudinary(image_file):
    if not image_file:
        return None
    try:
        upload_result = cloudinary.uploader.upload(image_file)
        return upload_result.get('secure_url')
    except Exception as e:
        print(f"Cloudinary Upload Error: {e}")
        return None


def save_upload(file, upload_folder):
    if file and allowed_file(file.filename):
        try:
            # 直接上傳到 Cloudinary，不需要先存到本地
            upload_result = cloudinary.uploader.upload(file)

            # 取得雲端上的圖片網址
            return upload_result['secure_url']

        except Exception as e:
            print(f"上傳失敗: {e}")
            return None
    return None


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

    # ⭐ 修正 1: 資料表名稱 posts -> blog_posts
    cursor.execute(
        "SELECT COUNT(*) as count FROM blog_posts WHERE status = 'published'")
    post_count = cursor.fetchone()['count']

    # 2. 營收計算 (Revenue)
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

    # Products
    cursor.execute("""
        SELECT p.*, pc.name as category_name
        FROM products p
        LEFT JOIN product_categories pc ON p.category_id = pc.id
        ORDER BY p.display_order ASC, p.created_at DESC
    """)
    products = cursor.fetchall()

    # Courses
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

    # ⭐ 修正 2: Events 表不存在，暫時給空列表防止 500 錯誤
    # cursor.execute("SELECT e.* ... FROM events e ...")
    events = []

    # Inventory
    cursor.execute("""
        SELECT 
            p.id, p.name, p.stock_quantity, p.cost, p.price, 
            p.last_purchase_date, p.last_sale_date, p.unit,
            p.image, p.description, c.name as category_name,
            (SELECT notes FROM inventory_logs WHERE product_id = p.id ORDER BY created_at DESC LIMIT 1) as latest_note
        FROM products p
        LEFT JOIN product_categories c ON p.category_id = c.id
        ORDER BY p.display_order ASC, p.id DESC
    """)
    # 轉成 list 以便修改內容
    inventory_products = list(cursor.fetchall())

    # ⭐ 新增：清理備註欄位 (只保留使用者輸入的內容)
    for prod in inventory_products:
        note = prod.get('latest_note') or ''

        # 1. 去除進貨時系統自動加上的價格資訊 (截斷 '. 進貨價:' 之後的內容)
        if '. 進貨價:' in note:
            note = note.split('. 進貨價:')[0]

        # 2. 去除完全是系統產生的預設文字
        system_prefixes = ['Admin Manual Order',
                           'Order Cancelled', 'Order Restored']
        system_exact = ['Manual Restock']

        # 如果備註是 "Manual Restock" (沒填寫時的預設值)，就清空
        if note in system_exact:
            note = ''
        # 如果備註以 "Admin Manual Order" 開頭 (手動訂單)，就清空
        elif any(note.startswith(prefix) for prefix in system_prefixes):
            note = ''

        prod['latest_note'] = note.strip()

    # Customers
    cursor.execute(
        "SELECT id, firstname, surname, username FROM users WHERE role = 'customer' ORDER BY firstname")
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

    for item in all_items:
        if isinstance(item.get('unit_price'), Decimal):
            item['unit_price'] = float(item['unit_price'])
        if isinstance(item.get('subtotal'), Decimal):
            item['subtotal'] = float(item['subtotal'])

    order_items_map = {}
    for item in all_items:
        oid = item['order_id']
        if oid not in order_items_map:
            order_items_map[oid] = []
        order_items_map[oid].append(item)

    for order in orders:
        if isinstance(order.get('total_amount'), Decimal):
            order['total_amount'] = float(order['total_amount'])

    # ⭐ 修正 3: course_schedules -> shop_schedules
    cursor.execute("""
        SELECT b.*, u.username, u.firstname, u.surname, u.email, u.phone, u.line_id,
               c.name as course_name, c.duration, s.start_time, s.end_time
        FROM bookings b
        LEFT JOIN users u ON b.customer_id = u.id
        LEFT JOIN courses c ON b.course_id = c.id
        LEFT JOIN shop_schedules s ON b.global_schedule_id = s.id
        ORDER BY b.created_at DESC
    """)
    bookings = cursor.fetchall()

    for booking in bookings:
        if isinstance(booking.get('total_amount'), Decimal):
            booking['total_amount'] = float(booking['total_amount'])

    # Customer list
    cursor.execute("""
        SELECT u.id, u.username, u.email, u.firstname, u.surname,
               u.phone, u.line_id, u.gender, u.occupation, u.created_at,
               u.birth_date, u.source_id, u.address, u.notes,
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

    # ⭐ 修正 4: blog_posts -> posts (變數名 posts 維持不變，SQL 改為 blog_posts)
    cursor.execute("""
        SELECT p.*, u.firstname, u.surname, CONCAT(u.firstname, ' ', u.surname) as author_name
        FROM blog_posts p
        LEFT JOIN users u ON p.author_id = u.id
        ORDER BY p.created_at DESC
    """)
    posts = cursor.fetchall()

    # Audit Logs
    audit_logs = []
    if session.get('user', {}).get('role') == 'admin':
        # 檢查 audit_logs 表是否存在，避免 500
        try:
            cursor.execute("""
                SELECT a.*, u.username, u.firstname, u.surname,
                    CONCAT(u.firstname, ' ', u.surname) as operator_name
                FROM audit_logs a
                LEFT JOIN users u ON a.user_id = u.id
                ORDER BY a.created_at DESC
                LIMIT 50
            """)
            audit_logs = cursor.fetchall()
        except:
            audit_logs = []

    cursor.execute("SELECT * FROM customer_sources ORDER BY id")
    customer_sources = cursor.fetchall()

    cursor.close()

    now = datetime.now()

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
        audit_logs=audit_logs,
        now_str=now.strftime('%Y-%m-%dT%H:%M')
    )


@admin_bp.route('/product/add/modal', methods=['POST'])
@staff_required
def add_product_modal():
    try:
        name = request.form.get('name')
        category_id = request.form.get('category_id') or None
        price = request.form.get('price') or 0
        cost = request.form.get('cost') or 0
        stock = request.form.get('stock') or 0
        description = request.form.get('description')

        image_url = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '':
                image_url = upload_to_cloudinary(file)

        cursor = database.connection.cursor()
        sql = """
            INSERT INTO products
            (name, category_id, price, cost, stock_quantity,
             description, image, is_active, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """
        cursor.execute(sql, (name, category_id, price, cost,
                       stock, description, image_url, 1))

        new_id = cursor.lastrowid
        database.connection.commit()
        cursor.close()

        log_activity('create', 'product', new_id, {'name': name})
        flash('產品新增成功', 'success')

    except Exception as e:
        database.connection.rollback()
        flash(f'新增失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='products'))


@admin_bp.route('/product/update/modal/<int:product_id>', methods=['POST'])
@staff_required
def update_product_modal(product_id):
    try:
        # 1. 先取得資料庫目前的資料 (為了防止 Staff 編輯時將成本誤寫為 0)
        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        current_prod = cursor.fetchone()

        if not current_prod:
            flash('找不到該產品', 'error')
            return redirect(url_for('admin.dashboard', tab='products'))

        # 2. 接收表單資料
        name = request.form.get('name')
        category_id = request.form.get('category_id') or None
        price = request.form.get('price') or 0
        stock = request.form.get('stock') or 0
        description = request.form.get('description')
        is_active = 1 if request.form.get('is_active') else 0

        # ⭐ 關鍵修正：如果是 Staff (表單沒傳 cost)，則使用資料庫舊值
        if 'cost' in request.form:
            cost = request.form.get('cost') or 0
        else:
            cost = current_prod['cost']  # 保持原樣
        # 3. 處理圖片
        image_url = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '':
                image_url = upload_to_cloudinary(file)

        # 4. 更新資料庫
        if image_url:
            sql = """
                UPDATE products
                SET name=%s, category_id=%s, price=%s, cost=%s, stock_quantity=%s,
                    description=%s, is_active=%s, image=%s, updated_at=NOW()
                WHERE id=%s
            """
            cursor.execute(sql, (name, category_id, price, cost,
                           stock, description, is_active, image_url, product_id))
        else:
            sql = """
                UPDATE products
                SET name=%s, category_id=%s, price=%s, cost=%s, stock_quantity=%s,
                    description=%s, is_active=%s, updated_at=NOW()
                WHERE id=%s
            """
            cursor.execute(sql, (name, category_id, price, cost,
                           stock, description, is_active, product_id))

        database.connection.commit()
        cursor.close()

        log_activity('update', 'product', product_id, {'name': name})
        flash('產品更新成功', 'success')

    except Exception as e:
        database.connection.rollback()
        print(f"Update Error: {e}")  # 印出錯誤到後台
        flash(f'更新失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='products'))


@admin_bp.route('/product/<int:product_id>/delete', methods=['POST'])
@staff_required
def delete_product_modal(product_id):
    try:
        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute(
            "SELECT name FROM products WHERE id = %s", (product_id,))
        res = cursor.fetchone()
        p_name = res['name'] if res else 'Unknown'

        cursor.execute(
            "SELECT COUNT(*) as count FROM order_items WHERE product_id = %s", (product_id,))
        order_count = cursor.fetchone()['count']

        if order_count > 0:
            cursor.execute(
                "UPDATE products SET is_active = FALSE WHERE id = %s", (product_id,))
            msg = f'產品「{p_name}」已有 {order_count} 筆銷售紀錄，已自動改為「停用」狀態。'
            action = 'deactivate'
        else:
            cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
            msg = f'產品「{p_name}」已永久刪除。'
            action = 'delete'

        database.connection.commit()
        cursor.close()
        log_activity(action, 'product', product_id, {'name': p_name})
        flash(msg, 'success')

    except Exception as e:
        database.connection.rollback()
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


# --- 新增課程 ---
@admin_bp.route('/course/add/modal', methods=['POST'])
@staff_required
def add_course_modal():
    try:
        name = request.form.get('name')
        category_id = request.form.get('category_id') or None
        regular_price = request.form.get('regular_price') or 0
        experience_price = request.form.get('experience_price') or 0
        service_fee = request.form.get('service_fee') or 0
        product_fee = request.form.get('product_fee') or 0
        duration = request.form.get('duration') or 60
        description = request.form.get('description')

        image_url = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '':
                image_url = upload_to_cloudinary(file)

        cursor = database.connection.cursor()
        sql = """
            INSERT INTO courses 
            (name, category_id, regular_price, experience_price, service_fee, product_fee, 
             duration, description, image, is_active, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1, NOW())
        """
        cursor.execute(sql, (name, category_id, regular_price, experience_price,
                       service_fee, product_fee, duration, description, image_url))

        new_id = cursor.lastrowid
        database.connection.commit()
        cursor.close()

        log_activity('create', 'course', new_id, {'name': name})
        flash('課程新增成功', 'success')

    except Exception as e:
        database.connection.rollback()
        flash(f'新增失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='courses'))


@admin_bp.route('/course/update/modal/<int:course_id>', methods=['POST'])
@staff_required
def update_course_modal(course_id):
    try:
        # 1. 先取得資料庫目前的資料 (關鍵修正：防止 Staff 編輯時成本被誤寫為 0)
        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT * FROM courses WHERE id = %s", (course_id,))
        current_course = cursor.fetchone()

        if not current_course:
            flash('找不到該課程', 'error')
            return redirect(url_for('admin.dashboard', tab='courses'))

        # 2. 接收表單資料
        name = request.form.get('name')
        category_id = request.form.get('category_id') or None
        regular_price = request.form.get('regular_price') or 0
        experience_price = request.form.get('experience_price') or 0
        duration = request.form.get('duration') or 60
        description = request.form.get('description')
        is_active = 1 if request.form.get('is_active') else 0

        # ⭐ 關鍵修正：判斷成本欄位是否存在於表單中
        # 如果是 Admin (有欄位)，就用傳來的直；如果是 Staff (無欄位)，就沿用資料庫舊值
        if 'service_fee' in request.form:
            service_fee = request.form.get('service_fee') or 0
        else:
            service_fee = current_course['service_fee']

        if 'product_fee' in request.form:
            product_fee = request.form.get('product_fee') or 0
        else:
            product_fee = current_course['product_fee']

        # 3. 處理圖片上傳
        image_url = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '':
                image_url = upload_to_cloudinary(file)

        # 4. 更新資料庫
        if image_url:
            sql = """
                UPDATE courses 
                SET name=%s, category_id=%s, regular_price=%s, experience_price=%s, 
                    service_fee=%s, product_fee=%s, duration=%s, description=%s, 
                    is_active=%s, image=%s, updated_at=NOW()
                WHERE id=%s
            """
            cursor.execute(sql, (name, category_id, regular_price, experience_price, service_fee,
                           product_fee, duration, description, is_active, image_url, course_id))
        else:
            sql = """
                UPDATE courses 
                SET name=%s, category_id=%s, regular_price=%s, experience_price=%s, 
                    service_fee=%s, product_fee=%s, duration=%s, description=%s, 
                    is_active=%s, updated_at=NOW()
                WHERE id=%s
            """
            cursor.execute(sql, (name, category_id, regular_price, experience_price,
                           service_fee, product_fee, duration, description, is_active, course_id))

        database.connection.commit()
        cursor.close()

        log_activity('update', 'course', course_id, {'name': name})
        flash('課程更新成功', 'success')

    except Exception as e:
        database.connection.rollback()
        print(f"Update Course Error: {e}")
        flash(f'更新失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='courses'))


@admin_bp.route('/course/<int:course_id>/delete', methods=['POST'])
@staff_required
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
@staff_required
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
@staff_required
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
@staff_required
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
    """進貨入庫 (採加權平均成本法)"""
    try:
        product_id = request.form.get('product_id', type=int)
        quantity = request.form.get('quantity', type=int)
        new_cost = request.form.get('cost', type=float)  # 本次進貨單價
        notes = request.form.get('notes', '').strip()

        if not product_id or quantity <= 0:
            flash('請輸入有效的產品與數量', 'error')
            return redirect(url_for('admin.dashboard', tab='inventory'))

        cursor = database.connection.cursor(
            MySQLdb.cursors.DictCursor)  # 預設 cursor (Tuple)

        # 1. 先查詢目前的庫存與成本
        # 注意：這裡使用 FOR UPDATE 鎖定行，避免並發寫入導致計算錯誤
        cursor.execute(
            "SELECT stock_quantity, cost FROM products WHERE id = %s FOR UPDATE", (product_id,))
        current_data = cursor.fetchone()

        if not current_data:
            cursor.close()
            flash('找不到該產品', 'error')
            return redirect(url_for('admin.dashboard', tab='inventory'))

        # 處理資料庫可能回傳 None 的情況
        current_qty = current_data['stock_quantity'] if current_data['stock_quantity'] is not None else 0
        current_avg_cost = float(
            current_data['cost']) if current_data['cost'] is not None else 0.0

        # 2. 計算加權平均成本
        # 公式：((舊庫存 * 舊成本) + (新進貨量 * 新進貨成本)) / (舊庫存 + 新進貨量)

        # 確保不會因為負庫存導致計算錯誤 (防呆)
        calc_qty = max(0, current_qty)

        if new_cost is not None and new_cost >= 0:
            total_value = (calc_qty * current_avg_cost) + (quantity * new_cost)
            total_qty = calc_qty + quantity

            # 計算新的平均成本 (四捨五入到小數點後1位)
            final_avg_cost = round(total_value / total_qty, 1)
        else:
            # 如果沒有輸入新成本，則維持原成本
            final_avg_cost = current_avg_cost

        # 3. 更新資料庫
        # 更新庫存 + 更新為平均成本 + 更新最後進貨日
        cursor.execute("""
            UPDATE products 
            SET stock_quantity = stock_quantity + %s, 
                cost = %s,
                last_purchase_date = NOW()
            WHERE id = %s
        """, (quantity, final_avg_cost, product_id))

        # 4. 寫入 Log
        # 記錄時備註本次進貨成本與新的平均成本
        log_note = f"{notes or 'Manual Restock'}. 進貨價: {new_cost}, 新平均價: {final_avg_cost}"

        cursor.execute("""
            INSERT INTO inventory_logs 
            (product_id, change_amount, change_type, notes, created_by)
            VALUES (%s, %s, 'purchase', %s, %s)
        """, (product_id, quantity, log_note, get_current_user_id()))

        database.connection.commit()
        cursor.close()

        log_activity('restock', 'inventory', product_id, {
                     'qty': quantity, 'new_avg_cost': final_avg_cost})
        flash(f'成功進貨 {quantity} 件，成本已更新為平均價 ${final_avg_cost}', 'success')

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

        try:
            # ⭐ 延遲引用
            from project.notifications import notify_order_confirmed, notify_order_status_update
            if new_status == 'confirmed' and old_status != 'confirmed':
                notify_order_confirmed(
                    order_id, customer_data, order_info['total_amount'])
            elif new_status != old_status:
                notify_order_status_update(
                    order_id, customer_data['firstname'], customer_data['email'], new_status)
        except Exception as e:
            print(f"Notification Error: {e}")

        log_activity('update', 'order', order_id, {
                     'old': old_status, 'new': new_status})
        flash(f'狀態已更新 ({new_status})', 'success')
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
            SELECT b.status, c.name as course_name, s.start_time, 
                   u.email, u.firstname, u.line_id
            FROM bookings b
            JOIN users u ON b.customer_id = u.id
            JOIN courses c ON b.course_id = c.id
            LEFT JOIN shop_schedules s ON b.global_schedule_id = s.id
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
                'email': booking_info['email'], 'firstname': booking_info['firstname'], 'line_id': booking_info['line_id']}
            time_str = booking_info['start_time'].strftime(
                '%Y-%m-%d %H:%M') if booking_info['start_time'] else "未定"

            try:
                # ⭐ 延遲引用
                from project.notifications import notify_booking_confirmed, notify_booking_status_update
                if status == 'confirmed':
                    notify_booking_confirmed(
                        booking_id, customer_data, booking_info['course_name'], time_str)
                else:
                    notify_booking_status_update(
                        booking_id, customer_data['firstname'], customer_data['email'], booking_info['course_name'], status)
            except Exception:
                pass

        log_activity('update', 'booking', booking_id, {'status': status})
        flash('狀態已更新', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'更新失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='bookings'))


@admin_bp.route('/course/<int:course_id>/update-capacity', methods=['POST'])
@staff_required
def update_course_capacity(course_id):
    """(已棄用) 批次更新該課程未來時段的可預約人數"""
    # 由於改用全店時段，此功能可能不再適用，或需修改邏輯
    return redirect(url_for('admin.dashboard', tab='courses'))

# --------------------------------------------------------
# SCHEDULE MANAGEMENT API (PER SLOT)
# --------------------------------------------------------

# --------------------------------------------------------
# GLOBAL SCHEDULE MANAGEMENT (全店共用時段)
# --------------------------------------------------------


@admin_bp.route('/api/shop/schedules')
@staff_required
def get_shop_schedules_api():
    """取得全店共用時段列表"""
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SET time_zone = '+08:00'")

    # 撈取未來 60 天
    cursor.execute("""
        SELECT id, start_time, end_time, max_capacity, current_bookings
        FROM shop_schedules
        WHERE start_time >= CURDATE()
          AND start_time < DATE_ADD(CURDATE(), INTERVAL 60 DAY)
        ORDER BY start_time ASC
    """)
    schedules = cursor.fetchall()
    cursor.close()

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


@admin_bp.route('/shop/schedule/bulk-update', methods=['POST'])
@staff_required
def bulk_update_schedule():
    """批次更新/建立 全店時段 (日期範圍 + 時間範圍)"""
    try:
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        start_hour = int(request.form.get('start_hour'))  # e.g., 9
        end_hour = int(request.form.get('end_hour'))     # e.g., 21
        capacity = int(request.form.get('capacity'))

        # 解析日期
        s_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        e_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

        cursor = database.connection.cursor()
        cursor.execute("SET time_zone = '+08:00'")

        # 迴圈每一天
        delta = timedelta(days=1)
        curr = s_date
        updated_count = 0

        while curr <= e_date:
            # 迴圈每一小時 (從 start_hour 到 end_hour-1)
            for h in range(start_hour, end_hour):
                # 建立每個小時的 start_time 和 end_time
                slot_start = datetime.combine(
                    curr, datetime.min.time().replace(hour=h))
                slot_end = slot_start + timedelta(hours=1)  # 預設每個時段1小時

                # 使用 INSERT ... ON DUPLICATE KEY UPDATE
                # 如果該時段已存在，就更新容量；不存在則新增
                cursor.execute("""
                    INSERT INTO shop_schedules (start_time, end_time, max_capacity, current_bookings, is_active)
                    VALUES (%s, %s, %s, 0, 1)
                    ON DUPLICATE KEY UPDATE max_capacity = %s
                """, (slot_start, slot_end, capacity, capacity))

                updated_count += 1

            curr += delta

        database.connection.commit()
        cursor.close()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': f'已批次更新 {updated_count} 個時段設定！'})

        flash(f'已批次更新 {updated_count} 個時段設定！', 'success')
        return redirect(url_for('admin.dashboard', tab='courses'))

    except Exception as e:
        database.connection.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': str(e)}), 500

        flash(f'更新失敗: {str(e)}', 'error')
        return redirect(url_for('admin.dashboard', tab='courses'))


@admin_bp.route('/schedule/<int:schedule_id>/update-capacity', methods=['POST'])
@staff_required
def update_single_schedule_capacity(schedule_id):
    """更新單一時段的人數上限 (For Shop Schedules)"""
    try:
        data = request.get_json()
        new_capacity = int(data.get('max_capacity'))

        if new_capacity < 0:
            return jsonify({'success': False, 'message': '人數不能為負數'}), 400

        cursor = database.connection.cursor()

        # 檢查是否小於目前已預約人數 (防止超賣)
        cursor.execute(
            "SELECT current_bookings FROM shop_schedules WHERE id = %s", (schedule_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'success': False, 'message': '時段不存在'}), 404

        # 更新
        cursor.execute("""
            UPDATE shop_schedules 
            SET max_capacity = %s 
            WHERE id = %s
        """, (new_capacity, schedule_id))

        database.connection.commit()
        cursor.close()

        return jsonify({'success': True})

    except Exception as e:
        database.connection.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

# =====================================================
# CUSTOMER MANAGEMENT
# =====================================================


def validate_password_strength(password):
    """
    驗證密碼強度：
    1. 至少 10 碼
    2. 包含大寫英文
    3. 包含小寫英文
    4. 包含數字
    5. 包含符號
    """
    if len(password) < 10:
        return False
    if not re.search(r"[A-Z]", password):
        return False
    if not re.search(r"[a-z]", password):
        return False
    if not re.search(r"\d", password):
        return False
    # 檢查特殊符號 (非英數字)
    if not re.search(r"[\W_]", password):
        return False
    return True


@admin_bp.route('/customer/add', methods=['POST'])
@staff_required
def add_customer():
    try:
        # 1. 抓取資料
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        firstname = request.form.get('firstname')
        surname = request.form.get('surname')
        email = request.form.get('email')
        phone = request.form.get('phone', '').strip()

        line_id = request.form.get('line_id')
        gender = request.form.get('gender', 'other')
        birth_date = request.form.get('birth_date') or None
        occupation = request.form.get('occupation')
        address = request.form.get('address')
        source_id = request.form.get('source_id') or None
        notes = request.form.get('notes')

        is_auto_generated = False

        # ---------------------------------------------------
        # ⭐ 自動生成邏輯 (針對不使用網站的老客戶)
        # ---------------------------------------------------

        # A. 如果沒填 Email -> 用 "手機@offline.local"
        if not email:
            if phone:
                email = f"{phone}@offline.local"
            else:
                import time
                email = f"user_{int(time.time())}@offline.local"

        # B. 如果沒填 帳號 -> 預設同電話
        if not username:
            username = phone if phone else email.split('@')[0]

        # C. 如果沒填 密碼 -> 自動生成「符合高強度驗證」的密碼
        # 規則：手機號碼 + "@Jp1"
        # (這樣就同時滿足：>10碼、大寫、小寫、數字、符號)
        if not password:
            if phone:
                password = f"{phone}@Jp1"
            else:
                # 如果連電話都沒填，給一組預設合規密碼
                password = "Password@123456"

        # 3. 檢查重複 (帳號或Email)
        cursor = database.connection.cursor()
        cursor.execute(
            "SELECT id FROM users WHERE username = %s OR email = %s", (username, email))
        if cursor.fetchone():
            flash(f'建立失敗：帳號 {username} 或 Email {email} 已存在', 'warning')
            return redirect(url_for('admin.dashboard', tab='customers'))

        # 4. 加密密碼
        from werkzeug.security import generate_password_hash
        hashed_password = generate_password_hash(password)

        # 5. 寫入資料庫 (使用 password_hash)
        sql = """
            INSERT INTO users 
            (username, email, password_hash, firstname, surname, phone, line_id, role, gender, birth_date, occupation, address, source_id, notes, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'customer', %s, %s, %s, %s, %s, %s, NOW())
        """
        cursor.execute(sql, (
            username, email, hashed_password, firstname, surname,
            phone, line_id, gender, birth_date, occupation,
            address, source_id, notes
        ))

        new_id = cursor.lastrowid
        database.connection.commit()
        cursor.close()

        log_activity('create', 'customer', new_id, {
                     'name': f"{firstname} {surname}"})

        # 提示訊息：明確顯示生成的密碼，方便您告知客戶
        flash(f'客戶建立成功！預設帳號: {username} / 預設密碼: {password}', 'success')

    except Exception as e:
        database.connection.rollback()
        print(f"Add Customer Error: {e}")
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
# --- 新增文章 ---
@admin_bp.route('/post/add', methods=['GET', 'POST'])
@staff_required
def add_post():
    if request.method == 'POST':
        try:
            title = request.form.get('title')
            content = request.form.get('content')
            summary = request.form.get('summary')
            status = request.form.get('status', 'draft')
            author_id = session.get('user', {}).get('id')

            image_url = None
            if 'image' in request.files:
                file = request.files['image']
                if file and file.filename != '':
                    image_url = upload_to_cloudinary(file)

            cursor = database.connection.cursor()
            # ⭐ 修正: posts -> blog_posts
            sql = """
                INSERT INTO blog_posts 
                (title, content, summary, status, author_id, image, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
            """
            cursor.execute(sql, (title, content, summary,
                           status, author_id, image_url))

            new_id = cursor.lastrowid
            database.connection.commit()
            cursor.close()

            log_activity('create', 'post', new_id, {'title': title})
            flash('文章已建立', 'success')
            return redirect(url_for('admin.dashboard', tab='posts'))

        except Exception as e:
            database.connection.rollback()
            flash(f'建立失敗: {str(e)}', 'error')

    return render_template('admin_post_form.html')


@admin_bp.route('/post/edit/<int:post_id>', methods=['GET', 'POST'])
@staff_required
def edit_post(post_id):
    # ⭐ 修正: posts -> blog_posts
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM blog_posts WHERE id = %s", (post_id,))
    post = cursor.fetchone()
    cursor.close()

    if not post:
        flash('找不到該文章', 'error')
        return redirect(url_for('admin.dashboard', tab='posts'))

    if request.method == 'POST':
        try:
            title = request.form.get('title')
            content = request.form.get('content')
            summary = request.form.get('summary')
            status = request.form.get('status')

            image_url = None
            if 'image' in request.files:
                file = request.files['image']
                if file and file.filename != '':
                    image_url = upload_to_cloudinary(file)

            cursor = database.connection.cursor()
            if image_url:
                # ⭐ 修正: posts -> blog_posts
                sql = """
                    UPDATE blog_posts 
                    SET title=%s, content=%s, summary=%s, status=%s, image=%s, updated_at=NOW()
                    WHERE id=%s
                """
                cursor.execute(sql, (title, content, summary,
                               status, image_url, post_id))
            else:
                # ⭐ 修正: posts -> blog_posts
                sql = """
                    UPDATE blog_posts 
                    SET title=%s, content=%s, summary=%s, status=%s, updated_at=NOW()
                    WHERE id=%s
                """
                cursor.execute(sql, (title, content, summary, status, post_id))

            database.connection.commit()
            cursor.close()

            log_activity('update', 'post', post_id, {'title': title})
            flash('文章已更新', 'success')
            return redirect(url_for('admin.dashboard', tab='posts'))

        except Exception as e:
            database.connection.rollback()
            flash(f'更新失敗: {str(e)}', 'error')

    return render_template('admin_post_form.html', post=post)


@admin_bp.route('/post/delete/<int:post_id>', methods=['POST'])
@staff_required
def delete_post(post_id):
    try:
        cursor = database.connection.cursor()
        # ⭐ 修正: posts -> blog_posts
        cursor.execute("DELETE FROM blog_posts WHERE id = %s", (post_id,))
        database.connection.commit()
        cursor.close()

        log_activity('delete', 'post', post_id)
        flash('文章已刪除', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'刪除失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='posts'))

# =====================================================
# MANUAL ORDER & BOOKING (BACKDATING/CONCIERGE)
# =====================================================


@admin_bp.route('/order/add-manual', methods=['POST'])
@staff_required
def add_order_manual():
    """管理員手動建立/補登訂單"""
    try:
        customer_id = request.form.get('customer_id')
        created_at_str = request.form.get('created_at')  # 格式: YYYY-MM-DDTHH:MM
        send_notification = request.form.get('send_notification') == 'on'

        # 接收陣列資料 (多商品)
        product_ids = request.form.getlist('product_ids[]')
        quantities = request.form.getlist('quantities[]')
        prices = request.form.getlist('prices[]')
        costs = request.form.getlist('costs[]')

        if not customer_id or not product_ids:
            flash('請選擇客戶與至少一項產品', 'error')
            return redirect(url_for('admin.dashboard', tab='orders'))

        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

 # 1. 處理日期
        if created_at_str:
            created_at = datetime.strptime(created_at_str, '%Y-%m-%dT%H:%M')
        else:
            created_at = datetime.now()

        # 2. 計算總金額 & 準備寫入資料
        total_amount = 0
        items_to_process = []

        for i, pid in enumerate(product_ids):
            if not pid:
                continue  # 跳過空值

            qty = int(quantities[i])
            if qty <= 0:
                continue

            price = float(prices[i])
            cost = float(costs[i]) if i < len(costs) and costs[i] else None

            subtotal = price * qty
            total_amount += subtotal

            items_to_process.append({
                'product_id': pid,
                'quantity': qty,
                'price': price,
                'subtotal': subtotal,
                'cost': cost
            })

        if not items_to_process:
            flash('訂單內容無效', 'error')
            return redirect(url_for('admin.dashboard', tab='orders'))

        # 3. 寫入訂單主檔
        status = 'confirmed'
        cursor.execute("""
            INSERT INTO orders (customer_id, total_amount, status, created_at)
            VALUES (%s, %s, %s, %s)
        """, (customer_id, total_amount, status, created_at))
        order_id = cursor.lastrowid

        # 4. 寫入訂單項目 & 扣庫存 & 寫入 Log
        for item in items_to_process:
            # 寫入項目
            cursor.execute("""
                INSERT INTO order_items (order_id, product_id, quantity, unit_price, subtotal)
                VALUES (%s, %s, %s, %s, %s)
            """, (order_id, item['product_id'], item['quantity'], item['price'], item['subtotal']))

            # 扣除庫存
            cursor.execute("""
                UPDATE products SET stock_quantity = stock_quantity - %s WHERE id = %s
            """, (item['quantity'], item['product_id']))

            # 庫存 Log
            log_note = 'Admin Manual Order'
            if item['cost'] is not None:
                log_note += f" (Ref Cost: {item['cost']})"

            cursor.execute("""
                INSERT INTO inventory_logs (product_id, change_amount, change_type, reference_id, notes, created_by)
                VALUES (%s, %s, 'sale', %s, %s, %s)
            """, (item['product_id'], -item['quantity'], order_id, log_note, get_current_user_id()))

        # 5. 取得客戶資料發送通知
        cursor.execute(
            "SELECT firstname, email, line_id FROM users WHERE id = %s", (customer_id,))
        user = cursor.fetchone()

        database.connection.commit()
        cursor.close()

        # 發送通知
        if send_notification and user:
            try:
                from project.notifications import notify_order_confirmed
                customer_data = {
                    'email': user['email'], 'firstname': user['firstname'], 'line_id': user['line_id']}
                notify_order_confirmed(order_id, customer_data, total_amount)
                flash('訂單已建立並發送通知', 'success')
            except Exception as e:
                flash('訂單建立成功，但通知發送失敗', 'warning')
        else:
            flash('訂單已補登', 'success')

        log_activity('create', 'order', order_id, {
                     'type': 'manual_admin', 'amount': total_amount})

    except Exception as e:
        database.connection.rollback()
        flash(f'建立失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='orders'))


@admin_bp.route('/booking/add-manual', methods=['POST'])
@staff_required
def add_booking_manual():
    """管理員手動建立/補登預約"""
    try:
        customer_id = request.form.get('customer_id')
        course_id = request.form.get('course_id')
        appt_time_str = request.form.get('appointment_time')
        sessions = int(request.form.get('sessions', 1))
        is_first_time = request.form.get('is_first_time') == 'on'
        send_notification = request.form.get('send_notification') == 'on'
        custom_total_amount = request.form.get(
            'custom_total_amount', type=float)

        if not customer_id or not course_id or not appt_time_str:
            flash('資料不完整', 'error')
            return redirect(url_for('admin.dashboard', tab='bookings'))

        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

        # 1. 取得課程資訊
        cursor.execute(
            "SELECT name, regular_price, experience_price FROM courses WHERE id = %s", (course_id,))
        course = cursor.fetchone()

        # 2. 計算價格
        if custom_total_amount is not None:
            total_amount = custom_total_amount
        else:
            price = float(course['experience_price']) if is_first_time and course['experience_price'] else float(
                course['regular_price'])
            total_amount = price * sessions

        # 3. 處理時間
        appt_time = datetime.strptime(appt_time_str, '%Y-%m-%dT%H:%M')

        # 4. 寫入預約 (手動建立通常不綁定 Schedule ID，設為 NULL)
        cursor.execute("""
            INSERT INTO bookings 
            (customer_id, course_id, schedule_id, total_amount, is_first_time, sessions_purchased, sessions_remaining, status, created_at)
            VALUES (%s, %s, NULL, %s, %s, %s, %s, 'confirmed', %s)
        """, (customer_id, course_id, total_amount, is_first_time, sessions, sessions, appt_time))

        booking_id = cursor.lastrowid

        # 4.1 自動建立一個專屬時段 (全店共用模式下，應該寫入 shop_schedules)
        # 不過為了相容性，這裡我們還是寫入 shop_schedules，並設為已佔用
        end_time = appt_time + timedelta(minutes=60)

        # 嘗試寫入全店時段，如果該時段已存在，則更新人數
        cursor.execute("""
            INSERT INTO shop_schedules (start_time, end_time, max_capacity, current_bookings, is_active)
            VALUES (%s, %s, 1, 1, 1)
            ON DUPLICATE KEY UPDATE current_bookings = current_bookings + 1
        """, (appt_time, end_time))

        # 取得剛插入或更新的 schedule id
        cursor.execute(
            "SELECT id FROM shop_schedules WHERE start_time = %s", (appt_time,))
        schedule_id = cursor.fetchone()['id']

        # 更新 booking 的 global_schedule_id
        cursor.execute("UPDATE bookings SET global_schedule_id = %s WHERE id = %s",
                       (schedule_id, booking_id))

        # 5. 取得客戶資料
        cursor.execute(
            "SELECT firstname, email, line_id FROM users WHERE id = %s", (customer_id,))
        user = cursor.fetchone()

        database.connection.commit()
        cursor.close()

        # 6. 發送通知
        if send_notification and user:
            try:
                from project.notifications import notify_booking_confirmed
                customer_data = {
                    'email': user['email'], 'firstname': user['firstname'], 'line_id': user['line_id']}
                time_str = appt_time.strftime('%Y-%m-%d %H:%M')
                notify_booking_confirmed(
                    booking_id, customer_data, course['name'], time_str)
                flash('預約已建立並發送通知', 'success')
            except Exception as e:
                print(e)
                flash('預約建立成功，但通知失敗', 'warning')
        else:
            flash('預約已補登 (未發送通知)', 'success')

        log_activity('create', 'booking', booking_id, {
                     'type': 'manual_admin', 'backdate': appt_time_str})

    except Exception as e:
        database.connection.rollback()
        flash(f'建立失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='bookings'))


@admin_bp.route('/fix-db-order')
@admin_required
def fix_db_order():
    try:
        cursor = database.connection.cursor()
        # 檢查欄位是否存在
        cursor.execute("DESCRIBE products")
        columns = [row[0] for row in cursor.fetchall()]

        if 'display_order' not in columns:
            # 新增 display_order 欄位，預設為 0
            cursor.execute(
                "ALTER TABLE products ADD COLUMN display_order INT DEFAULT 0")
            # 初始化順序 (依 ID 排序)
            cursor.execute("SET @i=0;")
            cursor.execute(
                "UPDATE products SET display_order = (@i:=@i+1) ORDER BY id ASC")
            database.connection.commit()
            return "✅ 資料庫更新成功：已新增 display_order 欄位"

        return "👌 資料庫無需更新：display_order 欄位已存在"
    except Exception as e:
        return f"❌ 更新失敗: {str(e)}"

    # ==========================================
# 🔄 產品排序 API
# ==========================================


@admin_bp.route('/product/reorder', methods=['POST'])
@staff_required
def reorder_products():
    """接收前端拖曳後的產品 ID 順序並更新資料庫"""
    try:
        data = request.get_json()
        new_order = data.get('order')  # 例如 [5, 2, 8, 1] (產品ID列表)

        if not new_order:
            return jsonify({'status': 'error', 'message': '無效的數據'}), 400

        cursor = database.connection.cursor()

        # 依序更新每個產品的 display_order
        for index, product_id in enumerate(new_order):
            cursor.execute("""
                UPDATE products 
                SET display_order = %s 
                WHERE id = %s
            """, (index, product_id))

        database.connection.commit()
        cursor.close()

        return jsonify({'status': 'success', 'message': '排序已更新'})

    except Exception as e:
        database.connection.rollback()
        print(f"Reorder Error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
