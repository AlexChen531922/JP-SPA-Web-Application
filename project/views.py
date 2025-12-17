from flask import Blueprint, render_template, request, session, flash, redirect, url_for, jsonify, abort
from .decorators import login_required, customer_required
from project.extensions import database
from .db import get_current_user_id, get_current_user_role, is_logged_in
# 引入新的通知函式
from .notifications import notify_contact_message, notify_new_order_created, notify_new_booking_created
import MySQLdb.cursors
from datetime import datetime

main_bp = Blueprint('main', __name__)


# =====================================================
# HOME PAGE
# =====================================================

@main_bp.route('/')
def home():
    """Homepage with latest products and courses"""
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    # Get featured products (latest 6)
    cursor.execute("""
        SELECT p.id, p.name, p.price, p.image, pc.name as category_name
        FROM products p
        LEFT JOIN product_categories pc ON p.category_id = pc.id
        WHERE p.is_active = TRUE
        ORDER BY p.created_at DESC
        LIMIT 6
    """)
    featured_products = cursor.fetchall()

    # Get featured courses (latest 6)
    cursor.execute("""
        SELECT c.id, c.name, c.regular_price, c.experience_price,
               c.duration, c.image, cc.name as category_name
        FROM courses c
        LEFT JOIN course_categories cc ON c.category_id = cc.id
        WHERE c.is_active = TRUE
        ORDER BY c.created_at DESC
        LIMIT 6
    """)
    featured_courses = cursor.fetchall()

    # Get published blog posts (latest 3)
    cursor.execute("""
        SELECT id, title, summary, image, published_at
        FROM blog_posts
        WHERE status = 'published'
        ORDER BY published_at DESC
        LIMIT 3
    """)
    posts = cursor.fetchall()

    # Convert datetime to string for template
    for post in posts:
        if post['published_at']:
            post['date'] = post['published_at'].strftime('%Y-%m-%d')
        else:
            post['date'] = ''

    # Testimonials
    testimonials = [
        {
            'content': '晶品的課程非常專業，讓我的壓力得到很好的釋放，強烈推薦！',
            'author': '王小姐'
        },
        {
            'content': '產品品質很好，服務也很貼心，會繼續支持！',
            'author': '李先生'
        },
        {
            'content': '第一次體驗芳療就選擇晶品，真的沒有失望，環境舒適放鬆。',
            'author': '陳小姐'
        }
    ]

    cursor.close()

    return render_template(
        'index.html',
        products=featured_products,
        courses=featured_courses,
        posts=posts,
        testimonials=testimonials
    )


# =====================================================
# PRODUCTS
# =====================================================

@main_bp.route('/products')
def products():
    """Product listing page with infinite scroll"""
    page = request.args.get('page', 1, type=int)
    category_id = request.args.get('category', type=int)
    search = request.args.get('q', '').strip()
    per_page = 15
    offset = (page - 1) * per_page

    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    # Build query
    where_clauses = ["p.is_active = TRUE"]
    params = []

    if category_id:
        where_clauses.append("p.category_id = %s")
        params.append(category_id)

    if search:
        where_clauses.append("(p.name LIKE %s OR p.description LIKE %s)")
        params.extend([f'%{search}%', f'%{search}%'])

    where_sql = " AND ".join(where_clauses)

    sql = f"""
        SELECT p.id, p.name, p.price, p.image, p.description, p.stock_quantity,
               pc.name as category_name
        FROM products p
        LEFT JOIN product_categories pc ON p.category_id = pc.id
        WHERE {where_sql}
        ORDER BY p.created_at DESC
        LIMIT %s OFFSET %s
    """
    params.extend([per_page, offset])

    cursor.execute(sql, params)
    products_list = cursor.fetchall()

    cursor.close()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render_template('products_partial.html', products=products_list)

    return render_template(
        'products.html',
        products=products_list,
        current_category=category_id,
        search_query=search
    )


@main_bp.route('/product/<int:product_id>')
def product_detail(product_id):
    """Product detail page"""
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    cursor.execute("""
        SELECT p.*, pc.name as category_name
        FROM products p
        LEFT JOIN product_categories pc ON p.category_id = pc.id
        WHERE p.id = %s AND p.is_active = TRUE
    """, (product_id,))

    product = cursor.fetchone()
    cursor.close()

    if not product:
        abort(404)

    return render_template('product_detail.html', product=product)


# =====================================================
# COURSE & SCHEDULE
# =====================================================

@main_bp.route('/courses')
def courses():
    """Course listing page"""
    page = request.args.get('page', 1, type=int)
    category_id = request.args.get('category', type=int)
    search = request.args.get('q', '').strip()
    per_page = 15
    offset = (page - 1) * per_page

    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    # Build query
    where_clauses = ["c.is_active = TRUE"]
    params = []

    if category_id:
        where_clauses.append("c.category_id = %s")
        params.append(category_id)

    if search:
        where_clauses.append("(c.name LIKE %s OR c.description LIKE %s)")
        params.extend([f'%{search}%', f'%{search}%'])

    where_sql = " AND ".join(where_clauses)

    sql = f"""
        SELECT c.id, c.name, c.regular_price, c.experience_price,
               c.duration, c.sessions, c.image, c.description,
               cc.name as category_name
        FROM courses c
        LEFT JOIN course_categories cc ON c.category_id = cc.id
        WHERE {where_sql}
        ORDER BY c.created_at DESC
        LIMIT %s OFFSET %s
    """
    params.extend([per_page, offset])

    cursor.execute(sql, params)
    courses_list = cursor.fetchall()

    # Check bookings
    user_id = get_current_user_id()
    has_bookings = False
    if user_id:
        cursor.execute(
            "SELECT COUNT(*) as count FROM bookings WHERE customer_id = %s", (user_id,))
        result = cursor.fetchone()
        has_bookings = result['count'] > 0

    cursor.close()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render_template('courses_partial.html', courses=courses_list, has_bookings=has_bookings)

    return render_template(
        'courses.html',
        courses=courses_list,
        current_category=category_id,
        search_query=search,
        has_bookings=has_bookings
    )


@main_bp.route('/course/<int:course_id>')
def course_detail(course_id):
    """Course detail page with Calendar"""
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    cursor.execute("""
        SELECT c.*, cc.name as category_name
        FROM courses c
        LEFT JOIN course_categories cc ON c.category_id = cc.id
        WHERE c.id = %s AND c.is_active = TRUE
    """, (course_id,))

    course = cursor.fetchone()
    cursor.close()

    if not course:
        abort(404)

    return render_template(
        'course_detail.html',
        course=course
    )


@main_bp.route('/api/course/<int:course_id>/schedule')
def get_course_schedule(course_id):
    """
    API for FullCalendar
    Modified: 讀取全店共用時段 (shop_schedules)，限制預約時間
    """
    start_str = request.args.get('start')
    end_str = request.args.get('end')

    try:
        # 設定「最早可預約時間」為後天 00:00
        now = datetime.now()
        start_limit = (now + timedelta(days=2)).replace(hour=0,
                                                        minute=0, second=0, microsecond=0)

        # 轉換日期 (處理可能帶有的時區 Z)
        if start_str:
            start_date = datetime.fromisoformat(start_str.replace('Z', ''))
        else:
            # 預設查詢本月第一天
            start_date = datetime(now.year, now.month, 1)

        if end_str:
            end_date = datetime.fromisoformat(end_str.replace('Z', ''))
        else:
            # 預設查詢下個月第一天 (即本月最後一天)
            if now.month == 12:
                end_date = datetime(now.year + 1, 1, 1)
            else:
                end_date = datetime(now.year, now.month + 1, 1)

        # 確保查詢範圍不早於 start_limit
        if start_date < start_limit:
            start_date = start_limit

    except ValueError:
        return jsonify([])  # 日期格式錯誤回傳空陣列

    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SET time_zone = '+08:00'")  # 強制設定時區

    # 查詢時段 - 改為查詢 shop_schedules (全店共用)
    # 條件：
    # 1. 時間範圍內
    # 2. start_time 必須大於 start_limit (後天)
    # 3. 只顯示 19:00 (含) 以前開始的時段
    # 4. is_active 為真
    cursor.execute("""
        SELECT id, start_time, end_time, max_capacity, current_bookings
        FROM shop_schedules
        WHERE start_time BETWEEN %s AND %s
          AND start_time >= %s
          AND HOUR(start_time) <= 19
          AND is_active = TRUE
    """, (start_date, end_date, start_limit))

    db_schedules = cursor.fetchall()
    cursor.close()

    events = []

    for s in db_schedules:
        is_full = s['current_bookings'] >= s['max_capacity']
        remaining = s['max_capacity'] - s['current_bookings']

        events.append({
            'id': str(s['id']),  # ID 轉字串
            'title': f"{'額滿' if is_full else '可預約'} ({remaining})",
            'start': s['start_time'].isoformat(),
            'end': s['end_time'].isoformat(),
            'backgroundColor': '#dc3545' if is_full else '#28a745',
            'borderColor': '#dc3545' if is_full else '#28a745',
            'textColor': '#fff',
            'extendedProps': {
                'isFull': is_full,
                'scheduleId': s['id'],  # 這裡是 shop_schedules 的 ID
                'dateStr': s['start_time'].strftime('%Y-%m-%d %H:%M')
            }
        })

    return jsonify(events)


# =====================================================
# POSTS
# =====================================================


@main_bp.route('/post/<int:post_id>')
def post_detail(post_id):
    """Blog post detail page"""
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    # Get post
    cursor.execute("""
        SELECT p.*, u.firstname, u.surname,
               CONCAT(u.firstname, ' ', u.surname) as author_name
        FROM blog_posts p
        LEFT JOIN users u ON p.author_id = u.id
        WHERE p.id = %s AND p.status = 'published'
    """, (post_id,))
    post = cursor.fetchone()

    if not post:
        cursor.close()
        abort(404)

    # Increment view count
    cursor.execute("""
        UPDATE blog_posts
        SET views = views + 1
        WHERE id = %s
    """, (post_id,))
    database.connection.commit()

    # Get related posts
    cursor.execute("""
        SELECT id, title, summary, image, published_at
        FROM blog_posts
        WHERE status = 'published' AND id != %s
        ORDER BY published_at DESC
        LIMIT 3
    """, (post_id,))
    related_posts = cursor.fetchall()

    cursor.close()

    # Format date
    if post['published_at']:
        post['date'] = post['published_at'].strftime('%Y-%m-%d')
    else:
        post['date'] = ''

    return render_template(
        'post_detail.html',
        post=post,
        related_posts=related_posts
    )

# =====================================================
# BLOG
# =====================================================


@main_bp.route('/blog')
def blog():
    """Blog listing page"""
    page = request.args.get('page', 1, type=int)
    per_page = 12
    offset = (page - 1) * per_page

    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    # Get published posts
    cursor.execute("""
        SELECT p.id, p.title, p.summary, p.image, p.published_at, p.views,
               u.firstname, u.surname
        FROM blog_posts p
        LEFT JOIN users u ON p.author_id = u.id
        WHERE p.status = 'published'
        ORDER BY p.published_at DESC
        LIMIT %s OFFSET %s
    """, (per_page, offset))
    posts = cursor.fetchall()

    # Get total count
    cursor.execute("""
        SELECT COUNT(*) as total
        FROM blog_posts
        WHERE status = 'published'
    """)
    total = cursor.fetchone()['total']

    cursor.close()

    # Format dates
    for post in posts:
        if post['published_at']:
            post['date'] = post['published_at'].strftime('%Y-%m-%d')
        else:
            post['date'] = ''

    total_pages = (total + per_page - 1) // per_page

    return render_template(
        'blog.html',
        posts=posts,
        page=page,
        total_pages=total_pages,
        total=total
    )

# =====================================================
# ABOUT & CONTACT
# =====================================================


@main_bp.route('/about')
def about():
    """About page"""
    return render_template('about.html')


@main_bp.route('/contact', methods=['GET', 'POST'])
def contact():
    """Contact form"""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        line_id = request.form.get('line', '').strip()
        message = request.form.get('message', '').strip()

        if not name or not email or not message:
            flash('請填寫所有必填欄位', 'error')
            return redirect(url_for('main.home'))

        # Save to database
        cursor = database.connection.cursor()
        cursor.execute("""
            INSERT INTO contact_messages (name, email, phone, line_id, message)
            VALUES (%s, %s, %s, %s, %s)
        """, (name, email, phone, line_id, message))
        database.connection.commit()
        cursor.close()

        # Send notifications
        try:
            notify_contact_message(name, email, phone, line_id, message)
        except:
            pass

        flash('感謝您的來信！我們將盡快回覆', 'success')
        return redirect(url_for('main.home'))

    return redirect(url_for('main.home'))


# =====================================================
# SHOPPING CART
# =====================================================

@main_bp.route('/cart')
@login_required
@customer_required
def cart():
    """View shopping cart"""
    user_id = get_current_user_id()
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    # Get or create cart
    cursor.execute("SELECT id FROM carts WHERE customer_id = %s", (user_id,))
    cart_data = cursor.fetchone()

    if not cart_data:
        cursor.execute(
            "INSERT INTO carts (customer_id) VALUES (%s)", (user_id,))
        database.connection.commit()
        cart_id = cursor.lastrowid
    else:
        cart_id = cart_data['id']

    # Get cart items
    cursor.execute("""
        SELECT ci.id, ci.quantity,
               p.id as product_id, p.name, p.price, p.image
        FROM cart_items ci
        JOIN products p ON ci.product_id = p.id
        WHERE ci.cart_id = %s AND p.is_active = TRUE
    """, (cart_id,))

    cart_items = cursor.fetchall()
    cursor.close()

    # Calculate total
    total = sum(item['price'] * item['quantity'] for item in cart_items)

    return render_template(
        'cart.html',
        cart_items=cart_items,
        total=total
    )


@main_bp.route('/cart/update', methods=['POST'])
@login_required
@customer_required
def update_cart():
    """Update cart quantities"""
    user_id = get_current_user_id()
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    cursor.execute("SELECT id FROM carts WHERE customer_id = %s", (user_id,))
    cart_data = cursor.fetchone()

    if not cart_data:
        cursor.close()
        flash('購物車是空的', 'warning')
        return redirect(url_for('main.cart'))

    cart_id = cart_data['id']

    # Update each item
    for key, value in request.form.items():
        if key.startswith('quantity_'):
            item_id = int(key.replace('quantity_', ''))
            quantity = int(value)

            if quantity < 1:
                cursor.execute(
                    "DELETE FROM cart_items WHERE id = %s AND cart_id = %s", (item_id, cart_id))
            else:
                cursor.execute(
                    "UPDATE cart_items SET quantity = %s WHERE id = %s AND cart_id = %s", (quantity, item_id, cart_id))

    database.connection.commit()
    cursor.close()

    flash('購物車已更新', 'success')
    return redirect(url_for('main.cart'))


@main_bp.route('/cart/remove/<int:item_id>', methods=['POST'])
@login_required
@customer_required
def remove_from_cart(item_id):
    """Remove item from cart"""
    user_id = get_current_user_id()
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    cursor.execute("SELECT id FROM carts WHERE customer_id = %s", (user_id,))
    cart_data = cursor.fetchone()

    if cart_data:
        cursor.execute(
            "DELETE FROM cart_items WHERE id = %s AND cart_id = %s", (item_id, cart_data['id']))
        database.connection.commit()
        flash('已移除商品', 'info')

    cursor.close()
    return redirect(url_for('main.cart'))


# =====================================================
# CHECKOUT WITH INVENTORY AUTO-SYNC
# =====================================================

@main_bp.route('/cart/checkout', methods=['POST'])
@login_required
@customer_required
def checkout():
    """
    Checkout and create order
    """
    user_id = get_current_user_id()
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    try:
        # 1. Get cart
        cursor.execute(
            "SELECT id FROM carts WHERE customer_id = %s", (user_id,))
        cart_data = cursor.fetchone()

        if not cart_data:
            flash('購物車是空的', 'warning')
            cursor.close()
            return redirect(url_for('main.cart'))

        cart_id = cart_data['id']

        # 2. Get cart items + product stock
        cursor.execute("""
            SELECT
                ci.id, ci.quantity, ci.product_id,
                p.name, p.price, p.stock_quantity
            FROM cart_items ci
            JOIN products p ON ci.product_id = p.id
            WHERE ci.cart_id = %s AND p.is_active = TRUE
        """, (cart_id,))
        items = cursor.fetchall()

        if not items:
            flash('購物車是空的', 'warning')
            cursor.close()
            return redirect(url_for('main.cart'))

        # 3. Stock validation
        for item in items:
            if item['stock_quantity'] < item['quantity']:
                flash(f'「{item["name"]}」庫存不足', 'error')
                cursor.close()
                return redirect(url_for('main.cart'))

        # 4. Calculate total
        total = sum(item['price'] * item['quantity'] for item in items)

        # 5. Create order
        cursor.execute("""
            INSERT INTO orders (customer_id, total_amount, status)
            VALUES (%s, %s, 'pending')
        """, (user_id, total))
        order_id = cursor.lastrowid

        # 6. Insert order_items + reduce stock + log
        for item in items:
            subtotal = item['price'] * item['quantity']

            # Insert order item record
            cursor.execute("""
                INSERT INTO order_items
                (order_id, product_id, quantity, unit_price, subtotal)
                VALUES (%s, %s, %s, %s, %s)
            """, (order_id, item['product_id'], item['quantity'], item['price'], subtotal))

            # Reduce inventory
            cursor.execute("""
                UPDATE products
                SET stock_quantity = stock_quantity - %s
                WHERE id = %s
            """, (item['quantity'], item['product_id']))

            # Write inventory log
            cursor.execute("""
                INSERT INTO inventory_logs
                (product_id, change_amount, change_type, reference_id, created_by)
                VALUES (%s, %s, 'sale', %s, %s)
            """, (item['product_id'], -item['quantity'], order_id, user_id))

        # 7. Clear cart
        cursor.execute("DELETE FROM cart_items WHERE cart_id = %s", (cart_id,))

        # 8. Get user info
        cursor.execute("""
            SELECT username, email, firstname, surname
            FROM users
            WHERE id = %s
        """, (user_id,))
        user = cursor.fetchone()

        database.connection.commit()
        cursor.close()

        # 9. Send notification
        try:
            items_text = '\n'.join([
                f"- {item['name']} x {item['quantity']}"
                for item in items
            ])

            # 使用新的通知函式
            notify_new_order_created(
                order_id,
                f"{user['firstname']} {user['surname']}",
                user['email'],  # 傳入 Email
                total,
                items_text
            )
        except Exception as e:
            print(f"Notification failed: {e}")

        return redirect(url_for('main.checkout_success', order_id=order_id))

    except Exception as e:
        database.connection.rollback()
        if 'cursor' in locals():
            cursor.close()
        flash(f'結帳失敗: {str(e)}', 'error')
        return redirect(url_for('main.cart'))


# =====================================================
# ORDER CANCELLATION WITH INVENTORY RESTORE
# =====================================================


@main_bp.route('/order/<int:order_id>/cancel', methods=['POST'])
@login_required
@customer_required
def cancel_order(order_id):
    """
    Cancel order and restore inventory
    """
    user_id = get_current_user_id()
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    try:
        # Verify order ownership
        cursor.execute("""
            SELECT id, status 
            FROM orders 
            WHERE id = %s AND customer_id = %s
        """, (order_id, user_id))

        order = cursor.fetchone()

        if not order:
            flash('訂單不存在', 'error')
            cursor.close()
            return redirect(url_for('customer.orders'))

        if order['status'] != 'pending':
            flash('只能取消待確認的訂單', 'error')
            cursor.close()
            return redirect(url_for('customer.orders'))

        # Get order items
        cursor.execute("""
            SELECT product_id, quantity 
            FROM order_items 
            WHERE order_id = %s
        """, (order_id,))

        items = cursor.fetchall()

        # RESTORE INVENTORY
        for item in items:
            cursor.execute("""
                UPDATE products 
                SET stock_quantity = stock_quantity + %s 
                WHERE id = %s
            """, (item['quantity'], item['product_id']))

            # LOG INVENTORY RESTORATION
            cursor.execute("""
                INSERT INTO inventory_logs 
                (product_id, change_amount, change_type, reference_id, created_by)
                VALUES (%s, %s, 'return', %s, %s)
            """, (item['product_id'], item['quantity'], order_id, user_id))

        # Update order status
        cursor.execute("""
            UPDATE orders 
            SET status = 'cancelled' 
            WHERE id = %s
        """, (order_id,))

        database.connection.commit()
        cursor.close()

        flash('訂單已取消,庫存已恢復', 'success')
        return redirect(url_for('customer.orders'))

    except Exception as e:
        database.connection.rollback()
        cursor.close()
        flash(f'取消失敗: {str(e)}', 'error')
        return redirect(url_for('customer.orders'))


# =====================================================
# ADD TO CART
# =====================================================


@main_bp.route('/cart/add/<int:product_id>', methods=['POST'])
@login_required
@customer_required
def add_to_cart(product_id):
    """Add product to cart"""
    user_id = get_current_user_id()
    quantity = request.form.get('quantity', 1, type=int)

    # Validate quantity
    if quantity < 1:
        flash('數量必須大於 0', 'error')
        return redirect(request.referrer or url_for('main.products'))

    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    # 1. Check product
    cursor.execute("""
        SELECT id, name, stock_quantity 
        FROM products 
        WHERE id = %s AND is_active = TRUE
    """, (product_id,))
    product = cursor.fetchone()

    if not product:
        cursor.close()
        flash('此商品不存在', 'error')
        return redirect(request.referrer or url_for('main.products'))

    # 2. Check stock
    if product['stock_quantity'] < quantity:
        cursor.close()
        flash('庫存不足', 'error')
        return redirect(request.referrer or url_for('main.products'))

    # 3. Get or create cart
    cursor.execute("SELECT id FROM carts WHERE customer_id = %s", (user_id,))
    cart_data = cursor.fetchone()

    if not cart_data:
        cursor.execute(
            "INSERT INTO carts (customer_id) VALUES (%s)", (user_id,))
        database.connection.commit()
        cart_id = cursor.lastrowid
    else:
        cart_id = cart_data['id']

    # 4. Check if item already in cart
    cursor.execute("""
        SELECT id, quantity 
        FROM cart_items
        WHERE cart_id = %s AND product_id = %s
    """, (cart_id, product_id))
    existing = cursor.fetchone()

    if existing:
        new_quantity = existing['quantity'] + quantity

        # Prevent total > stock
        if product['stock_quantity'] < new_quantity:
            cursor.close()
            flash('加入數量超過庫存', 'error')
            return redirect(request.referrer or url_for('main.products'))

        cursor.execute("""
            UPDATE cart_items 
            SET quantity = %s
            WHERE id = %s
        """, (new_quantity, existing['id']))
    else:
        cursor.execute("""
            INSERT INTO cart_items (cart_id, product_id, quantity)
            VALUES (%s, %s, %s)
        """, (cart_id, product_id, quantity))

    # 5. Commit + close
    database.connection.commit()
    cursor.close()

    flash(f'已將「{product["name"]}」產品預訂', 'success')
    return redirect(request.referrer or url_for('main.products'))


# =====================================================
# SUCCESS PAGES
# =====================================================

@main_bp.route('/checkout/success/<int:order_id>')
@login_required
@customer_required
def checkout_success(order_id):
    """Order success page"""
    user_id = get_current_user_id()
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    cursor.execute("""
        SELECT o.id, o.total_amount, o.created_at
        FROM orders o WHERE o.id = %s AND o.customer_id = %s
    """, (order_id, user_id))
    order = cursor.fetchone()

    if not order:
        cursor.close()
        abort(404)

    cursor.execute("""
        SELECT oi.quantity, oi.unit_price, oi.subtotal, p.name
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id = %s
    """, (order_id,))
    items = cursor.fetchall()
    cursor.close()

    return render_template('checkout_success.html', order=order, items=items)


@main_bp.route('/booking/success/<int:booking_id>')
@login_required
@customer_required
def booking_success(booking_id):
    """Booking success page"""
    user_id = get_current_user_id()
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    cursor.execute("""
        SELECT b.id, b.sessions_purchased, b.total_amount, b.is_first_time,
               b.created_at, c.name as course_name
        FROM bookings b
        JOIN courses c ON b.course_id = c.id
        WHERE b.id = %s AND b.customer_id = %s
    """, (booking_id, user_id))
    booking = cursor.fetchone()
    cursor.close()

    if not booking:
        abort(404)

    return render_template('booking_success.html', booking=booking)


@main_bp.route('/course/<int:course_id>/book', methods=['POST'])
@login_required
@customer_required
def book_course(course_id):
    """Legacy booking method - Redirect to calendar"""
    return redirect(url_for('main.course_detail', course_id=course_id))


# =====================================================
# COURSE SLOT BOOKING (修復版)
# =====================================================

@main_bp.route('/course/book_slot', methods=['POST'])
@login_required
@customer_required
def book_course_slot():
    user_id = get_current_user_id()
    schedule_id = request.form.get('schedule_id')
    course_id = request.form.get('course_id')

    if not schedule_id:
        flash('請選擇預約時段', 'error')
        return redirect(url_for('main.courses'))

    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    try:
        # 1. 檢查時段是否存在且有名額
        cursor.execute("""
            SELECT cs.*, c.name, c.regular_price, c.experience_price
            FROM course_schedules cs
            JOIN courses c ON cs.course_id = c.id
            WHERE cs.id = %s FOR UPDATE
        """, (schedule_id,))
        schedule = cursor.fetchone()

        if not schedule:
            raise Exception("時段不存在")

        if schedule['current_bookings'] >= schedule['max_capacity']:
            raise Exception("該時段已額滿，請選擇其他時間")

        # 2. 檢查是否首購
        cursor.execute(
            "SELECT COUNT(*) as count FROM bookings WHERE customer_id = %s", (user_id,))
        is_first_time = cursor.fetchone()['count'] == 0

        # 判斷價格
        price = schedule['experience_price'] if (
            is_first_time and schedule['experience_price']) else schedule['regular_price']

        # 3. 建立訂單
        cursor.execute("""
            INSERT INTO bookings (customer_id, course_id, schedule_id, total_amount, is_first_time, status)
            VALUES (%s, %s, %s, %s, %s, 'pending')
        """, (user_id, course_id, schedule_id, price, is_first_time))
        booking_id = cursor.lastrowid

        # 4. 更新時段人數
        cursor.execute("""
            UPDATE course_schedules 
            SET current_bookings = current_bookings + 1 
            WHERE id = %s
        """, (schedule_id,))

        # 5. 獲取用戶資料
        cursor.execute(
            "SELECT firstname, surname, email FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()

        # 提交資料庫
        database.connection.commit()

        # ==========================================
        # 6. 發送通知 (獨立 Try-Catch，避免影響預約結果)
        # ==========================================
        try:
            from .notifications import notify_new_booking_created

            booking_time_str = schedule['start_time'].strftime(
                '%Y-%m-%d %H:%M')
            customer_name = f"{user['firstname']} {user['surname']}"

            notify_new_booking_created(
                booking_id,
                customer_name,
                user['email'],
                schedule['name'],
                booking_time_str
            )
        except Exception as e:
            print(f"Notification failed: {e}")

        flash('預約申請已送出！待確認後將通知您。', 'success')
        return redirect(url_for('customer.bookings'))

    except Exception as e:
        database.connection.rollback()
        flash(f'預約失敗: {str(e)}', 'error')
        return redirect(url_for('main.course_detail', course_id=course_id))

    finally:
        cursor.close()


# =====================================================
# LEGAL PAGES
# =====================================================

@main_bp.route('/privacy-policy')
def privacy_policy():
    return render_template('privacy.html')


@main_bp.route('/terms-of-service')
def terms_of_service():
    return render_template('terms.html')
