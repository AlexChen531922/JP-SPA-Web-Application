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
import json
import secrets
import cloudinary
import cloudinary.uploader
import re
from project.extensions import database
from project.db import get_current_user_id, get_current_user_role
import MySQLdb.cursors
from decimal import Decimal
from zoneinfo import ZoneInfo
from project.course_entitlements import parse_tiers, replace_tiers, load_tiers, transition_allocation
from project.stored_value import (money, ensure_wallet, change_balance, lock_order,
                                  cancel_order, restore_order, archive_order)
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

# Customer-owned stored products use independent capacity units; products.unit
# continues to mean pieces/bottles for merchandise inventory and orders.


def _capacity_from_form(form, *, required=False):
    raw = (form.get('capacity_per_unit') or '').strip()
    unit = (form.get('capacity_unit') or '').strip()
    if not raw and not unit and not required:
        return None, None
    if not raw or unit not in ('ml', 'g'):
        raise ValueError('單件容量與 ml/g 單位必須一起填寫')
    capacity = _positive_decimal(raw, '單件容量')
    return capacity, unit


def _positive_decimal(raw, label):
    text = str(raw or '').strip()
    if not re.fullmatch(r'\d{1,8}(?:\.\d{1,2})?', text):
        raise ValueError(f'{label}必須是正數，最多兩位小數')
    amount = Decimal(text)
    if amount <= 0 or amount > Decimal('99999999.99'):
        raise ValueError(f'{label}超出有效範圍')
    return amount


def _request_key(form):
    key = (form.get('request_key') or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,64}', key):
        raise ValueError('表單已過期，請重新整理後再送出')
    return key


def _taipei_today():
    return datetime.now(ZoneInfo('Asia/Taipei')).date()


def _inventory_request(cursor, customer_id, action, key, booking_id=None, usage_date=None, notes=''):
    # Insert the idempotency token inside the same transaction as the ledger.
    cursor.execute('''INSERT INTO customer_inventory_requests
        (request_key, customer_id, action, booking_id, usage_date, notes, operated_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                   (key, customer_id, action, booking_id, usage_date, notes, get_current_user_id()))
    return cursor.lastrowid


def _inventory_ledger(cursor, operation_id, inventory_id, delta, before, after, unit):
    cursor.execute('''INSERT INTO customer_inventory_movements
        (request_id, inventory_id, delta_amount, before_amount, after_amount, capacity_unit)
        VALUES (%s, %s, %s, %s, %s, %s)''',
                   (operation_id, inventory_id, delta, before, after, unit))


def _duplicate_inventory_request(exc):
    return getattr(exc, 'args', (None,))[0] == 1062


def _inventory_form_redirect(customer_id, booking_id=None):
    params = {'customer_id': customer_id, 'tab': 'inventory'}
    if booking_id:
        params['booking_id'] = booking_id
    return redirect(url_for('admin.customer_detail', **params))


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
    show_deleted_orders = request.args.get('show_deleted') == '1'
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    # 1. 基礎計數 (Counts)
    cursor.execute(
        "SELECT COUNT(*) as count FROM products WHERE is_active = TRUE")
    product_count = cursor.fetchone()['count']

    cursor.execute(
        "SELECT COUNT(*) as count FROM courses WHERE is_active = TRUE")
    course_count = cursor.fetchone()['count']

    cursor.execute(
        "SELECT COUNT(*) as count FROM orders WHERE status != 'cancelled' AND deleted_at IS NULL")
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

  # 2. 營收計算 (Revenue) - ⭐ 排除店內損耗 (email = store@jparomatic.local)
    cursor.execute("""
        SELECT
            (SELECT COALESCE(SUM(o.total_amount), 0)
             FROM orders o JOIN users u ON o.customer_id = u.id
             WHERE o.status != 'cancelled' AND o.deleted_at IS NULL AND u.email != 'store@jparomatic.local') +
            (SELECT COALESCE(SUM(b.total_amount), 0)
             FROM bookings b JOIN users u ON b.customer_id = u.id
             WHERE b.status != 'cancelled' AND u.email != 'store@jparomatic.local') +
            (SELECT COALESCE(SUM(a.recognized_amount),0)
             FROM customer_course_allocations a
             JOIN customer_course_purchases cp ON cp.id=a.purchase_id
             JOIN users u ON u.id=cp.customer_id
             WHERE a.status='completed' AND u.email != 'store@jparomatic.local')
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
        JOIN users u ON u.id=o.customer_id
        WHERE o.status != 'cancelled' AND o.deleted_at IS NULL
          AND u.email != 'store@jparomatic.local'
    """)
    res = cursor.fetchone()
    order_cost = float(res['order_cost']) if res and res['order_cost'] else 0.0

    # 課程成本
    cursor.execute("""
        SELECT COALESCE(SUM((CASE WHEN b.course_purchase_id IS NOT NULL THEN 1 ELSE b.sessions_purchased END) * (c.service_fee + c.product_fee)), 0) as course_cost
        FROM bookings b
        JOIN courses c ON b.course_id = c.id
        WHERE b.status != 'cancelled' AND b.is_unpaid_course_booking=0
          AND (b.course_purchase_id IS NULL OR b.status='completed')
    """)
    res = cursor.fetchone()
    course_cost = float(
        res['course_cost']) if res and res['course_cost'] else 0.0

    # 05: customer prepaid course receipts are separate from completed-service revenue.
    cursor.execute('''SELECT COALESCE(SUM(amount),0) AS cash_received
        FROM customer_course_payments WHERE method != 'stored_value' ''')
    course_cash_received = cursor.fetchone()['cash_received']
    cursor.execute('''SELECT COALESCE(SUM(total_paid),0) AS prepaid_total,
               COALESCE(SUM(total_paid * completed_sessions / total_sessions),0) AS allocated_total
        FROM customer_course_purchases''')
    liabilities = cursor.fetchone()

    total_cost = order_cost + course_cost
    net_profit = total_revenue - total_cost

    # Recent orders
    cursor.execute("""
        SELECT o.id, o.total_amount, o.status, o.created_at,
               u.username, u.firstname, u.surname
        FROM orders o
        JOIN users u ON o.customer_id = u.id
        WHERE o.deleted_at IS NULL
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
    cursor.execute('SELECT course_id,sessions,default_total FROM course_sale_tiers ORDER BY course_id,sessions')
    course_tiers = {}
    for tier in cursor.fetchall():
        course_tiers.setdefault(tier['course_id'], {})[tier['sessions']] = float(tier['default_total'])

    # Categories
    cursor.execute(
        "SELECT * FROM product_categories ORDER BY display_order, name")
    product_categories = cursor.fetchall()

    cursor.execute(
        "SELECT * FROM course_categories ORDER BY display_order, name")
    course_categories = cursor.fetchall()

    # 活動管理統一使用 events。封存活動不再供新訂單選取。
    cursor.execute("""
        SELECT e.*, CONCAT_WS('', u.surname, u.firstname) AS customer_name
        FROM events e
        LEFT JOIN users u ON u.id = e.customer_id
        ORDER BY e.start_date DESC, e.id DESC
    """)
    all_events = cursor.fetchall()
    events = [e for e in all_events if not e['is_archived']]
    archived_events = [e for e in all_events if e['is_archived']]

    # Inventory
    cursor.execute("""
        SELECT
            p.id, p.name, p.stock_quantity, p.cost, p.price,
            p.last_purchase_date, p.last_sale_date, p.unit,
            p.capacity_per_unit, p.capacity_unit,
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

    # Wallet balances for customer selection; missing rows mean zero credit.
    cursor.execute('SELECT customer_id,balance FROM customer_stored_balances')
    stored_balances = {r['customer_id']: str(
        r['balance']) for r in cursor.fetchall()}

    # Orders full list
    order_visibility = 'IS NOT NULL' if show_deleted_orders else 'IS NULL'
    cursor.execute(f"""
        SELECT o.*, u.username, u.firstname, u.surname, u.email, u.phone
        FROM orders o
        JOIN users u ON o.customer_id = u.id
        WHERE o.deleted_at {order_visibility}
        ORDER BY o.created_at DESC
    """)
    orders = cursor.fetchall()

    # 訂單與活動多對多關聯；需先執行對應 Staging migration。
    cursor.execute("""
        SELECT oe.order_id, e.id AS event_id, e.title
        FROM order_events oe JOIN events e ON e.id=oe.event_id
        ORDER BY e.start_date DESC, e.id DESC
    """)
    order_event_map = {}
    for link in cursor.fetchall():
        order_event_map.setdefault(link['order_id'], []).append(link)

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
               c.name as course_name, c.duration, s.start_time, s.end_time,
               cp.material_mode, cp.requires_material_confirmation
        FROM bookings b
        LEFT JOIN users u ON b.customer_id = u.id
        LEFT JOIN courses c ON b.course_id = c.id
        LEFT JOIN shop_schedules s ON b.global_schedule_id = s.id
        LEFT JOIN customer_course_purchases cp ON cp.id=b.course_purchase_id
        ORDER BY b.created_at DESC
    """)
    bookings = cursor.fetchall()

    for booking in bookings:
        if isinstance(booking.get('total_amount'), Decimal):
            booking['total_amount'] = float(booking['total_amount'])

    cursor.execute("SELECT id FROM users WHERE email='store@jparomatic.local' AND role='customer' LIMIT 1")
    shop_row = cursor.fetchone()
    store_inventory_owner_id = shop_row['id'] if shop_row else None

    # Customer list
    cursor.execute("""
        SELECT u.id, u.username, u.email, u.firstname, u.surname,
               u.phone, u.line_id, u.gender, u.occupation, u.created_at,
               u.birth_date, u.source_id, u.address, u.notes, u.updated_at,
               TIMESTAMPDIFF(YEAR, u.birth_date, CURDATE()) as age,
               cs.name as source_name,
               COUNT(DISTINCT o.id) as order_count,
               COUNT(DISTINCT b.id) as booking_count
        FROM users u
        LEFT JOIN customer_sources cs ON u.source_id = cs.id
        LEFT JOIN orders o ON u.id = o.customer_id AND o.deleted_at IS NULL
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

    now = datetime.now()

    stats = {
        'products': product_count,
        'courses': course_count,
        'orders': order_count,
        'bookings': booking_count,
        'customers': customer_count,
        'posts': post_count,
        'revenue': float(total_revenue),
        'net_profit': net_profit,
        'course_cash_received': course_cash_received,
        'course_unfulfilled': max(Decimal('0'), Decimal(str(liabilities['prepaid_total'])) - Decimal(str(liabilities['allocated_total'])))
    }

    # ================= 新增：員工與手技費資料 =================
    cursor.execute(
        "SELECT * FROM users WHERE role IN ('admin', 'staff') ORDER BY role, firstname")
    employees = cursor.fetchall()

    # 取得員工當月薪資紀錄 (或歷史紀錄)
    cursor.execute(
        "SELECT * FROM employee_salaries ORDER BY salary_month DESC")
    salaries = cursor.fetchall()

    # 取得手技費列表
    cursor.execute("SELECT * FROM service_fees WHERE is_active = 1")
    service_fees = cursor.fetchall()
    # ========================================================

    cursor.close()

    return render_template(
        'admin_dashboard.html',
        tab=tab,
        stats=stats,
        recent_orders=recent_orders,
        recent_bookings=recent_bookings,
        products=products,
        courses=courses,
        course_tiers=course_tiers,
        course_sale_request_key=secrets.token_urlsafe(24),
        unpaid_booking_request_key=secrets.token_urlsafe(24),
        course_completion_request_key=secrets.token_urlsafe(24),
        store_inventory_owner_id=store_inventory_owner_id,
        owned_booking_request_key=secrets.token_urlsafe(24),
        product_categories=product_categories,
        course_categories=course_categories,
        events=events,
        archived_events=archived_events,
        inventory_products=inventory_products,
        customers=customers,
        manual_order_request_key=secrets.token_urlsafe(24),
        manual_booking_request_key=secrets.token_urlsafe(24),
        stored_balances=stored_balances,
        orders=orders,
        show_deleted_orders=show_deleted_orders,
        bookings=bookings,
        customers_list=customers_list,
        customer_sources=customer_sources,
        posts=posts,
        order_items_map=order_items_map,
        order_event_map=order_event_map,
        audit_logs=audit_logs,
        employees=employees,
        salaries=salaries,
        service_fees=service_fees,
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
        capacity, capacity_unit = _capacity_from_form(request.form)

        image_url = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '':
                image_url = upload_to_cloudinary(file)

        cursor = database.connection.cursor()
        sql = """
            INSERT INTO products
            (name, category_id, price, cost, stock_quantity,
             description, image, is_active, created_at, capacity_per_unit, capacity_unit)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s)
        """
        cursor.execute(sql, (name, category_id, price, cost,
                       stock, description, image_url, 1, capacity, capacity_unit))

        new_id = cursor.lastrowid
        # 初始庫存也應具有可追溯的入庫流水。
        initial_stock = int(stock)
        if initial_stock < 0:
            raise ValueError('初始庫存不得為負數')
        if initial_stock:
            cursor.execute("""INSERT INTO inventory_logs
                (product_id, change_amount, change_type, notes, created_by,
                 capacity_per_unit_snapshot, capacity_unit_snapshot)
                VALUES (%s, %s, 'adjustment', '新產品初始庫存', %s, %s, %s)""",
                           (new_id, initial_stock, get_current_user_id(), capacity, capacity_unit))
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
        cursor.execute(
            "SELECT * FROM products WHERE id = %s FOR UPDATE", (product_id,))
        current_prod = cursor.fetchone()

        if not current_prod:
            flash('找不到該產品', 'error')
            return redirect(url_for('admin.dashboard', tab='products'))

        # 2. 接收表單資料
        name = request.form.get('name')
        category_id = request.form.get('category_id') or None
        price = request.form.get('price') or 0
        stock = int(request.form.get('stock') or 0)
        if stock < 0:
            raise ValueError('庫存不得為負數')
        stock_difference = stock - int(current_prod['stock_quantity'] or 0)
        description = request.form.get('description')
        is_active = 1 if request.form.get('is_active') else 0
        capacity, capacity_unit = _capacity_from_form(request.form)
        old_capacity = current_prod.get('capacity_per_unit')
        old_unit = current_prod.get('capacity_unit')
        changed_capacity = (
            capacity != old_capacity or capacity_unit != old_unit)
        if changed_capacity:
            # Historical purchased / stored products must retain their size.
            cursor.execute('''SELECT COUNT(*) AS n FROM customer_inventory
                              WHERE product_id=%s''', (product_id,))
            if cursor.fetchone()['n']:
                raise ValueError('已有寄店紀錄，不能改變容量規格；請建立不同規格商品')
            if old_capacity is not None:
                cursor.execute(
                    'SELECT 1 FROM order_items WHERE product_id=%s LIMIT 1', (product_id,))
                if cursor.fetchone():
                    raise ValueError('已有購買紀錄，不能改變既有容量規格；請建立不同規格商品')
                if int(current_prod.get('stock_quantity') or 0) > 0:
                    raise ValueError('仍有商品庫存，不能改變既有容量規格；請建立不同規格商品')

        # 如果是 Staff (表單沒傳 cost)，則使用資料庫舊值
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
                    description=%s, is_active=%s, image=%s,
                    capacity_per_unit=%s, capacity_unit=%s, updated_at=NOW()
                WHERE id=%s
            """
            cursor.execute(sql, (name, category_id, price, cost,
                           stock, description, is_active, image_url,
                           capacity, capacity_unit, product_id))
        else:
            sql = """
                UPDATE products
                SET name=%s, category_id=%s, price=%s, cost=%s, stock_quantity=%s,
                    description=%s, is_active=%s,
                    capacity_per_unit=%s, capacity_unit=%s, updated_at=NOW()
                WHERE id=%s
            """
            cursor.execute(sql, (name, category_id, price, cost,
                           stock, description, is_active, capacity, capacity_unit, product_id))

        if stock_difference:
            cursor.execute("""INSERT INTO inventory_logs
                (product_id, change_amount, change_type, notes, created_by)
                VALUES (%s, %s, 'adjustment', '編輯產品時調整庫存', %s)""",
                           (product_id, stock_difference, get_current_user_id()))
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
    tiers = load_tiers(cursor,course_id) if course else {}
    cursor.close()

    if course:
        course['sale_tiers'] = ','.join(f'{qty}:{price:.0f}' for qty,price in tiers.items())
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
        tiers = parse_tiers(request.form.get('sale_tiers'))
        visibility = request.form.get('course_visibility','public')
        if visibility not in ('public','hidden','disabled'):
            raise ValueError('課程上架狀態不正確')
        uses_store = 1 if request.form.get('uses_store_consumables') == '1' else 0

        image_url = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '':
                image_url = upload_to_cloudinary(file)

        cursor = database.connection.cursor()
        sql = """
            INSERT INTO courses
            (name, category_id, regular_price, experience_price, service_fee, product_fee,
             duration, description, image, is_active, is_public, uses_store_consumables, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """
        cursor.execute(sql, (name, category_id, regular_price, experience_price,
                       service_fee, product_fee, duration, description, image_url,
                       0 if visibility == 'disabled' else 1, 1 if visibility == 'public' else 0, uses_store))

        new_id = cursor.lastrowid
        replace_tiers(cursor, new_id, tiers)
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
        visibility = request.form.get('course_visibility','public')
        if visibility not in ('public','hidden','disabled'):
            raise ValueError('課程上架狀態不正確')
        is_active = 0 if visibility == 'disabled' else 1
        is_public = 1 if visibility == 'public' else 0
        uses_store = 1 if request.form.get('uses_store_consumables') == '1' else 0
        tiers = parse_tiers(request.form.get('sale_tiers'))

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
                    is_active=%s, is_public=%s, uses_store_consumables=%s, image=%s, updated_at=NOW()
                WHERE id=%s
            """
            cursor.execute(sql, (name, category_id, regular_price, experience_price, service_fee,
                           product_fee, duration, description, is_active, is_public, uses_store, image_url, course_id))
        else:
            sql = """
                UPDATE courses
                SET name=%s, category_id=%s, regular_price=%s, experience_price=%s,
                    service_fee=%s, product_fee=%s, duration=%s, description=%s,
                    is_active=%s, is_public=%s, uses_store_consumables=%s, updated_at=NOW()
                WHERE id=%s
            """
            cursor.execute(sql, (name, category_id, regular_price, experience_price,
                           service_fee, product_fee, duration, description, is_active, is_public, uses_store, course_id))

        replace_tiers(cursor,course_id,tiers)
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
        cursor.execute('SELECT COUNT(*) AS count FROM customer_course_purchases WHERE course_id=%s', (course_id,))
        purchase_count = cursor.fetchone()['count']

        if booking_count > 0 or purchase_count > 0:
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
        cursor.execute(
            "SELECT customer_id FROM events WHERE id=%s", (event_id,))
        prior_event = cursor.fetchone()
        if prior_event is None:
            cursor.close()
            flash('找不到這筆活動，未進行更新', 'error')
            return redirect(url_for('admin.dashboard', tab='events'))
        # 原編輯表單沒有 customer_id 欄位，不能因此將既有客戶關聯清空。
        if 'customer_id' not in request.form:
            customer_id = prior_event[0]
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
    """Unlinked events may be deleted; linked events are archived, preserving order history."""
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    action = None
    event_title = None
    try:
        # Lock the parent row: a concurrent order adding an FK must wait.
        cursor.execute(
            'SELECT id,title,is_archived FROM events WHERE id=%s FOR UPDATE', (event_id,))
        event = cursor.fetchone()
        if not event:
            flash('活動不存在或已刪除', 'warning')
        elif event['is_archived']:
            flash('這筆活動已封存', 'info')
        else:
            event_title = event['title']
            cursor.execute(
                'SELECT COUNT(*) AS n FROM order_events WHERE event_id=%s', (event_id,))
            linked_orders = cursor.fetchone()['n']
            if linked_orders:
                cursor.execute(
                    'UPDATE events SET is_archived=1 WHERE id=%s', (event_id,))
                action = 'archive'
            else:
                cursor.execute('DELETE FROM events WHERE id=%s', (event_id,))
                if cursor.rowcount != 1:
                    raise RuntimeError('活動刪除未成功，請重新載入後再試')
                action = 'delete'
            database.connection.commit()
            flash('活動已封存，歷史訂單關聯保留' if action ==
                  'archive' else '活動已永久刪除', 'success')
    except MySQLdb.IntegrityError:
        database.connection.rollback()
        current_app.logger.exception(
            'Event deletion blocked by database constraint: %s', event_id)
        flash('活動仍被其他資料參照，未刪除任何資料；請查看 Railway 執行日誌', 'error')
    except Exception:
        database.connection.rollback()
        current_app.logger.exception(
            'Failed to delete or archive event %s', event_id)
        flash('活動刪除／封存失敗，請查看 Railway 執行日誌', 'error')
    finally:
        cursor.close()
    if action:
        try:
            log_activity(action, 'event', event_id, {'title': event_title})
        except Exception:
            current_app.logger.exception('Could not audit event %s', event_id)
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
        incoming_capacity, incoming_unit = _capacity_from_form(request.form)

        if not product_id or quantity is None or quantity <= 0:
            flash('請輸入有效的產品與數量', 'error')
            return redirect(url_for('admin.dashboard', tab='inventory'))

        cursor = database.connection.cursor(
            MySQLdb.cursors.DictCursor)  # 預設 cursor (Tuple)

        # 1. 先查詢目前的庫存與成本
        # 注意：這裡使用 FOR UPDATE 鎖定行，避免並發寫入導致計算錯誤
        cursor.execute(
            "SELECT stock_quantity, cost, capacity_per_unit, capacity_unit FROM products WHERE id = %s FOR UPDATE", (product_id,))
        current_data = cursor.fetchone()

        if not current_data:
            cursor.close()
            flash('找不到該產品', 'error')
            return redirect(url_for('admin.dashboard', tab='inventory'))

        # If a size is supplied, it is the incoming batch specification.
        # Never combine batches of different sizes under one product ID.
        configured_capacity = current_data['capacity_per_unit']
        configured_unit = current_data['capacity_unit']
        if incoming_capacity is not None:
            if configured_capacity is not None and (
                incoming_capacity != configured_capacity or incoming_unit != configured_unit
            ):
                raise ValueError('進貨容量與此產品既有規格不同，請新增另一個產品規格')
            if configured_capacity is None:
                cursor.execute('''UPDATE products
                    SET capacity_per_unit=%s, capacity_unit=%s WHERE id=%s''',
                               (incoming_capacity, incoming_unit, product_id))
        elif configured_capacity is not None:
            incoming_capacity, incoming_unit = configured_capacity, configured_unit

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
            (product_id, change_amount, change_type, notes, created_by,
             capacity_per_unit_snapshot, capacity_unit_snapshot)
            VALUES (%s, %s, 'purchase', %s, %s, %s, %s)
        """, (product_id, quantity, log_note, get_current_user_id(),
              incoming_capacity, incoming_unit))

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

        if not product_id or change_amount is None or change_amount == 0:
            flash('請填寫完整資料', 'error')
            return redirect(url_for('admin.dashboard', tab='inventory'))

        if change_type not in ('purchase', 'sale', 'adjustment', 'return'):
            raise ValueError('不支援的庫存異動類型')
        reason = (request.form.get('reason') or '').strip()
        if reason:
            notes = (reason + ('：' + notes if notes else ''))[:2000]
        cursor = database.connection.cursor()
        cursor.execute(
            'SELECT stock_quantity FROM products WHERE id=%s FOR UPDATE', (product_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError('產品不存在')
        if (row[0] or 0) + change_amount < 0:
            raise ValueError('庫存不足，不能調整為負數')

        # 1. 更新產品實際庫存
        cursor.execute("""
            UPDATE products SET stock_quantity = stock_quantity + %s WHERE id = %s
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


@admin_bp.route('/inventory/product/<int:product_id>/history')
@staff_required
def product_inventory_history(product_id):
    """逐筆檢視產品進出貨紀錄；訂單銷貨可追溯至訂單與客戶。"""
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        cursor.execute(
            'SELECT id, name, stock_quantity, unit, capacity_per_unit, capacity_unit FROM products WHERE id=%s', (product_id,))
        product = cursor.fetchone()
        if not product:
            flash('找不到該產品', 'error')
            return redirect(url_for('admin.dashboard', tab='inventory'))
        cursor.execute("""
            SELECT l.id, l.created_at, l.change_type, l.change_amount, l.notes,
                   l.reference_id, o.id AS order_id,
                   CONCAT_WS('', u.surname, u.firstname) AS customer_name,
                   creator.username AS operator_name
            FROM inventory_logs l
            LEFT JOIN orders o ON o.id=l.reference_id AND l.change_type IN ('sale','return')
            LEFT JOIN users u ON u.id=o.customer_id
            LEFT JOIN users creator ON creator.id=l.created_by
            WHERE l.product_id=%s
            ORDER BY l.created_at DESC, l.id DESC
        """, (product_id,))
        logs = cursor.fetchall()
    finally:
        cursor.close()
    return render_template('admin_inventory_history.html', product=product, logs=logs)


# =====================================================
# ORDER STATUS & INVENTORY SYNC (CRITICAL)
# =====================================================


# 記得確認檔案最上方有匯入通知函式
# from project.notifications import notify_order_confirmed, notify_order_status_update

@admin_bp.route('/order/<int:order_id>/update-status', methods=['POST'])
@staff_required
def update_order_status(order_id):
    new_status = request.form.get('status')
    if new_status not in ('pending', 'confirmed', 'completed', 'cancelled'):
        flash('無效的狀態', 'error')
        return redirect(url_for('admin.dashboard', tab='orders'))

    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    changed = False
    try:
        order = lock_order(cursor, order_id)
        old_status = order['status']
        if old_status != new_status:
            if new_status == 'cancelled':
                cursor.execute('''SELECT COUNT(*) AS count FROM manual_checkout_payments
                                  WHERE order_id=%s AND method IN
                                    ('cash','credit_card','bank_transfer','other')
                                    AND status='recorded' ''', (order_id,))
                if cursor.fetchone()['count']:
                    raise ValueError('訂單有人工記錄的實際收款，須先確認退款，不能直接取消')
                cancel_order(cursor, order, get_current_user_id())
            elif old_status == 'cancelled':
                # Stock and stored-value are both charged before the order can be restored.
                restore_order(cursor, order, new_status, get_current_user_id())
            else:
                cursor.execute(
                    'UPDATE orders SET status=%s WHERE id=%s', (new_status, order_id))
                if new_status == 'completed':
                    cursor.execute('''UPDATE products p JOIN order_items oi ON p.id=oi.product_id
                                      SET p.last_sale_date=NOW() WHERE oi.order_id=%s''', (order_id,))
            changed = True
        cursor.execute(
            'SELECT firstname,email,line_id FROM users WHERE id=%s', (order['customer_id'],))
        customer_data = cursor.fetchone()
        database.connection.commit()
    except Exception as exc:
        database.connection.rollback()
        flash(f'訂單狀態更新失敗：{exc}', 'error')
        return redirect(url_for('admin.dashboard', tab='orders'))
    finally:
        cursor.close()
    if changed:
        try:
            from project.notifications import notify_order_confirmed, notify_order_status_update
            if new_status == 'confirmed' and old_status != 'confirmed':
                notify_order_confirmed(order_id, customer_data, order['total_amount'],
                                       order['stored_value_amount'], order['other_payment_amount'], order['other_payment_method'])
            else:
                notify_order_status_update(
                    order_id, customer_data['firstname'], customer_data['email'], new_status)
        except Exception as exc:
            current_app.logger.warning(
                'Order notification failed: %s', type(exc).__name__)
        try:
            log_activity('update', 'order', order_id, {
                         'old': old_status, 'new': new_status})
        except Exception:
            current_app.logger.warning(
                'Order status audit log failed for order %s', order_id)
        flash('訂單狀態已更新', 'success')
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

        # 鎖住此預約，避免重複取消／恢復造成時段人數不一致。
        cursor.execute(
            'SELECT id, status, is_unpaid_course_booking, course_purchase_id FROM bookings WHERE id=%s FOR UPDATE', (booking_id,))
        locked_booking = cursor.fetchone()
        if not locked_booking:
            raise ValueError('預約不存在')
        if (status == 'completed' and locked_booking['is_unpaid_course_booking']
                and not locked_booking['course_purchase_id']):
            raise ValueError('純預約尚未購買課程，不能標記完成；請先在課程販售連結預約')
        if status == 'completed' and locked_booking['course_purchase_id']:
            cursor.execute('''SELECT requires_material_confirmation FROM customer_course_purchases
                              WHERE id=%s''', (locked_booking['course_purchase_id'],))
            needs = cursor.fetchone()
            if needs and needs['requires_material_confirmation']:
                raise ValueError('此課程須使用「完成與耗材核銷」，不得直接變更狀態')

        # 有已收款或待核銷寄店抵扣的預約，不可直接取消而不作退款／沖銷。
        if status == 'cancelled' and locked_booking['status'] != 'cancelled':
            cursor.execute('''SELECT stored_value_amount, other_payment_amount,
                                     deposit_credit_amount FROM bookings WHERE id=%s''', (booking_id,))
            pay = cursor.fetchone()
            if any(Decimal(str(pay[f] or 0)) > 0 for f in
                   ('stored_value_amount','other_payment_amount','deposit_credit_amount')):
                raise ValueError('此預約已有付款或待核銷寄店抵扣，須先處理退款與沖銷，不能直接取消')

        # 1. ⭐ 獲取預約詳細資訊 (包含課程名稱、時間、客戶資料)
        cursor.execute("""
            SELECT b.status, b.global_schedule_id, c.name as course_name, s.start_time,
                   u.email, u.firstname, u.line_id
            FROM bookings b
            JOIN users u ON b.customer_id = u.id
            JOIN courses c ON b.course_id = c.id
            LEFT JOIN shop_schedules s ON b.global_schedule_id = s.id
            WHERE b.id = %s
        """, (booking_id,))
        booking_info = cursor.fetchone()
        if not booking_info:
            raise ValueError('預約不存在')
        old_active = booking_info['status'] != 'cancelled'
        new_active = status != 'cancelled'
        schedule_id = booking_info['global_schedule_id']
        if schedule_id and old_active != new_active:
            cursor.execute(
                'SELECT max_capacity, current_bookings FROM shop_schedules WHERE id=%s FOR UPDATE', (schedule_id,))
            slot = cursor.fetchone()
            if not slot:
                raise ValueError('找不到預約時段')
            delta = 1 if new_active else -1
            if delta > 0 and slot['current_bookings'] >= slot['max_capacity']:
                raise ValueError('時段已額滿，無法恢復預約')
            if delta < 0 and slot['current_bookings'] <= 0:
                raise ValueError('預約時段人數不一致，請先檢查資料')
            cursor.execute(
                'UPDATE shop_schedules SET current_bookings=current_bookings+%s WHERE id=%s', (delta, schedule_id))

        # 05: Paid entitlement stays reserved until service completion.
        transition_allocation(cursor, booking_id, status, get_current_user_id())
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

        if capacity < 0 or not (0 <= start_hour < end_hour <= 24):
            raise ValueError('人數或營業時段不合法')
        # 解析日期
        s_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        e_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        if s_date > e_date:
            raise ValueError('結束日期不能早於開始日期')
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

                # 已存在的時段不能將容量調整至低於實際預約人數。
                cursor.execute(
                    'SELECT current_bookings FROM shop_schedules WHERE start_time=%s FOR UPDATE', (slot_start,))
                occupied = cursor.fetchone()
                if occupied and capacity < occupied[0]:
                    raise ValueError(
                        f'{slot_start} 已預約 {occupied[0]} 人，不能降低至 {capacity} 人')
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
            "SELECT current_bookings FROM shop_schedules WHERE id = %s FOR UPDATE", (schedule_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'success': False, 'message': '時段不存在'}), 404

        if new_capacity < row[0]:
            cursor.close()
            return jsonify({'success': False, 'message': '新容量不能低於已預約人數'}), 400
        # 更新
        cursor.execute("""
            UPDATE shop_schedules
            SET max_capacity = %s WHERE id = %s
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

        # 沒填密碼時產生高熵隨機初始密碼，不使用手機或固定預設密碼。
        # 不顯示或記錄初始密碼；需要登入的客戶透過忘記密碼流程重設。
        auto_password = not password
        if auto_password:
            import secrets
            password = secrets.token_urlsafe(32)

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
            (username, email, password_hash, firstname, surname, phone, line_id, role,
             gender, birth_date, occupation, address, source_id, notes, created_at)
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

        if auto_password:
            flash('客戶建立成功。系統已設定隨機初始密碼，未在畫面顯示；若需要登入，請使用真實 Email 的忘記密碼流程重設。', 'success')
        else:
            flash('客戶建立成功', 'success')

    except Exception as e:
        database.connection.rollback()
        print(f"Add Customer Error: {e}")
        flash(f'新增失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='customers'))


@admin_bp.route('/customer/<int:customer_id>/update', methods=['POST'])
@staff_required
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
        address = request.form.get('address', '').strip()

        notes = request.form.get('notes', '').strip()

        if not firstname or not email:
            flash('姓名與 Email 為必填', 'error')
            return redirect(url_for('admin.dashboard', tab='customers'))

        cursor = database.connection.cursor()
        cursor.execute(
            "SELECT id FROM users WHERE id=%s AND role='customer'", (customer_id,))
        if cursor.fetchone() is None:
            cursor.close()
            flash('找不到該客戶，未進行更新', 'error')
            return redirect(url_for('admin.dashboard', tab='customers'))

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
                gender=%s, birth_date=%s, occupation=%s, source_id=%s, address=%s, notes=%s
            WHERE id=%s AND role='customer'
        """, (firstname, surname, email, phone, line_id, gender, birth_date, occupation, source_id, address, notes, customer_id))

        database.connection.commit()
        cursor.close()

        # 記錄 Log
        log_activity('update', 'customer', customer_id,
                     {'name': f"{firstname} {surname}"})

        flash('客戶資料已更新', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'更新失敗: {str(e)}', 'error')

    return redirect(url_for('admin.customer_detail', customer_id=customer_id))


@admin_bp.route('/customer/<int:customer_id>/detail')
@staff_required
def customer_detail(customer_id):
    """檢視客戶詳細資料與歷史紀錄"""
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    try:
        # 1. 取得客戶基本資料與來源名稱
        cursor.execute("""
            SELECT u.*, cs.name as source_name,
                   TIMESTAMPDIFF(YEAR, u.birth_date, CURDATE()) as age
            FROM users u
            LEFT JOIN customer_sources cs ON u.source_id = cs.id
            WHERE u.id = %s AND u.role = 'customer'
        """, (customer_id,))
        customer = cursor.fetchone()

        if not customer:
            flash('找不到該客戶', 'error')
            return redirect(url_for('admin.dashboard', tab='customers'))

        # 2. 取得產品訂單紀錄 (依時間新到舊排序)
        cursor.execute("""
            SELECT id, total_amount, status, created_at
            FROM orders
            WHERE customer_id = %s AND deleted_at IS NULL
            ORDER BY created_at DESC
        """, (customer_id,))
        product_orders = cursor.fetchall()

        # 取得訂單「購買明細 (Order Items)」並依照訂單 ID 打包
        order_items_map = {}
        if product_orders:
            # 抽出所有訂單的 ID
            order_ids = [str(o['id']) for o in product_orders]
            format_strings = ','.join(['%s'] * len(order_ids))

            # 一次性撈出這些訂單底下的所有產品
            cursor.execute(f"""
                SELECT oi.order_id, oi.quantity, p.name as product_name
                FROM order_items oi
                JOIN products p ON oi.product_id = p.id
                WHERE oi.order_id IN ({format_strings})
            """, tuple(order_ids))
            all_items = cursor.fetchall()

            # 把產品分類塞回對應的訂單 ID 字典裡
            for item in all_items:
                oid = item['order_id']
                if oid not in order_items_map:
                    order_items_map[oid] = []
                order_items_map[oid].append(item)

        # 3. 取得課程預約紀錄 (關聯課程名稱與預約時間)
        cursor.execute("""
            SELECT b.id, b.total_amount, b.status, b.created_at,
                   c.name as course_name, s.start_time
            FROM bookings b
            JOIN courses c ON b.course_id = c.id
            LEFT JOIN shop_schedules s ON b.global_schedule_id = s.id
            WHERE b.customer_id = %s
            ORDER BY b.created_at DESC
        """, (customer_id,))
        course_bookings = cursor.fetchall()
        cursor.execute('''SELECT cp.id,cp.course_id,cp.total_sessions,cp.completed_sessions,
            cp.reserved_sessions,cp.total_paid,cp.created_at,c.name AS course_name
            FROM customer_course_purchases cp JOIN courses c ON c.id=cp.course_id
            WHERE cp.customer_id=%s ORDER BY cp.id DESC''', (customer_id,))
        owned_courses = cursor.fetchall()

        # Prepaid credit (never expires). Ledger is append-only.
        cursor.execute(
            'SELECT balance FROM customer_stored_balances WHERE customer_id=%s', (customer_id,))
        balance_row = cursor.fetchone()
        stored_value_balance = balance_row['balance'] if balance_row else Decimal(
            '0.00')
        cursor.execute('''SELECT l.*, o.id AS related_order_id
                           FROM customer_stored_value_ledger l
                           LEFT JOIN orders o ON o.id=l.order_id
                           WHERE l.customer_id=%s ORDER BY l.id DESC LIMIT 50''', (customer_id,))
        stored_value_history = cursor.fetchall()

        # 4. 取得來源列表 (供編輯表單的下拉選單使用)
        cursor.execute("SELECT * FROM customer_sources ORDER BY id")
        customer_sources = cursor.fetchall()

        # 5. 客戶寄店產品與來源購買明細
        cursor.execute("""
            SELECT ci.id, ci.product_id, ci.order_item_id, ci.deposited_units,
                   ci.original_amount, ci.remaining_amount, ci.capacity_unit,
                   ci.created_at, ci.updated_at, p.name AS product_name
            FROM customer_inventory ci
            JOIN products p ON p.id=ci.product_id
            WHERE ci.customer_id=%s
            ORDER BY (ci.remaining_amount > 0) DESC, ci.created_at DESC, ci.id DESC
        """, (customer_id,))
        customer_inventory = cursor.fetchall()

        # Source is a specific completed order line, not merely a product name.
        # Never offer the same purchased unit for deposit twice.
        cursor.execute("""
            SELECT oi.id AS order_item_id, oi.order_id, oi.product_id,
                   oi.quantity AS purchased_units, p.name AS product_name,
                   p.capacity_per_unit, p.capacity_unit,
                   COALESCE(SUM(ci.deposited_units), 0) AS deposited_units
            FROM order_items oi
            JOIN orders o ON o.id=oi.order_id
            JOIN products p ON p.id=oi.product_id
            LEFT JOIN customer_inventory ci ON ci.order_item_id=oi.id
            WHERE o.customer_id=%s AND o.deleted_at IS NULL AND o.status='completed'
            GROUP BY oi.id, oi.order_id, oi.product_id, oi.quantity, p.name,
                     p.capacity_per_unit, p.capacity_unit
            ORDER BY oi.id DESC
        """, (customer_id,))
        purchased_products = cursor.fetchall()
        for item in purchased_products:
            item['available_units'] = int(
                item['purchased_units']) - int(item['deposited_units'])

        cursor.execute('''SELECT b.id, b.status, c.name AS course_name,
                                 COALESCE(s.start_time, b.booking_date, b.created_at) AS session_time
                          FROM bookings b
                          JOIN courses c ON c.id=b.course_id
                          LEFT JOIN shop_schedules s ON s.id=b.global_schedule_id
                          WHERE b.customer_id=%s AND b.status='completed'
                          ORDER BY session_time DESC''', (customer_id,))
        inventory_bookings = cursor.fetchall()

        cursor.execute('''SELECT m.id, m.inventory_id, m.delta_amount,
                                 m.before_amount, m.after_amount, m.capacity_unit,
                                 m.created_at, r.action, r.usage_date, r.notes,
                                 r.booking_id, c.name AS course_name,
                                 CONCAT(COALESCE(u.surname,''),COALESCE(u.firstname,'')) AS operator_name
                          FROM customer_inventory_movements m
                          JOIN customer_inventory_requests r ON r.id=m.request_id
                          JOIN customer_inventory ci ON ci.id=m.inventory_id
                          LEFT JOIN bookings b ON b.id=r.booking_id
                          LEFT JOIN courses c ON c.id=b.course_id
                          LEFT JOIN users u ON u.id=r.operated_by
                          WHERE ci.customer_id=%s
                          ORDER BY m.created_at DESC, m.id DESC LIMIT 200''', (customer_id,))
        inventory_history = cursor.fetchall()

    finally:
        cursor.close()

    return render_template(
        'admin_customer_detail.html',
        customer=customer,
        stored_value_balance=stored_value_balance,
        stored_value_history=stored_value_history,
        stored_value_request_key=secrets.token_urlsafe(24),
        product_orders=product_orders,
        order_items_map=order_items_map,
        course_bookings=course_bookings,
        owned_courses=owned_courses,
        owned_booking_request_key=secrets.token_urlsafe(24),
        customer_sources=customer_sources,
        customer_inventory=customer_inventory,
        purchased_products=purchased_products,
        inventory_bookings=inventory_bookings,
        inventory_history=inventory_history,
        inventory_booking_id=request.args.get('booking_id', type=int),
        inventory_today=_taipei_today().isoformat(),
        deposit_request_key=secrets.token_urlsafe(24),
        deduct_request_key=secrets.token_urlsafe(24),
        adjust_request_keys={inv['id']: secrets.token_urlsafe(24)
                             for inv in customer_inventory}
    )


@admin_bp.route('/customer/<int:customer_id>/inventory/add', methods=['POST'])
@staff_required
def add_customer_inventory(customer_id):
    # Deposit multiple actually purchased order-line units atomically.
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        key = _request_key(request.form)
        selected = request.form.getlist('deposit_order_item_ids[]')
        if not selected or len(selected) > 100:
            raise ValueError('請至少勾選一項已購買產品')
        ids = []
        for raw_id in selected:
            try:
                item_id = int(raw_id)
            except (ValueError, TypeError):
                raise ValueError('產品項目無效')
            if item_id <= 0 or item_id in ids:
                raise ValueError('產品項目重複或無效')
            ids.append(item_id)
        ids.sort()  # deterministic locking order
        database.connection.begin()
        request_id = _inventory_request(cursor, customer_id, 'deposit', key)
        for item_id in ids:
            units_raw = (request.form.get(
                f'deposit_units_{item_id}') or '').strip()
            if not re.fullmatch(r'[1-9]\d{0,5}', units_raw):
                raise ValueError('寄店件數必須是正整數')
            units = int(units_raw)
            cursor.execute('''SELECT oi.id, oi.order_id, oi.product_id,
                                     oi.quantity, p.capacity_per_unit, p.capacity_unit
                              FROM order_items oi
                              JOIN orders o ON o.id=oi.order_id
                              JOIN products p ON p.id=oi.product_id
                              WHERE oi.id=%s AND o.customer_id=%s
                                AND o.deleted_at IS NULL AND o.status='completed'
                              FOR UPDATE''', (item_id, customer_id))
            source = cursor.fetchone()
            if not source:
                raise ValueError('來源訂單不存在、未完成或不屬於此客戶')
            capacity = source['capacity_per_unit']
            unit = source['capacity_unit']
            if capacity is None or unit not in ('g', 'ml') or capacity <= 0:
                raise ValueError('產品尚未設定單件容量與單位，無法寄店')
            # Legacy rows have no verifiable source order line. Prevent over-allocation.
            cursor.execute('''SELECT COUNT(*) AS n FROM customer_inventory
                              WHERE customer_id=%s AND product_id=%s
                                AND order_item_id IS NULL''',
                           (customer_id, source['product_id']))
            if cursor.fetchone()['n']:
                raise ValueError('此產品有尚未對應來源訂單的舊寄店紀錄，請先人工核對')
            cursor.execute('''SELECT COALESCE(SUM(deposited_units),0) AS used
                              FROM customer_inventory WHERE order_item_id=%s''', (item_id,))
            allocated = int(cursor.fetchone()['used'])
            if allocated + units > int(source['quantity']):
                raise ValueError('寄店件數超過此訂單明細尚可寄店的數量')
            initial = capacity * units
            if initial > Decimal('99999999.99'):
                raise ValueError('寄店容量超出可儲存範圍')
            cursor.execute('''INSERT INTO customer_inventory
                (customer_id, product_id, order_id, order_item_id, deposited_units,
                 original_amount, remaining_amount, capacity_unit)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
                           (customer_id, source['product_id'], source['order_id'], item_id,
                            units, initial, initial, unit))
            inventory_id = cursor.lastrowid
            _inventory_ledger(cursor, request_id, inventory_id,
                              initial, Decimal('0'), initial, unit)
        database.connection.commit()
        flash('所選產品已加入客戶寄店庫存', 'success')
    except MySQLdb.IntegrityError as exc:
        database.connection.rollback()
        if _duplicate_inventory_request(exc):
            flash('此筆寄店操作已處理，沒有重複加入', 'info')
        else:
            current_app.logger.exception(
                'Deposit failed for customer %s', customer_id)
            flash('寄店新增失敗，請查看伺服器紀錄', 'error')
    except ValueError as exc:
        database.connection.rollback()
        flash(str(exc), 'error')
    except Exception:
        database.connection.rollback()
        current_app.logger.exception(
            'Deposit failed for customer %s', customer_id)
        flash('寄店新增失敗，請查看伺服器紀錄', 'error')
    finally:
        cursor.close()
    return _inventory_form_redirect(customer_id)


@admin_bp.route('/customer/<int:customer_id>/inventory/deduct', methods=['POST'])
@staff_required
def deduct_customer_inventory(customer_id):
    # Record multiple course-end consumptions as one atomic, idempotent POST.
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    booking_id = request.form.get('booking_id', type=int)
    try:
        key = _request_key(request.form)
        date_raw = (request.form.get('usage_date') or '').strip()
        try:
            used_on = datetime.strptime(date_raw, '%Y-%m-%d').date()
        except ValueError:
            raise ValueError('請輸入有效使用日期')
        if used_on > _taipei_today():
            raise ValueError('使用日期不可晚於今日')
        if not booking_id:
            raise ValueError('必須選擇已完成的課程預約')
        selected = request.form.getlist('inv_ids[]')
        if not selected or len(selected) > 100:
            raise ValueError('請選擇要扣除的寄店產品')
        deduction_map = {}
        for raw_id in selected:
            try:
                inv_id = int(raw_id)
            except (ValueError, TypeError):
                raise ValueError('寄店產品編號不正確')
            if inv_id <= 0 or inv_id in deduction_map:
                raise ValueError('扣料項目重複或無效')
            raw_amount = (request.form.get(f'amount_{inv_id}') or '').strip()
            if not raw_amount:
                continue
            deduction_map[inv_id] = _positive_decimal(raw_amount, '扣除容量')
        if not deduction_map:
            raise ValueError('請填寫至少一項扣除容量')
        notes = (request.form.get('notes') or '').strip()[:500]
        database.connection.begin()
        cursor.execute('''SELECT b.id,c.uses_store_consumables,b.course_purchase_id
            FROM bookings b JOIN courses c ON c.id=b.course_id
            WHERE b.id=%s AND b.customer_id=%s AND b.status='completed' FOR UPDATE''',
            (booking_id, customer_id))
        booking = cursor.fetchone()
        if not booking:
            raise ValueError('預約不存在、未完成或不是此客戶的課程')
        if booking['uses_store_consumables'] or booking['course_purchase_id']:
            raise ValueError('此課程使用店內耗材或已購堂數，不應扣除客戶寄店產品')
        operation_id = _inventory_request(cursor, customer_id, 'deduct', key,
                                          booking_id, used_on, notes)
        for inv_id in sorted(deduction_map):
            amount = deduction_map[inv_id]
            cursor.execute('''SELECT id, remaining_amount, capacity_unit
                              FROM customer_inventory
                              WHERE id=%s AND customer_id=%s FOR UPDATE''', (inv_id, customer_id))
            record = cursor.fetchone()
            if not record or record['capacity_unit'] not in ('ml', 'g'):
                raise ValueError('寄店產品不存在或尚未完成容量單位核對')
            before = record['remaining_amount']
            if before < amount:
                raise ValueError('寄店剩餘容量不足；請重新整理後確認')
            cursor.execute('''UPDATE customer_inventory
                SET remaining_amount=remaining_amount-%s, updated_at=NOW()
                WHERE id=%s AND customer_id=%s AND remaining_amount >= %s''',
                           (amount, inv_id, customer_id, amount))
            if cursor.rowcount != 1:
                raise ValueError('寄店容量已被其他人更新，請重新整理')
            _inventory_ledger(cursor, operation_id, inv_id, -amount, before,
                              before-amount, record['capacity_unit'])
        database.connection.commit()
        flash('本次課程扣料已儲存，剩餘容量已同步更新', 'success')
    except MySQLdb.IntegrityError as exc:
        database.connection.rollback()
        if _duplicate_inventory_request(exc):
            flash('此筆扣料操作已處理，沒有再次扣除', 'info')
        else:
            current_app.logger.exception(
                'Deduct failed for customer %s', customer_id)
            flash('扣料失敗，請查看伺服器紀錄', 'error')
    except ValueError as exc:
        database.connection.rollback()
        flash(str(exc), 'error')
    except Exception:
        database.connection.rollback()
        current_app.logger.exception(
            'Deduct failed for customer %s', customer_id)
        flash('扣料失敗，請查看伺服器紀錄', 'error')
    finally:
        cursor.close()
    return _inventory_form_redirect(customer_id, booking_id)


@admin_bp.route('/customer/<int:customer_id>/inventory/<int:inv_id>/adjust', methods=['POST'])
@admin_required
def adjust_customer_inventory(customer_id, inv_id):
    # Explicit corrective adjustment, never overwrite the prior ledger history.
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        key = _request_key(request.form)
        new_raw = (request.form.get('new_remaining') or '').strip()
        if not re.fullmatch(r'\d{1,8}(?:\.\d{1,2})?', new_raw):
            raise ValueError('更正剩餘容量格式不正確')
        new_amount = Decimal(new_raw)
        if new_amount > Decimal('99999999.99'):
            raise ValueError('更正剩餘容量超出範圍')
        reason = (request.form.get('reason') or '').strip()
        if len(reason) < 3 or len(reason) > 500:
            raise ValueError('請填寫至少 3 字的更正原因（最多 500 字）')
        database.connection.begin()
        op_id = _inventory_request(
            cursor, customer_id, 'adjust', key, notes=reason)
        cursor.execute('''SELECT original_amount, remaining_amount, capacity_unit
                          FROM customer_inventory WHERE id=%s AND customer_id=%s
                          FOR UPDATE''', (inv_id, customer_id))
        record = cursor.fetchone()
        if not record or record['capacity_unit'] not in ('ml', 'g'):
            raise ValueError('找不到可更正的寄店產品')
        before = record['remaining_amount']
        if new_amount > record['original_amount']:
            raise ValueError('剩餘容量不能高於此批寄店原始容量')
        if new_amount == before:
            raise ValueError('更正後容量與原值相同，沒有需要儲存的異動')
        cursor.execute('''UPDATE customer_inventory SET remaining_amount=%s,
                          updated_at=NOW() WHERE id=%s AND customer_id=%s''',
                       (new_amount, inv_id, customer_id))
        _inventory_ledger(cursor, op_id, inv_id, new_amount-before, before,
                          new_amount, record['capacity_unit'])
        database.connection.commit()
        flash('寄店剩餘容量已更正並保留稽核紀錄', 'success')
    except MySQLdb.IntegrityError as exc:
        database.connection.rollback()
        if _duplicate_inventory_request(exc):
            flash('此筆更正已處理，沒有重複調整', 'info')
        else:
            current_app.logger.exception(
                'Adjust failed for customer %s', customer_id)
            flash('寄店更正失敗，請查看伺服器紀錄', 'error')
    except ValueError as exc:
        database.connection.rollback()
        flash(str(exc), 'error')
    except Exception:
        database.connection.rollback()
        current_app.logger.exception(
            'Adjust failed for customer %s', customer_id)
        flash('寄店更正失敗，請查看伺服器紀錄', 'error')
    finally:
        cursor.close()
    return _inventory_form_redirect(customer_id)


@admin_bp.route('/customer/<int:customer_id>/stored-value/add', methods=['POST'])
@staff_required
def add_customer_stored_value(customer_id):
    """Staff or admin may add credit; never directly edit the balance."""
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        operation_key = (request.form.get('request_key') or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{24,64}', operation_key):
            raise ValueError('儲值請求識別碼無效，請重新開啟客戶頁面')
        amount = money(request.form.get('amount'))
        if amount <= 0:
            raise ValueError('儲值金額必須大於零')
        if amount > Decimal('99999999.99'):
            raise ValueError('單筆儲值金額過大')
        note = (request.form.get('notes') or '').strip()
        if len(note) > 500:
            raise ValueError('備註不得超過 500 字')
        cursor.execute(
            "SELECT id FROM users WHERE id=%s AND role='customer'", (customer_id,))
        if not cursor.fetchone():
            raise ValueError('客戶不存在')
        change_balance(cursor, customer_id, amount, 'topup',
                       get_current_user_id(), notes=note, request_key=operation_key)
        database.connection.commit()
        flash('客戶儲值已成功入帳', 'success')
    except Exception as exc:
        database.connection.rollback()
        flash(f'儲值失敗：{exc}', 'error')
    finally:
        cursor.close()
    return redirect(url_for('admin.customer_detail', customer_id=customer_id))


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
                (title, content, summary, status,
                 author_id, image, created_at, updated_at)
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
        event_ids = list(dict.fromkeys(int(x)
                         for x in request.form.getlist('event_ids[]') if x))
        operation_key = (request.form.get('request_key') or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{24,64}', operation_key):
            raise ValueError('訂單請求識別碼無效，請重新開啟訂單頁面')
        use_stored_value = money(
            request.form.get('stored_value_amount') or '0')
        other_payment_method = request.form.get(
            'other_payment_method') or 'cash'
        if other_payment_method not in ('cash', 'credit_card', 'bank_transfer', 'other'):
            raise ValueError('付款方式無效')
        if use_stored_value < 0:
            raise ValueError('儲值扣款不能是負數')

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

            price = money(prices[i])
            if price < 0:
                raise ValueError('產品單價不得小於零')
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

        # 鎖定此客戶的儲值餘額，與建立訂單及扣庫存共享同一交易。
        total_amount = money(total_amount)
        if use_stored_value > total_amount:
            raise ValueError('儲值扣款超過訂單金額')
        current_balance = ensure_wallet(cursor, int(customer_id))
        if use_stored_value > current_balance:
            raise ValueError('儲值餘額不足')
        other_amount = total_amount - use_stored_value
        payment_method = ('stored_value' if other_amount == 0 else
                          'mixed' if use_stored_value > 0 else other_payment_method)

        # 3. 寫入訂單主檔
        status = 'confirmed'
        cursor.execute("""
            INSERT INTO orders (customer_id,total_amount,status,created_at,
                                stored_value_amount,other_payment_amount,other_payment_method,payment_method,request_key)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (customer_id, total_amount, status, created_at, use_stored_value,
              other_amount, other_payment_method if other_amount > 0 else None, payment_method, operation_key))
        order_id = cursor.lastrowid
        if use_stored_value > 0:
            change_balance(cursor, int(customer_id), -use_stored_value, 'spend',
                           get_current_user_id(), order_id, 1, '新訂單儲值扣款')
            cursor.execute(
                'UPDATE orders SET financial_revision=1 WHERE id=%s', (order_id,))
        if event_ids:
            placeholders = ','.join(['%s'] * len(event_ids))
            cursor.execute(
                f'SELECT id FROM events WHERE is_archived=0 AND id IN ({placeholders})', tuple(event_ids))
            if len(cursor.fetchall()) != len(event_ids):
                raise ValueError('所選活動不存在')
            for event_id in event_ids:
                cursor.execute('INSERT INTO order_events (order_id,event_id) VALUES (%s,%s)',
                               (order_id, event_id))

        # 4. 寫入訂單項目 & 扣庫存 & 寫入 Log
        for item in items_to_process:
            # 寫入項目
            cursor.execute("""
                INSERT INTO order_items (order_id, product_id, quantity, unit_price, subtotal)
                VALUES (%s, %s, %s, %s, %s)
            """, (order_id, item['product_id'], item['quantity'], item['price'], item['subtotal']))

            # 原子性扣庫存，並發訂單與同商品多筆項目也不能造成負庫存。
            cursor.execute("""
                UPDATE products SET stock_quantity = stock_quantity - %s
                WHERE id = %s AND stock_quantity >= %s
            """, (item['quantity'], item['product_id'], item['quantity']))
            if cursor.rowcount != 1:
                raise ValueError(f'商品 ID {item["product_id"]} 庫存不足或產品不存在')

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
                notify_order_confirmed(order_id, customer_data, total_amount,
                                       use_stored_value, other_amount, other_payment_method if other_amount else None)
                flash('訂單已建立並發送通知', 'success')
            except Exception as e:
                flash('訂單建立成功，但通知發送失敗', 'warning')
        else:
            flash('訂單已補登', 'success')

        # Notification/audit failure must not report a committed order as failed.
        try:
            log_activity('create', 'order', order_id, {
                         'type': 'manual_admin', 'amount': str(total_amount)})
        except Exception:
            current_app.logger.warning(
                'Manual order audit log failed for order %s', order_id)

    except Exception as e:
        database.connection.rollback()
        flash(f'建立失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='orders'))


@admin_bp.route('/order/<int:order_id>/events', methods=['POST'])
@staff_required
def update_order_events(order_id):
    """編輯訂單關聯活動（可選零至多個），不修改原有訂單金額或狀態。"""
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        ids = list(dict.fromkeys(int(v)
                   for v in request.form.getlist('event_ids[]') if v))
        cursor.execute(
            'SELECT id FROM orders WHERE id=%s AND deleted_at IS NULL FOR UPDATE', (order_id,))
        if not cursor.fetchone():
            raise ValueError('訂單不存在')
        # 保留舊訂單已關聯的封存活動，但不允許新加入封存活動。
        cursor.execute('''SELECT oe.event_id FROM order_events oe
                          JOIN events e ON e.id=oe.event_id
                          WHERE oe.order_id=%s AND e.is_archived=1''', (order_id,))
        archived_ids = [row['event_id'] for row in cursor.fetchall()]
        if ids:
            placeholders = ','.join(['%s'] * len(ids))
            cursor.execute(
                f'SELECT id FROM events WHERE is_archived=0 AND id IN ({placeholders})', tuple(ids))
            if len(cursor.fetchall()) != len(ids):
                raise ValueError('活動選項包含已刪除或已封存的活動')
        cursor.execute(
            'DELETE FROM order_events WHERE order_id=%s', (order_id,))
        for event_id in archived_ids + ids:
            cursor.execute(
                'INSERT INTO order_events(order_id,event_id) VALUES(%s,%s)', (order_id, event_id))
        database.connection.commit()
        flash('訂單相關活動已儲存', 'success')
    except (ValueError, TypeError) as e:
        database.connection.rollback()
        flash(f'更新失敗：{e}', 'error')
    except Exception:
        database.connection.rollback()
        raise
    finally:
        cursor.close()
    return redirect(url_for('admin.dashboard', tab='orders'))


def _manual_payment_entries(raw, item_type, total, service_fee, cursor, customer_id):
    '''Validate independent payment lines server-side; never trust JS totals.'''
    if not raw or len(raw) > 6000:
        raise ValueError('付款明細不存在或過長，請重新開啟表單')
    try:
        entries = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError('付款明細格式不正確') from exc
    if not isinstance(entries, list) or len(entries) > 20:
        raise ValueError('單項目付款方式最多 20 筆')
    allowed = {'cash', 'credit_card', 'bank_transfer', 'other', 'stored_value', 'deposit_credit'}
    result = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get('method') not in allowed:
            raise ValueError('包含不支援的付款方式')
        # Save only positive payment amounts. Zero lines are UI placeholders.
        amount = money(entry.get('amount', '0'))
        if amount < 0 or amount != amount.to_integral_value():
            raise ValueError('每種付款方式的金額須為非負整數（元）')
        if amount == 0:
            continue
        method = entry['method']
        if method == 'deposit_credit':
            if item_type != 'course':
                raise ValueError('寄店產品抵扣只能用於課程，不可直接抵扣加購商品')
            if service_fee <= 0:
                raise ValueError('使用寄店產品抵扣時，請先選擇手技費')
        result.append((method, amount))
    if sum((a for _, a in result), Decimal('0')) > total:
        raise ValueError('各付款方式與寄店抵扣合計不得超過本項目總額')
    deposit_amount = sum((a for m, a in result if m == 'deposit_credit'), Decimal('0'))
    if deposit_amount > 0:
        if deposit_amount > total - service_fee:
            raise ValueError('寄店產品抵扣不得超過課程總價扣除手技費的部分')
        cursor.execute('''SELECT id FROM customer_inventory
                          WHERE customer_id=%s AND remaining_amount > 0
                            AND capacity_unit IN ('ml','g') LIMIT 1''', (customer_id,))
        if not cursor.fetchone():
            raise ValueError('此客戶沒有可用的寄店產品，不能建立寄店抵扣')
    return result


def _manual_payment_summary(entries, total):
    stored = sum((a for m, a in entries if m == 'stored_value'), Decimal('0'))
    deposit = sum((a for m, a in entries if m == 'deposit_credit'), Decimal('0'))
    offline = [(m, a) for m, a in entries if m not in ('stored_value', 'deposit_credit')]
    paid_other = sum((a for _, a in offline), Decimal('0'))
    remaining = total - stored - deposit - paid_other
    methods = sorted(set(m for m, _ in entries))
    method = methods[0] if len(methods) == 1 else ('mixed' if methods else 'offline')
    other_method = offline[0][0] if len(set(m for m, _ in offline)) == 1 else ('mixed' if offline else None)
    return stored, deposit, paid_other, remaining, method, other_method


@admin_bp.route('/booking/add-manual', methods=['POST'])
@staff_required
def add_booking_manual():
    # Create multiple bookings/products with itemized payments in ONE atomic transaction.

    # A deposit credit is provisional until a completed course's g/ml use is recorded;
    # It does NOT consume customer_inventory during booking creation.
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        key = (request.form.get('booking_request_key') or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{20,64}', key):
            raise ValueError('表單已過期，請重新整理後再建立預約')
        raw_rows = request.form.get('manual_rows_json') or ''
        if not raw_rows or len(raw_rows) > 50000:
            raise ValueError('預約付款明細不完整，請重新整理後操作')
        try:
            rows = json.loads(raw_rows)
        except json.JSONDecodeError as exc:
            raise ValueError('預約付款資料格式不正確') from exc
        if not isinstance(rows, list) or not (1 <= len(rows) <= 50):
            raise ValueError('請建立 1～50 筆課程或產品')
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError('預約表單列格式不正確')
        if any(row.get('item_type') == 'course' for row in rows):
            raise ValueError('06 版課程須先販售或建立純預約，舊版直接收費預約已停用')
        if any(v and v != '[]' for v in request.form.getlist('inv_jsons[]')):
            raise ValueError('寄店容量必須在課程完成後登記，不可於預約時扣除')

        actor = get_current_user_id()
        if not actor:
            raise ValueError('找不到目前操作人員')
        database.connection.begin()
        cursor.execute('''INSERT INTO manual_checkout_requests(request_key, operated_by)
                          VALUES (%s, %s)''', (key, actor))
        request_id = cursor.lastrowid
        count = 0
        for i, row in enumerate(rows):
            item_raw = row.get('item_id')
            c_id_raw = row.get('customer_id')
            if not item_raw or not c_id_raw:
                raise ValueError(f'第 {i + 1} 筆缺少客戶或產品／課程')
            try:
                customer_id = int(c_id_raw); item_id = int(item_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f'第 {i + 1} 筆項目編號不正確') from exc
            if customer_id <= 0 or item_id <= 0:
                raise ValueError('客戶或項目編號不正確')
            cursor.execute("SELECT id FROM users WHERE id=%s AND role='customer'", (customer_id,))
            if not cursor.fetchone():
                raise ValueError('客戶不存在或不是客戶帳號')
            kind = row.get('item_type')
            if kind not in ('course', 'product'):
                raise ValueError('項目類型不支援')
            first_time = row.get('is_first_time') is True
            fee_id = None
            fee_amount = Decimal('0')
            if kind == 'course':
                cursor.execute('''SELECT regular_price, experience_price, uses_store_consumables FROM courses
                                  WHERE id=%s AND is_active=1''', (item_id,))
                course = cursor.fetchone()
                if not course:
                    raise ValueError('課程不存在或已下架')
                reg = money(course['regular_price'])
                exp = money(course['experience_price']) if course['experience_price'] is not None else None
                total = exp if first_time and exp is not None and exp > 0 else reg
                if row.get('service_fee_id'):
                    fee_id = int(row['service_fee_id'])
                    cursor.execute('SELECT price FROM service_fees WHERE id=%s AND is_active=1', (fee_id,))
                    fee_row = cursor.fetchone()
                    if not fee_row:
                        raise ValueError('手技費選項不存在或已停用')
                    fee_amount = money(fee_row['price'])
                if fee_amount > total:
                    raise ValueError('手技費不可高於課程總價')
                if not row.get('appointment_time'):
                    raise ValueError('請填寫預約時間')
                appt = datetime.strptime(row['appointment_time'], '%Y-%m-%dT%H:%M')
            else:
                if row.get('service_fee_id') or row.get('appointment_time') or first_time:
                    raise ValueError('產品列不應有課程欄位')
                cursor.execute('SELECT price FROM products WHERE id=%s AND is_active=1', (item_id,))
                product = cursor.fetchone()
                if not product:
                    raise ValueError('產品不存在或已下架')
                # Manual product prices were already editable in the existing checkout.
                total = money(row.get('amount'))
                if total <= 0 or total != total.to_integral_value():
                    raise ValueError('加購產品金額必須是正整數（元）')
            lines = _manual_payment_entries(json.dumps(row.get('payments')), kind, total,
                                            fee_amount, cursor, customer_id)
            stored, deposit, other, due, pay_method, other_method = _manual_payment_summary(lines, total)
            if kind == 'course' and course['uses_store_consumables'] and deposit:
                raise ValueError('使用店內耗材的套裝課程，不可另以客戶寄店產品抵扣')
            if kind == 'course':
                cursor.execute('''INSERT INTO bookings
                    (customer_id, course_id, total_amount, is_first_time,
                     sessions_purchased, sessions_remaining, status, created_at,
                     payment_method, stored_value_amount, other_payment_amount,
                     other_payment_method, service_fee_id, service_fee_amount,
                     product_fee_amount, deposit_credit_amount, amount_due)
                    VALUES (%s,%s,%s,%s,1,1,'confirmed',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                    (customer_id, item_id, total, first_time, appt, pay_method,
                     stored, other, other_method, fee_id, fee_amount,
                     total - fee_amount, deposit, due))
                ref_id = cursor.lastrowid
                end_time = appt + timedelta(minutes=60)
                cursor.execute('''INSERT INTO shop_schedules
                    (start_time,end_time,max_capacity,current_bookings,is_active)
                    VALUES (%s,%s,1,1,1)
                    ON DUPLICATE KEY UPDATE current_bookings=current_bookings+1''',
                    (appt, end_time))
                cursor.execute('SELECT id FROM shop_schedules WHERE start_time=%s ORDER BY id LIMIT 1', (appt,))
                slot = cursor.fetchone()
                if slot:
                    cursor.execute('UPDATE bookings SET global_schedule_id=%s WHERE id=%s', (slot['id'], ref_id))
            else:
                # Outstanding purchases remain pending rather than falsely 'completed'.
                status = 'completed' if due == 0 else 'pending'
                cursor.execute('''INSERT INTO orders
                    (customer_id,total_amount,status,created_at,stored_value_amount,
                     other_payment_amount,other_payment_method,payment_method,request_key,amount_due)
                    VALUES (%s,%s,%s,NOW(),%s,%s,%s,%s,%s,%s)''',
                    (customer_id,total,status,stored,other,other_method,pay_method,
                     f'{key}:{i}' if len(key) + len(str(i)) + 1 <= 64 else None, due))
                ref_id = cursor.lastrowid
                cursor.execute('''INSERT INTO order_items
                    (order_id,product_id,quantity,unit_price,subtotal)
                    VALUES (%s,%s,1,%s,%s)''', (ref_id,item_id,total,total))
                cursor.execute('''UPDATE products SET stock_quantity=stock_quantity-1,
                    last_sale_date=NOW() WHERE id=%s AND stock_quantity >= 1''', (item_id,))
                if cursor.rowcount != 1:
                    raise ValueError('產品庫存不足，無法建立加購訂單')
                cursor.execute('''INSERT INTO inventory_logs
                    (product_id,change_amount,change_type,reference_id,notes,created_by)
                    VALUES (%s,-1,'sale',%s,'Admin Manual Booking (Product)',%s)''',
                    (item_id,ref_id,actor))
            for method, amount in lines:
                line_status = 'pending_reconciliation' if method == 'deposit_credit' else 'recorded'
                cursor.execute('''INSERT INTO manual_checkout_payments
                    (request_id,booking_id,order_id,method,amount,status,operated_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)''',
                    (request_id,ref_id if kind == 'course' else None,
                     ref_id if kind == 'product' else None,method,amount,line_status,actor))
            if stored > 0:
                change_balance(cursor,customer_id,-stored,'spend',actor,
                               ref_id if kind == 'product' else None,
                               1 if kind == 'product' else None,
                               f'後台手動{("課程預約" if kind == "course" else "產品訂單")} #{ref_id} 儲值扣款')
                if kind == 'product':
                    cursor.execute('UPDATE orders SET financial_revision=1 WHERE id=%s', (ref_id,))
            # Insert audit using the caller's cursor: log_activity() commits independently.
            cursor.execute('''INSERT INTO audit_logs
                (user_id,action,target_type,target_id,details,ip_address)
                VALUES (%s,'create',%s,%s,%s,%s)''',
                (actor,'booking' if kind == 'course' else 'order',ref_id,
                 json.dumps({'type':'manual_mixed_checkout','total':str(total),
                             'stored_value':str(stored),'deposit_credit_pending':str(deposit),
                             'other_paid':str(other),'due':str(due),
                             'payment_methods':[m for m,_ in lines]},ensure_ascii=False),
                 request.remote_addr))
            count += 1
        database.connection.commit()
        flash(f'成功建立 {count} 筆紀錄；寄店抵扣部分仍待課程完成後核銷', 'success')
    except MySQLdb.IntegrityError as exc:
        database.connection.rollback()
        if exc.args and exc.args[0] == 1062:
            flash('這份預約單已提交過，沒有重複建立；請查看預約管理', 'info')
        else:
            current_app.logger.exception('Manual checkout database error')
            flash('建立失敗：資料庫約束檢查未通過', 'error')
    except (ValueError, TypeError) as exc:
        database.connection.rollback()
        flash(f'建立失敗：{exc}', 'error')
    except Exception:
        database.connection.rollback()
        current_app.logger.exception('Manual checkout failed')
        flash('建立失敗，已取消整筆交易，請查看伺服器紀錄', 'error')
    finally:
        cursor.close()
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


# =====================================================
# DELETE ORDERS & BOOKINGS (刪除功能)
# =====================================================

@admin_bp.route('/order/<int:order_id>/delete', methods=['POST'])
@staff_required
def delete_order(order_id):
    """Soft delete only; cancel reverses inventory and prepaid amounts atomically."""
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        order = lock_order(cursor, order_id)
        archive_order(cursor, order, get_current_user_id())
        database.connection.commit()
        try:
            log_activity('archive', 'order', order_id)
        except Exception:
            current_app.logger.warning(
                'Archive audit notification failed for order %s', order_id)
        flash('訂單已封存；訂單、庫存與儲值流水均保留', 'success')
    except Exception as exc:
        database.connection.rollback()
        flash(f'封存訂單失敗：{exc}', 'error')
    finally:
        cursor.close()
    return redirect(url_for('admin.dashboard', tab='orders'))


@admin_bp.route('/booking/<int:booking_id>/delete', methods=['POST'])
@staff_required
def delete_booking(booking_id):
    """永久刪除預約紀錄"""
    try:
        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

        # 1. 查詢該預約是否有佔用「全店共用排班表 (shop_schedules)」
        cursor.execute(
            "SELECT global_schedule_id,course_purchase_id FROM bookings WHERE id = %s FOR UPDATE", (booking_id,))
        booking = cursor.fetchone()
        if booking and booking.get('course_purchase_id'):
            raise ValueError('已購課程核銷預約不得永久刪除，請透過狀態取消釋放堂數')

        # 2. 如果有綁定時段，把該時段的「已預約人數」扣回來，釋放名額
        if booking and booking.get('global_schedule_id'):
            cursor.execute("""
                UPDATE shop_schedules 
                SET current_bookings = GREATEST(0, current_bookings - 1) 
                WHERE id = %s
            """, (booking['global_schedule_id'],))

        # 3. 永久刪除預約紀錄
        cursor.execute("DELETE FROM bookings WHERE id = %s", (booking_id,))

        database.connection.commit()
        cursor.close()

        log_activity('delete', 'booking', booking_id)
        flash('預約紀錄已永久刪除', 'success')

    except Exception as e:
        database.connection.rollback()
        flash(f'刪除預約失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='bookings'))

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

    # =====================================================
# HR & SERVICE FEE MANAGEMENT
# =====================================================


@admin_bp.route('/service-fee/add', methods=['POST'])
@staff_required
def add_service_fee():
    name = request.form.get('name')
    price = request.form.get('price', type=float) or 0.0
    cursor = database.connection.cursor()
    cursor.execute(
        "INSERT INTO service_fees (name, price) VALUES (%s, %s)", (name, price))
    database.connection.commit()
    cursor.close()
    flash('手技費新增成功', 'success')
    return redirect(url_for('admin.dashboard', tab='service_fees'))


@admin_bp.route('/service-fee/<int:fee_id>/delete', methods=['POST'])
@staff_required
def delete_service_fee(fee_id):
    cursor = database.connection.cursor()
    cursor.execute(
        "UPDATE service_fees SET is_active = 0 WHERE id = %s", (fee_id,))
    database.connection.commit()
    cursor.close()
    flash('手技費已停用', 'success')
    return redirect(url_for('admin.dashboard', tab='service_fees'))


@admin_bp.route('/employee/<int:emp_id>/detail')
@admin_required
def employee_detail(emp_id):
    """Admin only: employee data, salary and verifiable audit actions."""
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        # Keep historical created_at / updated_at untouched. Employment dates
        # are independent fields added by the accompanying SQL migration.
        cursor.execute("SHOW COLUMNS FROM users LIKE 'job_title'")
        job_title_column = ', job_title' if cursor.fetchone() else ''
        cursor.execute("SHOW COLUMNS FROM users LIKE 'hire_date'")
        hire_date_exists = cursor.fetchone() is not None
        cursor.execute("SHOW COLUMNS FROM users LIKE 'termination_date'")
        termination_date_exists = cursor.fetchone() is not None
        employment_dates_available = hire_date_exists and termination_date_exists
        hire_date_column = ', hire_date' if hire_date_exists else ', NULL AS hire_date'
        termination_date_column = (
            ', termination_date' if termination_date_exists
            else ', NULL AS termination_date'
        )

        cursor.execute(f"""
            SELECT id, username, firstname, surname, email, phone,
                   gender, birth_date, occupation, line_id, address,
                   notes, role, created_at, updated_at{job_title_column}
                   {hire_date_column}{termination_date_column}
            FROM users
            WHERE id = %s AND role IN ('admin', 'staff')
        """, (emp_id,))
        employee = cursor.fetchone()
        if employee is None:
            flash('找不到該員工', 'error')
            return redirect(url_for('admin.dashboard', tab='employees'))

        cursor.execute("SHOW TABLES LIKE %s", ('employee_salaries',))
        salary_table_exists = cursor.fetchone() is not None
        salary_history = []
        if salary_table_exists:
            cursor.execute("""
                SELECT salary_month, base_salary, personal_bonus, team_bonus,
                       other_bonus_name, other_bonus_amount, total_salary
                FROM employee_salaries
                WHERE user_id = %s
                ORDER BY salary_month DESC
            """, (emp_id,))
            salary_history = cursor.fetchall()

        # Audit attribution means this employee acted on the record. It does
        # NOT establish permanent sales ownership or customer assignment.
        cursor.execute("SHOW TABLES LIKE %s", ('audit_logs',))
        audit_table_exists = cursor.fetchone() is not None
        order_operations = []
        booking_operations = []
        handled_customers = []
        audit_totals = {'order': {'actions': 0, 'records': 0},
                        'booking': {'actions': 0, 'records': 0}}
        if audit_table_exists:
            cursor.execute("""
                SELECT target_type, COUNT(*) AS action_count,
                       COUNT(DISTINCT target_id) AS record_count
                FROM audit_logs
                WHERE user_id=%s AND target_type IN ('order', 'booking')
                GROUP BY target_type
            """, (emp_id,))
            for item in cursor.fetchall():
                audit_totals[item['target_type']] = {
                    'actions': item['action_count'],
                    'records': item['record_count']
                }

            cursor.execute("""
                SELECT a.id AS audit_id, a.action, a.details,
                       a.created_at AS operated_at, a.target_id AS order_id,
                       o.total_amount, o.status, o.created_at AS order_created_at,
                       o.deleted_at, c.id AS customer_id, c.firstname, c.surname
                FROM audit_logs a
                LEFT JOIN orders o ON o.id = a.target_id
                LEFT JOIN users c ON c.id = o.customer_id
                WHERE a.user_id=%s AND a.target_type='order'
                ORDER BY a.created_at DESC, a.id DESC
                LIMIT 100
            """, (emp_id,))
            order_operations = cursor.fetchall()

            cursor.execute("""
                SELECT a.id AS audit_id, a.action, a.details,
                       a.created_at AS operated_at, a.target_id AS booking_id,
                       b.total_amount, b.status, b.sessions_purchased,
                       c.id AS customer_id, c.firstname, c.surname,
                       co.name AS course_name,
                       COALESCE(s.start_time, b.booking_date) AS appointment_at
                FROM audit_logs a
                LEFT JOIN bookings b ON b.id = a.target_id
                LEFT JOIN users c ON c.id = b.customer_id
                LEFT JOIN courses co ON co.id = b.course_id
                LEFT JOIN shop_schedules s ON s.id = b.global_schedule_id
                WHERE a.user_id=%s AND a.target_type='booking'
                ORDER BY a.created_at DESC, a.id DESC
                LIMIT 100
            """, (emp_id,))
            booking_operations = cursor.fetchall()

            # Distinct customers appearing in transactions with recorded actions.
            # Customer contact data is not duplicated into the audit table.
            cursor.execute("""
                SELECT c.id, c.firstname, c.surname
                FROM users c
                JOIN (
                    SELECT o.customer_id AS customer_id
                    FROM audit_logs a JOIN orders o ON o.id=a.target_id
                    WHERE a.user_id=%s AND a.target_type='order'
                    UNION
                    SELECT b.customer_id AS customer_id
                    FROM audit_logs a JOIN bookings b ON b.id=a.target_id
                    WHERE a.user_id=%s AND a.target_type='booking'
                ) handled ON handled.customer_id=c.id
                ORDER BY c.surname, c.firstname, c.id
                LIMIT 100
            """, (emp_id, emp_id))
            handled_customers = cursor.fetchall()
    finally:
        cursor.close()

    return render_template(
        'admin_employee_detail.html',
        employee=employee,
        employment_dates_available=employment_dates_available,
        salary_history=salary_history,
        salary_table_exists=salary_table_exists,
        audit_table_exists=audit_table_exists,
        audit_totals=audit_totals,
        order_operations=order_operations,
        booking_operations=booking_operations,
        handled_customers=handled_customers
    )


@admin_bp.route('/employee/<int:emp_id>/employment-dates', methods=['POST'])
@admin_required
def update_employee_employment_dates(emp_id):
    """Update actual employment dates without overwriting account timestamps."""
    def parse_optional_date(field_name, label):
        raw = request.form.get(field_name, '').strip()
        if not raw:
            return None
        try:
            return datetime.strptime(raw, '%Y-%m-%d').date()
        except ValueError:
            raise ValueError(f'{label}必須是有效的 YYYY-MM-DD 日期')

    try:
        hire_date = parse_optional_date('hire_date', '入職日期')
        termination_date = parse_optional_date('termination_date', '離職日期')
        if hire_date and termination_date and termination_date < hire_date:
            raise ValueError('離職日期不得早於入職日期')

        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
        try:
            cursor.execute("SHOW COLUMNS FROM users LIKE 'hire_date'")
            has_hire_date = cursor.fetchone() is not None
            cursor.execute("SHOW COLUMNS FROM users LIKE 'termination_date'")
            has_termination_date = cursor.fetchone() is not None
            if not (has_hire_date and has_termination_date):
                raise ValueError('資料庫尚未新增入職日期／離職日期欄位，請先執行 Migration')
            cursor.execute("""
                SELECT id FROM users
                WHERE id=%s AND role IN ('admin', 'staff')
            """, (emp_id,))
            if not cursor.fetchone():
                raise ValueError('找不到該員工')
            cursor.execute("""
                UPDATE users SET hire_date=%s, termination_date=%s
                WHERE id=%s AND role IN ('admin', 'staff')
            """, (hire_date, termination_date, emp_id))
            database.connection.commit()
        finally:
            cursor.close()
        try:
            log_activity('update', 'employee', emp_id, {
                'fields': ['hire_date', 'termination_date']
            })
        except Exception:
            current_app.logger.warning(
                'Employment date audit failed for employee %s', emp_id)
        flash('入職／離職日期已更新', 'success')
    except ValueError as exc:
        flash(str(exc), 'error')
    except Exception:
        database.connection.rollback()
        current_app.logger.exception('Updating employment dates failed')
        flash('儲存入職／離職日期失敗，請查看伺服器紀錄', 'error')
    return redirect(url_for('admin.employee_detail', emp_id=emp_id))


@admin_bp.route('/employee/<int:emp_id>/salary', methods=['POST'])
@admin_required
def update_employee_salary(emp_id):
    """更新或新增員工當月薪資"""
    month = request.form.get('salary_month')  # YYYY-MM
    base = request.form.get('base_salary', type=float) or 0
    personal = request.form.get('personal_bonus', type=float) or 0
    team = request.form.get('team_bonus', type=float) or 0
    other_name = request.form.get('other_bonus_name', '')
    other_amount = request.form.get('other_bonus_amount', type=float) or 0

    total = base + personal + team + other_amount

    cursor = database.connection.cursor()
    cursor.execute("""
        INSERT INTO employee_salaries 
        (user_id, salary_month, base_salary, personal_bonus, team_bonus, other_bonus_name, other_bonus_amount, total_salary)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE 
        base_salary=%s, personal_bonus=%s, team_bonus=%s, other_bonus_name=%s, other_bonus_amount=%s, total_salary=%s
    """, (emp_id, month, base, personal, team, other_name, other_amount, total,
          base, personal, team, other_name, other_amount, total))
    database.connection.commit()
    cursor.close()

    flash('薪資結算已更新', 'success')
    return redirect(url_for('admin.dashboard', tab='employees'))


@admin_bp.route('/employee/<int:emp_id>/salary/history/update', methods=['POST'])
@admin_required
def recalculate_employee_salary(emp_id):
    """Correct one existing monthly salary record; do not create a duplicate."""
    month = (request.form.get('salary_month') or '').strip()
    if not month or len(month) > 32:
        flash('薪資月份不正確', 'error')
        return redirect(url_for('admin.employee_detail', emp_id=emp_id))

    def amount(field, label):
        raw = (request.form.get(field) or '').strip() or '0'
        try:
            parsed = Decimal(raw)
            if not parsed.is_finite() or parsed != parsed.quantize(Decimal('0.01')):
                raise ValueError()
            return parsed
        except (ArithmeticError, ValueError, TypeError):
            raise ValueError(f'{label}必須是有效金額，最多兩位小數')

    cursor = None
    try:
        base = amount('base_salary', '底薪')
        personal = amount('personal_bonus', '個人獎金')
        team = amount('team_bonus', '團體獎金')
        other_amount = amount('other_bonus_amount', '其他獎金')
        other_name = (request.form.get('other_bonus_name') or '').strip()
        total = base + personal + team + other_amount

        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("""
            SELECT id FROM users
            WHERE id=%s AND role IN ('admin', 'staff')
        """, (emp_id,))
        if cursor.fetchone() is None:
            raise ValueError('找不到該員工')

        # Scope both the lock and the update to the specific employee and month.
        cursor.execute("""
            SELECT total_salary FROM employee_salaries
            WHERE user_id=%s AND salary_month=%s FOR UPDATE
        """, (emp_id, month))
        matches = cursor.fetchall()
        if len(matches) != 1:
            raise ValueError('該月份沒有唯一的薪資紀錄，未進行修改；請先確認資料表是否有重複月份')
        previous_total = matches[0]['total_salary']

        cursor.execute("""
            UPDATE employee_salaries
            SET base_salary=%s, personal_bonus=%s, team_bonus=%s,
                other_bonus_name=%s, other_bonus_amount=%s, total_salary=%s
            WHERE user_id=%s AND salary_month=%s
        """, (base, personal, team, other_name, other_amount, total, emp_id, month))
        database.connection.commit()

        # Audit after commit; a logging problem must not erase a successful fix.
        try:
            log_activity('update', 'employee_salary', emp_id, {
                'salary_month': month,
                'previous_total': str(previous_total),
                'recalculated_total': str(total)
            })
        except Exception:
            current_app.logger.warning(
                'Salary correction audit failed for employee %s', emp_id)
        flash(f'薪資已重新核算並儲存：{month}', 'success')
    except ValueError as exc:
        database.connection.rollback()
        flash(str(exc), 'error')
    except Exception:
        database.connection.rollback()
        current_app.logger.exception('Employee salary correction failed')
        flash('薪資更新失敗，請查看伺服器紀錄', 'error')
    finally:
        if cursor is not None:
            cursor.close()

    return redirect(url_for('admin.employee_detail', emp_id=emp_id))


@admin_bp.route('/employee/<int:emp_id>/update', methods=['POST'])
@admin_required
def update_employee(emp_id):
    """Admin 修改員工基本資料與重設密碼"""
    try:
        firstname = request.form.get('firstname', '').strip()
        surname = request.form.get('surname', '').strip()
        phone = request.form.get('phone', '').strip()
        job_title = request.form.get('job_title', '').strip()
        password = request.form.get('password', '').strip()
        gender = request.form.get('gender', 'other')
        birth_date = request.form.get('birth_date') or None
        address = request.form.get('address', '').strip()
        notes = request.form.get('notes', '').strip()

        if not firstname:
            flash('名字為必填欄位', 'error')
            return redirect(url_for('admin.dashboard', tab='employees'))

        if gender not in ('male', 'female', 'other'):
            flash('性別欄位無效', 'error')
            return redirect(url_for('admin.dashboard', tab='employees'))
        if birth_date:
            try:
                datetime.strptime(birth_date, '%Y-%m-%d')
            except ValueError:
                flash('生日日期格式不正確', 'error')
                return redirect(url_for('admin.dashboard', tab='employees'))

        cursor = database.connection.cursor()

        # 若有填寫密碼，則進行安全加密並一起更新
        if password:
            hashed_password = generate_password_hash(password)
            cursor.execute("""
                UPDATE users
                SET firstname=%s, surname=%s, phone=%s, job_title=%s,
                    gender=%s, birth_date=%s, address=%s, notes=%s, password_hash=%s
                WHERE id=%s AND role IN ('staff', 'admin')
            """, (firstname, surname, phone, job_title,
                  gender, birth_date, address, notes, hashed_password, emp_id))
            flash_msg = '員工資料與密碼已成功更新！'
        else:
            # 未填寫密碼，只更新基本資料
            cursor.execute("""
                UPDATE users
                SET firstname=%s, surname=%s, phone=%s, job_title=%s,
                    gender=%s, birth_date=%s, address=%s, notes=%s
                WHERE id=%s AND role IN ('staff', 'admin')
            """, (firstname, surname, phone, job_title,
                  gender, birth_date, address, notes, emp_id))
            flash_msg = '員工基本資料已更新！'

        database.connection.commit()
        cursor.close()

        # 記錄稽核 (Audit Log)
        log_activity('update', 'employee', emp_id, {
                     'name': f"{surname}{firstname}"})
        flash(flash_msg, 'success')

    except Exception as e:
        database.connection.rollback()
        flash(f'更新失敗: {str(e)}', 'error')

    return redirect(url_for('admin.dashboard', tab='employees'))


@admin_bp.route('/api/customer/<int:customer_id>/inventory')
@staff_required
def get_customer_inventory(customer_id):
    """AJAX：動態取得客戶目前的寄店產品與剩餘量"""
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("""
        SELECT ci.id as inventory_id, p.id as product_id, p.name as product_name,
               ci.remaining_amount, ci.capacity_unit AS unit
        FROM customer_inventory ci
        JOIN products p ON ci.product_id = p.id
        WHERE ci.customer_id = %s AND ci.remaining_amount > 0
          AND ci.capacity_unit IN ('g', 'ml')
        ORDER BY ci.created_at ASC
    """, (customer_id,))
    items = cursor.fetchall()
    cursor.close()

    # 處理 Decimal 轉 float，避免 JSON 報錯
    for item in items:
        if isinstance(item['remaining_amount'], Decimal):
            item['remaining_amount'] = float(item['remaining_amount'])

    return jsonify(items)
