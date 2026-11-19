"""06: atomic paid-course completion and mixed-source consumable movements.

Customer-owned items are pre-purchased products, not a payment method. The
store's dedicated customer account is a material owner, never a service attendee.
All SQL uses the caller's transaction. No commits/notifications here.
"""
import hashlib
import json
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from project.course_entitlements import transition_allocation
from project.stored_value import money

STORE_EMAIL = 'store@jparomatic.local'


def parse_materials(raw):
    if not isinstance(raw, str) or len(raw) > 10000:
        raise ValueError('耗材明細資料格式不正確或過長')
    try:
        entries = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError('耗材明細不是有效 JSON') from exc
    if not isinstance(entries, list) or len(entries) > 40:
        raise ValueError('耗材明細最多 40 筆')
    result = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or entry.get('source') not in ('customer', 'store'):
            raise ValueError('耗材來源只能選擇顧客寄店或店內耗材')
        inv_id = entry.get('inventory_id')
        if isinstance(inv_id, bool) or not str(inv_id).isdigit() or int(inv_id) <= 0:
            raise ValueError('耗材產品編號無效')
        inv_id = int(inv_id)
        if inv_id in seen:
            raise ValueError('同一寄存產品不得重複列入核銷')
        seen.add(inv_id)
        amount = money(entry.get('amount'))
        if amount <= 0 or amount > Decimal('99999999.99'):
            raise ValueError('耗材核銷量必須為正數且不超過允許容量')
        result.append((entry['source'], inv_id, amount))
    return sorted(result, key=lambda item: item[1])


def complete_course_booking(cursor, booking_id, request_key, raw_materials, actor_id, ip_address):
    deductions = parse_materials(raw_materials)
    cursor.execute('''SELECT b.id,b.customer_id,b.status,b.course_purchase_id,
                             b.is_unpaid_course_booking,p.material_mode,
                             p.requires_material_confirmation,p.component_customer_value,
                             c.uses_store_consumables
        FROM bookings b
        JOIN courses c ON c.id=b.course_id
        LEFT JOIN customer_course_purchases p ON p.id=b.course_purchase_id
        WHERE b.id=%s FOR UPDATE''', (booking_id,))
    booking = cursor.fetchone()
    if not booking or booking['status'] in ('cancelled', 'completed'):
        raise ValueError('預約不存在、已完成或已取消')
    if not booking['course_purchase_id'] or booking['is_unpaid_course_booking']:
        raise ValueError('尚未付清購買課程的純預約不可完成服務')

    requires = bool(booking['requires_material_confirmation'])
    mode = booking['material_mode'] or 'store'
    sources = {source for source, _, _ in deductions}
    if booking['uses_store_consumables'] and 'customer' in sources:
        raise ValueError('固定價店內耗材課程不能核銷顧客寄店產品')
    if mode == 'store' and 'customer' in sources:
        raise ValueError('本次販售指定使用店內耗材，不能擅自改扣客戶產品')
    if mode == 'customer' and 'store' in sources:
        raise ValueError('本次販售指定使用顧客寄店產品，不能擅自改扣店內耗材')
    if requires:
        expected = {'store': {'store'}, 'customer': {'customer'}, 'mixed': {'store', 'customer'}}[mode]
        if sources != expected:
            raise ValueError('實際核銷來源與販售設定不一致；需先由管理員處理更正')

    cursor.execute("SELECT id FROM users WHERE email=%s AND role='customer'", (STORE_EMAIL,))
    store_row = cursor.fetchone()
    store_id = store_row['id'] if store_row else None
    if 'store' in sources and store_id is None:
        raise ValueError('找不到店內耗材專用帳號，無法扣料')
    if store_id == booking['customer_id']:
        raise ValueError('實際接受服務的客戶不可是店內耗材帳號')

    cursor.execute('''INSERT INTO course_service_completions
        (request_key,booking_id,operated_by) VALUES (%s,%s,%s)''',
        (request_key,booking_id,actor_id))
    completion_id = cursor.lastrowid
    owner_request = {}
    for source, inv_id, amount in deductions:
        owner_id = booking['customer_id'] if source == 'customer' else store_id
        cursor.execute('''SELECT id,customer_id,remaining_amount,capacity_unit FROM customer_inventory
            WHERE id=%s FOR UPDATE''', (inv_id,))
        inventory = cursor.fetchone()
        if (not inventory or inventory['customer_id'] != owner_id or
                inventory['capacity_unit'] not in ('ml', 'g')):
            raise ValueError('寄存產品來源不符，或容量單位尚未完成核對')
        before = Decimal(str(inventory['remaining_amount']))
        if before < amount:
            raise ValueError('寄店或店內耗材剩餘容量不足，整筆核銷已取消')
        if source not in owner_request:
            digest = hashlib.sha256((request_key + ':' + source).encode()).hexdigest()[:40]
            cursor.execute('''INSERT INTO customer_inventory_requests
                (request_key,customer_id,action,booking_id,usage_date,notes,operated_by)
                VALUES (%s,%s,'deduct',%s,%s,%s,%s)''',
                ('cs06_' + digest, owner_id, booking_id,
                 datetime.now(ZoneInfo('Asia/Taipei')).date(),
                 '06 課程完成／' + ('顧客寄店' if source == 'customer' else '店內耗材'), actor_id))
            owner_request[source] = cursor.lastrowid
        cursor.execute('''UPDATE customer_inventory SET remaining_amount=remaining_amount-%s,
            updated_at=NOW() WHERE id=%s AND customer_id=%s AND remaining_amount>=%s''',
            (amount, inv_id, owner_id, amount))
        if cursor.rowcount != 1:
            raise ValueError('耗材餘額同時變動，整筆核銷已取消')
        after = before - amount
        request_id = owner_request[source]
        cursor.execute('''INSERT INTO customer_inventory_movements
            (request_id,inventory_id,delta_amount,before_amount,after_amount,capacity_unit)
            VALUES (%s,%s,%s,%s,%s,%s)''',
            (request_id,inv_id,-amount,before,after,inventory['capacity_unit']))
        cursor.execute('''INSERT INTO course_service_materials
            (completion_id,owner_type,owner_customer_id,inventory_id,request_id,
             amount_used,capacity_unit,before_amount,after_amount)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (completion_id,source,owner_id,inv_id,request_id,amount,
             inventory['capacity_unit'],before,after))
    # Same transaction: if the session entitlement fails, every material write rolls back.
    transition_allocation(cursor,booking_id,'completed',actor_id)
    cursor.execute("UPDATE bookings SET status='completed' WHERE id=%s", (booking_id,))
    cursor.execute('''INSERT INTO audit_logs
        (user_id,action,target_type,target_id,details,ip_address)
        VALUES (%s,'complete','booking',%s,%s,%s)''',
        (actor_id,booking_id,json.dumps({'source':'course_sale_06',
          'completion_id':completion_id,'material_line_count':len(deductions)},ensure_ascii=False),ip_address))
    return {'lines':len(deductions),'completion_id':completion_id}
