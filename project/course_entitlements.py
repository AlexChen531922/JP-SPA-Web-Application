"""05: Paid course entitlements, bookings and recognition.

All functions using a cursor participate in the caller's MySQL transaction.
Never commit or send external notifications inside these helpers.
"""
import re
from decimal import Decimal
from project.stored_value import money


def positive_money(value, field='金額'):
    result = money(value)
    if result <= 0 or result > Decimal('99999999.99'):
        raise ValueError(f'{field}必須為正數且不得超過允許範圍')
    return result


def parse_tiers(raw):
    """5:11000,10:20000. Single-session tier always uses course regular_price."""
    raw = (raw or '').strip()
    if len(raw) > 300:
        raise ValueError('堂數優惠設定過長')
    result = {}
    if not raw:
        return result
    for entry in raw.split(','):
        match = re.fullmatch(r'\s*(\d{1,3})\s*:\s*(\d{1,8}(?:\.\d{1,2})?)\s*', entry)
        if not match:
            raise ValueError('堂數優惠請用「5:11000,10:20000」格式')
        sessions = int(match.group(1))
        if sessions < 2 or sessions > 100 or sessions in result:
            raise ValueError('優惠堂數需為 2～100，且不可重複；單堂使用原價')
        result[sessions] = positive_money(match.group(2), '堂數優惠總價')
    return result


def replace_tiers(cursor, course_id, tiers):
    cursor.execute('DELETE FROM course_sale_tiers WHERE course_id=%s', (course_id,))
    for count, price in sorted(tiers.items()):
        cursor.execute('INSERT INTO course_sale_tiers (course_id,sessions,default_total) VALUES (%s,%s,%s)',
                       (course_id, count, price))


def load_tiers(cursor, course_id):
    cursor.execute('SELECT sessions,default_total FROM course_sale_tiers WHERE course_id=%s ORDER BY sessions',
                   (course_id,))
    return {int(row['sessions']): money(row['default_total']) for row in cursor.fetchall()}


def available_sessions(purchase):
    return int(purchase['total_sessions']) - int(purchase['completed_sessions']) - int(purchase['reserved_sessions'])


def record_course_event(cursor, purchase_id, booking_id, action, actor_id,
                        reserved_delta=0, completed_delta=0, recognized=Decimal('0')):
    """Append-only action ledger, participating in the caller's transaction."""
    cursor.execute("""INSERT INTO customer_course_events
        (purchase_id,booking_id,action,delta_reserved,delta_completed,recognized_amount,operated_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (purchase_id,booking_id,action,reserved_delta,completed_delta,recognized,actor_id))


def reserve_for_booking(cursor, purchase_id, customer_id, course_id, booking_id, actor_id):
    """Lock purchase first. Never permit overspending across simultaneous bookings."""
    cursor.execute('''SELECT id,customer_id,course_id,total_sessions,completed_sessions,reserved_sessions
        FROM customer_course_purchases WHERE id=%s AND status='active' FOR UPDATE''', (purchase_id,))
    purchase = cursor.fetchone()
    if not purchase or purchase['customer_id'] != customer_id or purchase['course_id'] != course_id:
        raise ValueError('該客戶沒有這筆指定課程的可用購買權益')
    if available_sessions(purchase) < 1:
        raise ValueError('已購課程可用堂數不足（包含其他已預約保留的堂數）')
    cursor.execute('''INSERT INTO customer_course_allocations
        (purchase_id,booking_id,status,recognized_amount,operated_by)
        VALUES (%s,%s,'reserved',0,%s)''', (purchase_id, booking_id, actor_id))
    cursor.execute('''UPDATE customer_course_purchases SET reserved_sessions=reserved_sessions+1
        WHERE id=%s''', (purchase_id,))
    cursor.execute('UPDATE bookings SET course_purchase_id=%s WHERE id=%s', (purchase_id, booking_id))
    record_course_event(cursor,purchase_id,booking_id,'reserve',actor_id,reserved_delta=1)


def transition_allocation(cursor, booking_id, status, actor_id):
    """Call while holding the corresponding booking row lock, before status UPDATE.
    Legacy bookings (without a linked purchase) are unchanged.
    """
    cursor.execute('''SELECT a.id,a.purchase_id,a.status,a.recognized_amount
        FROM customer_course_allocations a WHERE a.booking_id=%s FOR UPDATE''', (booking_id,))
    alloc = cursor.fetchone()
    if not alloc:
        return False
    cursor.execute('''SELECT id,total_sessions,total_paid,completed_sessions,reserved_sessions
        FROM customer_course_purchases WHERE id=%s FOR UPDATE''', (alloc['purchase_id'],))
    purchase = cursor.fetchone()
    if not purchase:
        raise ValueError('對應的課程購買紀錄不存在')
    current = alloc['status']
    if current == 'completed':
        if status != 'completed':
            raise ValueError('已完成的堂數不得直接取消或改回未完成；必須另行人工帳務更正')
        return True
    if current == 'reserved':
        if status == 'completed':
            if purchase['reserved_sessions'] < 1:
                raise ValueError('預約保留堂數不一致')
            # Allocate actual discounted purchase price over completed lessons.
            # The last lesson receives the rounding residual.
            cursor.execute('''SELECT COALESCE(SUM(a.recognized_amount),0) AS recognized
                FROM customer_course_allocations a WHERE a.purchase_id=%s AND a.status='completed' ''',
                (alloc['purchase_id'],))
            already = money(cursor.fetchone()['recognized'])
            if int(purchase['completed_sessions']) + 1 == int(purchase['total_sessions']):
                recognized = money(purchase['total_paid']) - already
            else:
                recognized = money(Decimal(str(purchase['total_paid'])) / Decimal(purchase['total_sessions']))
            cursor.execute('''UPDATE customer_course_purchases SET completed_sessions=completed_sessions+1,
                reserved_sessions=reserved_sessions-1 WHERE id=%s''', (alloc['purchase_id'],))
            cursor.execute('''UPDATE customer_course_allocations SET status='completed', recognized_amount=%s,
                operated_by=%s,completed_at=NOW() WHERE id=%s''', (recognized, actor_id, alloc['id']))
            record_course_event(cursor,alloc['purchase_id'],booking_id,'complete',actor_id,
                                reserved_delta=-1,completed_delta=1,recognized=recognized)
        elif status == 'cancelled':
            cursor.execute('''UPDATE customer_course_purchases SET reserved_sessions=reserved_sessions-1
                WHERE id=%s AND reserved_sessions>0''', (alloc['purchase_id'],))
            if cursor.rowcount != 1:
                raise ValueError('預約保留堂數不足，無法取消')
            cursor.execute('''UPDATE customer_course_allocations SET status='released',operated_by=%s
                WHERE id=%s''', (actor_id, alloc['id']))
            record_course_event(cursor,alloc['purchase_id'],booking_id,'release',actor_id,reserved_delta=-1)
        return True
    if current == 'released':
        if status == 'cancelled':
            return True
        if status == 'completed':
            raise ValueError('已取消的課程不能直接核銷，請先恢復預約')
        if available_sessions(purchase) < 1:
            raise ValueError('剩餘堂數不足，無法恢復預約')
        cursor.execute('''UPDATE customer_course_purchases SET reserved_sessions=reserved_sessions+1
            WHERE id=%s''', (alloc['purchase_id'],))
        cursor.execute('''UPDATE customer_course_allocations SET status='reserved',operated_by=%s
            WHERE id=%s''', (actor_id, alloc['id']))
        record_course_event(cursor,alloc['purchase_id'],booking_id,'restore',actor_id,reserved_delta=1)
        return True
    raise ValueError('未知的課程核銷狀態')


def occupy_schedule(cursor, appointment, duration=60):
    """Use existing shop schedule with capacity checks; otherwise create one slot.
    Caller must be inside a transaction.
    """
    from datetime import timedelta
    cursor.execute('''SELECT id,max_capacity,current_bookings,is_active FROM shop_schedules
        WHERE start_time=%s FOR UPDATE''', (appointment,))
    slot = cursor.fetchone()
    if slot:
        if not slot['is_active'] or slot['current_bookings'] >= slot['max_capacity']:
            raise ValueError('預約時段已關閉或額滿')
        cursor.execute('''UPDATE shop_schedules SET current_bookings=current_bookings+1 WHERE id=%s''',
                       (slot['id'],))
        return slot['id']
    cursor.execute('''INSERT INTO shop_schedules
        (start_time,end_time,max_capacity,current_bookings,is_active)
        VALUES (%s,%s,1,1,1)''', (appointment, appointment+timedelta(minutes=duration or 60)))
    return cursor.lastrowid
