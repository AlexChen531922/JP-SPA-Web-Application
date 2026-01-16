from flask import Blueprint, render_template, request, session, flash, redirect, url_for, current_app
from .decorators import login_required, customer_required
from project.extensions import database, mail
from .db import get_current_user_id, get_user_details, update_user_profile
from project.notifications import send_email
import MySQLdb.cursors
import threading
import re

customer_bp = Blueprint('customer', __name__, url_prefix='/customer')

# ==========================================
# 📧 內部工具：Email 通知 & 密碼驗證
# ==========================================


def validate_password_strength(password):
    """驗證密碼強度"""
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


def send_cancel_notification(type_name, item_id, reason="顧客自行取消"):
    """發送取消通知給管理員"""
    try:
        admin_email = current_app.config.get('MAIL_DEFAULT_SENDER')
        if not admin_email:
            return

        user_id = get_current_user_id()
        user = get_user_details(user_id)
        customer_name = f"{user.get('firstname', '')} {user.get('surname', '')}"

        subject = f"【取消通知】{type_name} #{item_id} 已被取消"
        body = f"""
        管理員您好，
        顧客 {customer_name} (ID: {user_id}) 已取消了以下項目：
        類型：{type_name}
        編號：#{item_id}
        備註：{reason}
        請至後台確認詳情。
        """
        app = current_app._get_current_object()
        threading.Thread(target=send_email, args=(
            admin_email, subject, body)).start()

    except Exception as e:
        print(f"❌ 取消通知 Email 發送失敗: {e}")

# ==========================================
# 📊 Dashboard (儀表板)
# ==========================================


@customer_bp.route('/dashboard')
@customer_required
def dashboard():
    """Customer dashboard"""
    user_id = get_current_user_id()
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    # 1. 取得使用者詳細資料
    user = get_user_details(user_id)

    # 2. Get active bookings (進行中的課程)
    cursor.execute("""
        SELECT b.id, b.sessions_purchased, b.sessions_remaining, b.total_amount,
               b.created_at, b.status, c.name as course_name, c.duration
        FROM bookings b
        JOIN courses c ON b.course_id = c.id
        WHERE b.customer_id = %s AND b.sessions_remaining > 0 AND b.status != 'cancelled'
        ORDER BY b.created_at DESC
    """, (user_id,))
    active_courses = cursor.fetchall()

    # 3. Get recent orders (最近訂單)
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

    # 4. Get products stats (統計已購產品數)
    cursor.execute("""
        SELECT oi.product_id, p.name, SUM(oi.quantity) as total_quantity
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.id
        JOIN products p ON oi.product_id = p.id
        WHERE o.customer_id = %s AND o.status IN ('confirmed', 'completed')
        GROUP BY oi.product_id, p.name
    """, (user_id,))
    purchased_products = cursor.fetchall()

    cursor.close()

    return render_template(
        'customer_dashboard.html',  # 請確認您的模板檔名是這個
        user=user,
        active_courses=active_courses,
        recent_orders=recent_orders,
        purchased_products=purchased_products
    )

# ==========================================
# 📋 列表頁面 (修復 Missing Route 錯誤)
# ==========================================


@customer_bp.route('/bookings')
@customer_required
def bookings():
    """查看所有預約 (修復 base.html 連結錯誤)"""
    user_id = get_current_user_id()
    user = get_user_details(user_id)
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
    bookings_data = cursor.fetchall()
    cursor.close()
    # 注意：請確認您的模板檔名是否為 customer_bookings.html
    return render_template('customer_bookings.html', bookings=bookings_data, user=user)


@customer_bp.route('/orders')
@customer_required
def orders():
    """查看所有訂單 (修復 base.html 連結錯誤)"""
    user_id = get_current_user_id()
    user = get_user_details(user_id)
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("""
        SELECT o.id, o.total_amount, o.status, o.created_at, o.payment_method, o.notes
        FROM orders o
        WHERE o.customer_id = %s
        ORDER BY o.created_at DESC
    """, (user_id,))
    orders_data = cursor.fetchall()

    # Order Items
    order_items = {}
    for order in orders_data:
        cursor.execute("""
            SELECT oi.quantity, oi.unit_price, oi.subtotal, p.name, p.image 
            FROM order_items oi 
            JOIN products p ON oi.product_id = p.id 
            WHERE oi.order_id = %s
        """, (order['id'],))
        order_items[order['id']] = cursor.fetchall()

    cursor.close()
    # 注意：請確認您的模板檔名是否為 customer_orders.html
    return render_template('customer_orders.html', orders=orders_data, order_items=order_items, user=user)

# ==========================================
# 📦 詳細內容 & 取消功能
# ==========================================


@customer_bp.route('/order/<int:order_id>')
@customer_required
def order_detail(order_id):
    user_id = get_current_user_id()
    user = get_user_details(user_id)
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    cursor.execute(
        "SELECT * FROM orders WHERE id = %s AND customer_id = %s", (order_id, user_id))
    order = cursor.fetchone()

    if not order:
        cursor.close()
        flash('訂單不存在', 'error')
        return redirect(url_for('customer.orders'))

    cursor.execute("""
        SELECT oi.quantity, oi.unit_price, oi.subtotal, p.name, p.image, p.description 
        FROM order_items oi 
        JOIN products p ON oi.product_id = p.id 
        WHERE oi.order_id = %s
    """, (order_id,))
    items = cursor.fetchall()

    cursor.close()
    return render_template('order_detail.html', order=order, items=items, user=user)


@customer_bp.route('/order/<int:order_id>/cancel', methods=['POST'])
@customer_required
def cancel_order(order_id):
    user_id = get_current_user_id()
    try:
        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute(
            "SELECT status FROM orders WHERE id = %s AND customer_id = %s", (order_id, user_id))
        order = cursor.fetchone()

        if not order or order['status'] in ['completed', 'cancelled']:
            flash('無法取消此訂單', 'error')
            return redirect(request.referrer or url_for('customer.dashboard'))

        # 回補庫存
        cursor.execute(
            "SELECT product_id, quantity FROM order_items WHERE order_id = %s", (order_id,))
        items = cursor.fetchall()
        for item in items:
            cursor.execute("UPDATE products SET stock_quantity = stock_quantity + %s WHERE id = %s",
                           (item['quantity'], item['product_id']))
            cursor.execute("INSERT INTO inventory_logs (product_id, change_amount, change_type, notes, created_by) VALUES (%s, %s, 'return', 'Customer Cancel', %s)",
                           (item['product_id'], item['quantity'], user_id))

        cursor.execute(
            "UPDATE orders SET status = 'cancelled' WHERE id = %s", (order_id,))
        database.connection.commit()
        cursor.close()

        send_cancel_notification("訂單", order_id)
        flash('訂單已取消，庫存已釋出', 'success')

    except Exception as e:
        database.connection.rollback()
        flash(f'取消失敗: {str(e)}', 'error')

    return redirect(request.referrer or url_for('customer.dashboard'))


@customer_bp.route('/booking/<int:booking_id>/cancel', methods=['POST'])
@customer_required
def cancel_booking(booking_id):
    user_id = get_current_user_id()
    try:
        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute(
            "SELECT status, schedule_id FROM bookings WHERE id = %s AND customer_id = %s", (booking_id, user_id))
        booking = cursor.fetchone()

        if not booking or booking['status'] in ['completed', 'cancelled']:
            flash('無法取消此預約', 'error')
            return redirect(request.referrer or url_for('customer.dashboard'))

        cursor.execute(
            "UPDATE bookings SET status = 'cancelled' WHERE id = %s", (booking_id,))

        if booking['schedule_id']:
            cursor.execute(
                "UPDATE course_schedules SET current_bookings = GREATEST(current_bookings - 1, 0) WHERE id = %s", (booking['schedule_id'],))

        database.connection.commit()
        cursor.close()

        send_cancel_notification("預約", booking_id)
        flash('預約已取消', 'success')

    except Exception as e:
        database.connection.rollback()
        flash(f'取消失敗: {str(e)}', 'error')

    return redirect(request.referrer or url_for('customer.dashboard'))

# ==========================================
# 👤 Profile
# ==========================================


# 在 customer.py 或負責處理會員路由的檔案中

@customer_bp.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    # 1. 接收表單資料
    firstname = request.form.get('firstname')
    surname = request.form.get('surname')
    phone = request.form.get('phone')
    line_id = request.form.get('line_id')  # 新增
    occupation = request.form.get('occupation')  # 新增
    address = request.form.get('address')  # 新增

    # 密碼處理 (如果有填寫才更新)
    password = request.form.get('password')

    cursor = database.connection.cursor()

    try:
        # 2. 檢查 LINE ID 是否已被其他人使用 (若有填寫且與原值不同)
        if line_id and line_id != session['user'].get('line_id'):
            cursor.execute("SELECT id FROM users WHERE line_id = %s AND id != %s",
                           (line_id, session['user']['id']))
            if cursor.fetchone():
                flash('此 LINE ID 已被其他帳號使用', 'warning')
                return redirect(url_for('customer.dashboard'))

        # 3. 建構 SQL (根據是否有改密碼)
        if password and len(password) >= 10:
            # A. 有改密碼
            from werkzeug.security import generate_password_hash
            hashed_password = generate_password_hash(password)

            sql = """
                UPDATE users 
                SET firstname=%s, surname=%s, phone=%s, line_id=%s, occupation=%s, address=%s, password_hash=%s 
                WHERE id=%s
            """
            cursor.execute(sql, (firstname, surname, phone, line_id,
                           occupation, address, hashed_password, session['user']['id']))
        else:
            # B. 沒改密碼 (只更新基本資料)
            sql = """
                UPDATE users 
                SET firstname=%s, surname=%s, phone=%s, line_id=%s, occupation=%s, address=%s 
                WHERE id=%s
            """
            cursor.execute(sql, (firstname, surname, phone, line_id,
                           occupation, address, session['user']['id']))

        database.connection.commit()

        # 4. 更新 Session 中的使用者資料 (重要！不然重整後會看到舊資料)
        cursor.execute("SELECT * FROM users WHERE id = %s",
                       (session['user']['id'],))
        updated_user = cursor.fetchone()
        session['user'] = updated_user  # 更新 session

        flash('個人資料更新成功！', 'success')

    except Exception as e:
        database.connection.rollback()
        print(f"Update Profile Error: {str(e)}")  # ⭐ 請檢查這裡印出的錯誤
        flash(f'更新失敗，請稍後再試 ({str(e)})', 'error')

    finally:
        cursor.close()

    return redirect(url_for('customer.dashboard'))
