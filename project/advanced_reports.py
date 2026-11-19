"""
Advanced Reporting System with Filters
Supports: Daily, Weekly, Monthly, Quarterly, Yearly reports
Sales rankings by quantity and revenue
Event analytics
"""

from flask import Blueprint, render_template, request, jsonify
from datetime import datetime, timedelta
from decimal import Decimal
import MySQLdb.cursors
from project.extensions import database
# ⭐ 修改：改用 admin_required，並建議從 decorators 匯入以避免循環引用
from project.decorators import admin_required

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
# MAIN REPORTS DASHBOARD
# =====================================================


@reports_bp.route('/')
@admin_required  # ⭐ 修改：僅限 Admin
def dashboard():
    """Main reports dashboard with filters"""
    period = request.args.get('period', 'month')
    custom_start = request.args.get('start_date')
    custom_end = request.args.get('end_date')

    start_date, end_date = get_date_range(period, custom_start, custom_end)

    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    # Revenue Summary
    cursor.execute("""
        SELECT 
            COALESCE(SUM(total_amount), 0) as total_revenue,
            COUNT(*) as order_count,
            AVG(total_amount) as avg_order_value
        FROM orders o JOIN users u ON u.id=o.customer_id
        WHERE DATE(o.created_at) BETWEEN %s AND %s
        AND o.status != 'cancelled' AND o.deleted_at IS NULL
        AND u.email != 'store@jparomatic.local'
    """, (start_date, end_date))
    revenue_summary = cursor.fetchone()

    # Booking Revenue
    cursor.execute("""
        SELECT 
            COALESCE(SUM(total_amount), 0) as total_revenue,
            COUNT(*) as booking_count,
            AVG(total_amount) as avg_booking_value
        FROM bookings b JOIN users u ON u.id=b.customer_id
        WHERE DATE(b.created_at) BETWEEN %s AND %s
        AND b.status != 'cancelled' AND u.email != 'store@jparomatic.local'
    """, (start_date, end_date))
    booking_summary = cursor.fetchone()
    cursor.execute('''SELECT COALESCE(SUM(a.recognized_amount),0) AS recognized
        FROM customer_course_allocations a
        JOIN customer_course_purchases cp ON cp.id=a.purchase_id
        JOIN users u ON u.id=cp.customer_id
        WHERE a.status='completed' AND DATE(a.completed_at) BETWEEN %s AND %s
        AND u.email != 'store@jparomatic.local' ''', (start_date,end_date))
    prepaid_recognized = cursor.fetchone()['recognized']
    booking_summary['total_revenue'] += prepaid_recognized

    # Calculate Cost and Profit
    cursor.execute("""
        SELECT COALESCE(SUM(oi.quantity * p.cost), 0) as total_cost
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        JOIN orders o ON oi.order_id = o.id
        JOIN users u ON u.id=o.customer_id
        WHERE DATE(o.created_at) BETWEEN %s AND %s
        AND o.status != 'cancelled' AND o.deleted_at IS NULL
        AND u.email != 'store@jparomatic.local'
    """, (start_date, end_date))
    cost_data = cursor.fetchone()

    # Course costs (assuming service_fee + product_fee as cost)
    cursor.execute("""
        SELECT COALESCE(SUM((CASE WHEN b.course_purchase_id IS NOT NULL THEN 1 ELSE b.sessions_purchased END) * (c.service_fee + c.product_fee)), 0) as course_cost
        FROM bookings b
        JOIN courses c ON b.course_id = c.id
        WHERE DATE(b.created_at) BETWEEN %s AND %s
        AND b.status != 'cancelled' AND b.is_unpaid_course_booking=0
        AND (b.course_purchase_id IS NULL OR b.status='completed')
    """, (start_date, end_date))
    course_cost_data = cursor.fetchone()

    total_revenue = float(
        revenue_summary['total_revenue']) + float(booking_summary['total_revenue'])
    total_cost = float(cost_data['total_cost']) + \
        float(course_cost_data['course_cost'])
    net_profit = total_revenue - total_cost
    profit_margin = (net_profit / total_revenue *
                     100) if total_revenue > 0 else 0

    # Daily breakdown
    cursor.execute("""
        SELECT DATE(o.created_at) AS date, COALESCE(SUM(o.total_amount),0) AS revenue,
               COUNT(*) AS count
        FROM orders o JOIN users u ON u.id=o.customer_id
        WHERE DATE(o.created_at) BETWEEN %s AND %s
          AND o.status != 'cancelled' AND o.deleted_at IS NULL
          AND u.email != 'store@jparomatic.local'
        GROUP BY DATE(o.created_at) ORDER BY date
    """, (start_date, end_date))
    daily_orders = cursor.fetchall()

    cursor.execute("""
        SELECT t.date AS date, SUM(t.revenue) AS revenue, SUM(t.count) AS count
        FROM (
            SELECT DATE(b.created_at) AS date, SUM(b.total_amount) AS revenue,COUNT(*) AS count
            FROM bookings b JOIN users u ON u.id=b.customer_id
            WHERE DATE(b.created_at) BETWEEN %s AND %s AND b.status!='cancelled'
              AND b.course_purchase_id IS NULL AND b.is_unpaid_course_booking=0 AND u.email!='store@jparomatic.local'
            GROUP BY DATE(b.created_at)
            UNION ALL
            SELECT DATE(a.completed_at) AS date,SUM(a.recognized_amount) AS revenue,COUNT(*) AS count
            FROM customer_course_allocations a
            JOIN customer_course_purchases cp ON cp.id=a.purchase_id
            JOIN users u ON u.id=cp.customer_id
            WHERE a.status='completed' AND DATE(a.completed_at) BETWEEN %s AND %s
              AND u.email!='store@jparomatic.local'
            GROUP BY DATE(a.completed_at)
        ) t GROUP BY t.date ORDER BY t.date
    """, (start_date, end_date,start_date,end_date))
    daily_bookings = cursor.fetchall()

    cursor.close()

    return render_template('reports_dashboard.html',
                           period=period,
                           start_date=start_date,
                           end_date=end_date,
                           revenue_summary=revenue_summary,
                           booking_summary=booking_summary,
                           total_revenue=total_revenue,
                           total_cost=total_cost,
                           net_profit=net_profit,
                           profit_margin=profit_margin,
                           daily_orders=daily_orders,
                           daily_bookings=daily_bookings)

# =====================================================
# PRODUCT SALES RANKINGS
# =====================================================


@reports_bp.route('/products')
@admin_required  # ⭐ 修改：僅限 Admin
def product_rankings():
    """Product sales rankings with filters"""
    period = request.args.get('period', 'month')
    sort_by = request.args.get('sort', 'quantity')  # quantity or revenue
    custom_start = request.args.get('start_date')
    custom_end = request.args.get('end_date')

    start_date, end_date = get_date_range(period, custom_start, custom_end)

    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    # Product rankings
    order_column = 'total_quantity' if sort_by == 'quantity' else 'total_revenue'

    cursor.execute(f"""
        SELECT 
            p.id,
            p.name,
            p.image,
            pc.name as category_name,
            SUM(oi.quantity) as total_quantity,
            SUM(oi.subtotal) as total_revenue,
            AVG(oi.unit_price) as avg_price,
            COUNT(DISTINCT o.id) as order_count
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        LEFT JOIN product_categories pc ON p.category_id = pc.id
        JOIN orders o ON oi.order_id = o.id
        WHERE DATE(o.created_at) BETWEEN %s AND %s
        AND o.status != 'cancelled'
        GROUP BY p.id, p.name, p.image, pc.name
        ORDER BY {order_column} DESC
        LIMIT 50
    """, (start_date, end_date))

    products = cursor.fetchall()

    # Calculate profit per product
    for product in products:
        cursor.execute("""
            SELECT cost FROM products WHERE id = %s
        """, (product['id'],))
        cost_data = cursor.fetchone()
        cost = float(cost_data['cost']) if cost_data else 0

        product['total_cost'] = cost * int(product['total_quantity'])
        product['total_profit'] = float(
            product['total_revenue']) - product['total_cost']
        product['profit_margin'] = (product['total_profit'] / float(
            product['total_revenue']) * 100) if product['total_revenue'] > 0 else 0

    cursor.close()

    return render_template('reports_products.html',
                           period=period,
                           start_date=start_date,
                           end_date=end_date,
                           sort_by=sort_by,
                           products=products)

# =====================================================
# COURSE SALES RANKINGS
# =====================================================


@reports_bp.route('/courses')
@admin_required  # ⭐ 修改：僅限 Admin
def course_rankings():
    """Course booking rankings with filters"""
    period = request.args.get('period', 'month')
    sort_by = request.args.get('sort', 'quantity')  # quantity or revenue
    custom_start = request.args.get('start_date')
    custom_end = request.args.get('end_date')

    start_date, end_date = get_date_range(period, custom_start, custom_end)

    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    order_column = 'total_sessions' if sort_by == 'quantity' else 'total_revenue'

    cursor.execute(f"""
        SELECT c.id,c.name,c.image,cc.name AS category_name,c.duration,
               SUM(t.sessions) AS total_sessions,SUM(t.amount) AS total_revenue,
               SUM(t.amount)/NULLIF(SUM(t.sessions),0) AS avg_price_per_session,
               COUNT(DISTINCT t.booking_id) AS booking_count,
               COUNT(DISTINCT t.customer_id) AS unique_customers
        FROM (
            SELECT b.course_id,b.sessions_purchased AS sessions,b.total_amount AS amount,
                   b.id AS booking_id,b.customer_id
            FROM bookings b JOIN users u ON u.id=b.customer_id
            WHERE DATE(b.created_at) BETWEEN %s AND %s AND b.status!='cancelled'
              AND b.course_purchase_id IS NULL AND b.is_unpaid_course_booking=0 AND u.email!='store@jparomatic.local'
            UNION ALL
            SELECT cp.course_id,1 AS sessions,a.recognized_amount AS amount,
                   a.booking_id,cp.customer_id
            FROM customer_course_allocations a
            JOIN customer_course_purchases cp ON cp.id=a.purchase_id
            JOIN users u ON u.id=cp.customer_id
            WHERE a.status='completed' AND DATE(a.completed_at) BETWEEN %s AND %s
              AND u.email!='store@jparomatic.local'
        ) t JOIN courses c ON c.id=t.course_id
        LEFT JOIN course_categories cc ON cc.id=c.category_id
        GROUP BY c.id,c.name,c.image,cc.name,c.duration
        ORDER BY {order_column} DESC LIMIT 50
    """, (start_date,end_date,start_date,end_date))

    courses = cursor.fetchall()

    # Calculate profit per course
    for course in courses:
        cursor.execute("""
            SELECT service_fee, product_fee 
            FROM courses 
            WHERE id = %s
        """, (course['id'],))
        cost_data = cursor.fetchone()

        if cost_data:
            cost_per_session = float(
                cost_data['service_fee'] or 0) + float(cost_data['product_fee'] or 0)
            course['total_cost'] = cost_per_session * \
                int(course['total_sessions'])
            course['total_profit'] = float(
                course['total_revenue']) - course['total_cost']
            course['profit_margin'] = (course['total_profit'] / float(
                course['total_revenue']) * 100) if course['total_revenue'] > 0 else 0
        else:
            course['total_cost'] = 0
            course['total_profit'] = float(course['total_revenue'])
            course['profit_margin'] = 100

    cursor.close()

    return render_template('reports_courses.html',
                           period=period,
                           start_date=start_date,
                           end_date=end_date,
                           sort_by=sort_by,
                           courses=courses)

# =====================================================
# EVENT ANALYTICS
# =====================================================


@reports_bp.route('/events')
@admin_required  # ⭐ 修改：僅限 Admin
def event_analytics():
    """Event performance analytics"""
    period = request.args.get('period', 'month')
    custom_start = request.args.get('start_date')
    custom_end = request.args.get('end_date')

    start_date, end_date = get_date_range(period, custom_start, custom_end)

    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    # Events with sales data
    cursor.execute("""
        SELECT 
            e.id,
            e.title,
            e.start_date,
            e.end_date,
            e.duration,
            e.customer_id,
            CONCAT(u.firstname, ' ', u.surname) as customer_name,
            COUNT(DISTINCT o.id) as order_count,
            COUNT(DISTINCT b.id) as booking_count,
            COALESCE(SUM(o.total_amount), 0) as order_revenue,
            COALESCE(SUM(b.total_amount), 0) as booking_revenue,
            COUNT(DISTINCT COALESCE(o.customer_id, b.customer_id)) as unique_customers
        FROM events e
        LEFT JOIN users u ON e.customer_id = u.id
        LEFT JOIN orders o ON DATE(o.created_at) BETWEEN DATE(e.start_date) AND DATE(e.end_date)
            AND o.status != 'cancelled'
        LEFT JOIN bookings b ON DATE(b.created_at) BETWEEN DATE(e.start_date) AND DATE(e.end_date)
            AND b.status != 'cancelled'
        WHERE DATE(e.start_date) BETWEEN %s AND %s
        GROUP BY e.id, e.title, e.start_date, e.end_date, e.duration, e.customer_id, u.firstname, u.surname
        ORDER BY e.start_date DESC
    """, (start_date, end_date))

    events = cursor.fetchall()

    # Calculate total revenue per event
    for event in events:
        event['total_revenue'] = float(
            event['order_revenue']) + float(event['booking_revenue'])
        event['total_transactions'] = int(
            event['order_count']) + int(event['booking_count'])

    # Overall event summary
    total_events = len(events)
    total_event_revenue = sum(e['total_revenue'] for e in events)
    total_event_customers = sum(e['unique_customers'] for e in events)

    cursor.close()

    return render_template('reports_events.html',
                           period=period,
                           start_date=start_date,
                           end_date=end_date,
                           events=events,
                           total_events=total_events,
                           total_event_revenue=total_event_revenue,
                           total_event_customers=total_event_customers)

# =====================================================
# CUSTOMER ANALYTICS
# =====================================================


@reports_bp.route('/customers')
@admin_required  # ⭐ 修改：僅限 Admin
def customer_analytics():
    """Customer behavior analytics"""
    period = request.args.get('period', 'month')
    custom_start = request.args.get('start_date')
    custom_end = request.args.get('end_date')

    start_date, end_date = get_date_range(period, custom_start, custom_end)

    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    # Group each source per customer BEFORE joining; avoid Cartesian double counts.
    cursor.execute("""
        SELECT u.id,CONCAT(u.firstname,' ',u.surname) AS name,u.email,u.phone,
               COALESCE(o.order_count,0) AS order_count,
               COALESCE(b.booking_count,0) AS booking_count,
               COALESCE(o.order_total,0) AS order_total,
               COALESCE(b.booking_total,0) + COALESCE(cp.recognized,0) AS booking_total,
               COALESCE(o.order_total,0)+COALESCE(b.booking_total,0)+COALESCE(cp.recognized,0) AS total_spent
        FROM users u
        LEFT JOIN (
            SELECT customer_id,COUNT(*) AS order_count,SUM(total_amount) AS order_total
            FROM orders WHERE DATE(created_at) BETWEEN %s AND %s
              AND status!='cancelled' AND deleted_at IS NULL GROUP BY customer_id
        ) o ON o.customer_id=u.id
        LEFT JOIN (
            SELECT customer_id,COUNT(*) AS booking_count,SUM(total_amount) AS booking_total
            FROM bookings WHERE DATE(created_at) BETWEEN %s AND %s
              AND status!='cancelled' GROUP BY customer_id
        ) b ON b.customer_id=u.id
        LEFT JOIN (
            SELECT cp.customer_id,SUM(a.recognized_amount) AS recognized
            FROM customer_course_allocations a JOIN customer_course_purchases cp ON cp.id=a.purchase_id
            WHERE a.status='completed' AND DATE(a.completed_at) BETWEEN %s AND %s
            GROUP BY cp.customer_id
        ) cp ON cp.customer_id=u.id
        WHERE u.role='customer' AND u.email!='store@jparomatic.local'
          AND COALESCE(o.order_total,0)+COALESCE(b.booking_total,0)+COALESCE(cp.recognized,0)>0
        ORDER BY total_spent DESC LIMIT 50
    """, (start_date,end_date,start_date,end_date,start_date,end_date))

    top_customers = cursor.fetchall()

    # Customer acquisition
    cursor.execute("""
        SELECT 
            DATE(created_at) as date,
            COUNT(*) as new_customers
        FROM users
        WHERE role = 'customer'
        AND DATE(created_at) BETWEEN %s AND %s
        GROUP BY DATE(created_at)
        ORDER BY date
    """, (start_date, end_date))

    acquisition_data = cursor.fetchall()

    cursor.close()

    return render_template('reports_customers.html',
                           period=period,
                           start_date=start_date,
                           end_date=end_date,
                           top_customers=top_customers,
                           acquisition_data=acquisition_data)

# =====================================================
# EXPORT REPORTS (CSV/Excel)
# =====================================================


@reports_bp.route('/export/<report_type>')
@admin_required  # ⭐ 修改：僅限 Admin
def export_report(report_type):
    """Export reports to CSV"""
    import csv
    from io import StringIO
    from flask import Response

    period = request.args.get('period', 'month')
    custom_start = request.args.get('start_date')
    custom_end = request.args.get('end_date')

    start_date, end_date = get_date_range(period, custom_start, custom_end)

    output = StringIO()

    if report_type == 'products':
        writer = csv.writer(output)
        writer.writerow(['產品名稱', '分類', '銷售數量', '銷售金額',
                        '平均單價', '訂單數', '成本', '利潤', '利潤率%'])

        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("""
            SELECT 
                p.name,
                pc.name as category_name,
                SUM(oi.quantity) as quantity,
                SUM(oi.subtotal) as revenue,
                AVG(oi.unit_price) as avg_price,
                COUNT(DISTINCT o.id) as orders,
                p.cost
            FROM order_items oi
            JOIN products p ON oi.product_id = p.id
            LEFT JOIN product_categories pc ON p.category_id = pc.id
            JOIN orders o ON oi.order_id = o.id
            JOIN users u ON u.id=o.customer_id
            WHERE DATE(o.created_at) BETWEEN %s AND %s
            AND o.status != 'cancelled' AND o.deleted_at IS NULL
            AND u.email != 'store@jparomatic.local'
            GROUP BY p.id, p.name, pc.name, p.cost
            ORDER BY SUM(oi.subtotal) DESC
        """, (start_date, end_date))

        for row in cursor.fetchall():
            cost = float(row['cost']) * int(row['quantity'])
            revenue = float(row['revenue'])
            profit = revenue - cost
            margin = (profit / revenue * 100) if revenue > 0 else 0

            writer.writerow([
                row['name'],
                row['category_name'] or '',
                row['quantity'],
                f"{revenue:.2f}",
                f"{row['avg_price']:.2f}",
                row['orders'],
                f"{cost:.2f}",
                f"{profit:.2f}",
                f"{margin:.2f}"
            ])

        cursor.close()

    elif report_type == 'courses':
        writer = csv.writer(output)
        writer.writerow(['課程名稱', '分類', '預約堂數', '銷售金額',
                        '預約數', '客戶數', '成本', '利潤', '利潤率%'])

        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("""
            SELECT c.name,cc.name AS category_name,SUM(t.sessions) AS sessions,
                   SUM(t.amount) AS revenue,COUNT(DISTINCT t.booking_id) AS bookings,
                   COUNT(DISTINCT t.customer_id) AS customers,c.service_fee,c.product_fee
            FROM (
                SELECT b.course_id,b.sessions_purchased AS sessions,b.total_amount AS amount,
                       b.id AS booking_id,b.customer_id
                FROM bookings b JOIN users u ON u.id=b.customer_id
                WHERE DATE(b.created_at) BETWEEN %s AND %s AND b.status!='cancelled'
                  AND b.course_purchase_id IS NULL AND b.is_unpaid_course_booking=0 AND u.email!='store@jparomatic.local'
                UNION ALL
                SELECT cp.course_id,1 AS sessions,a.recognized_amount AS amount,
                       a.booking_id,cp.customer_id
                FROM customer_course_allocations a JOIN customer_course_purchases cp ON cp.id=a.purchase_id
                JOIN users u ON u.id=cp.customer_id
                WHERE a.status='completed' AND DATE(a.completed_at) BETWEEN %s AND %s
                  AND u.email!='store@jparomatic.local'
            ) t JOIN courses c ON c.id=t.course_id
            LEFT JOIN course_categories cc ON cc.id=c.category_id
            GROUP BY c.id,c.name,cc.name,c.service_fee,c.product_fee
            ORDER BY revenue DESC
        """, (start_date,end_date,start_date,end_date))

        for row in cursor.fetchall():
            cost_per = float(row['service_fee'] or 0) + \
                float(row['product_fee'] or 0)
            cost = cost_per * int(row['sessions'])
            revenue = float(row['revenue'])
            profit = revenue - cost
            margin = (profit / revenue * 100) if revenue > 0 else 0

            writer.writerow([
                row['name'],
                row['category_name'] or '',
                row['sessions'],
                f"{revenue:.2f}",
                row['bookings'],
                row['customers'],
                f"{cost:.2f}",
                f"{profit:.2f}",
                f"{margin:.2f}"
            ])

        cursor.close()

    output.seek(0)
    filename = f"{report_type}_report_{start_date}_to_{end_date}.csv"

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )
