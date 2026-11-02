"""Atomic stored-value operations. All operations use the caller's MySQL transaction.

No independent commits: stock, order status and stored-value must succeed or roll back together.
The logged-in actor's account id is recorded, not client-supplied.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from project.extensions import database

CENT = Decimal('0.01')


def money(value):
    try:
        original = Decimal(str(value))
        if not original.is_finite():
            raise ValueError('金額必須是有限數字')
        amount = original.quantize(CENT, rounding=ROUND_HALF_UP)
        if amount != original:
            raise ValueError('金額最多兩位小數')
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise ValueError(str(exc) if isinstance(exc, ValueError) else '金額必須是有效數字') from exc
    return amount


def ensure_wallet(cursor, customer_id):
    # INSERT IGNORE avoids a duplicate-row error when two requests initialize simultaneously.
    cursor.execute('INSERT IGNORE INTO customer_stored_balances (customer_id,balance) VALUES (%s,0)', (customer_id,))
    cursor.execute('SELECT balance FROM customer_stored_balances WHERE customer_id=%s FOR UPDATE', (customer_id,))
    row = cursor.fetchone()
    if not row:
        raise ValueError('儲值帳戶不存在')
    return money(row['balance'])


def change_balance(cursor, customer_id, amount, action, actor_id, order_id=None, revision=None, notes=None, request_key=None):
    amount = money(amount)
    if amount == 0:
        return None
    previous = ensure_wallet(cursor, customer_id)
    after = previous + amount
    if after < 0:
        raise ValueError('儲值餘額不足，無法扣款')
    if after > Decimal('9999999999.99'):
        raise ValueError('儲值餘額超出可儲存範圍')
    cursor.execute('UPDATE customer_stored_balances SET balance=%s WHERE customer_id=%s', (after, customer_id))
    cursor.execute('''INSERT INTO customer_stored_value_ledger
        (customer_id,order_id,financial_revision,action,amount,balance_after,operated_by_user_id,notes,request_key)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
        (customer_id, order_id, revision, action, amount, after, actor_id, notes, request_key))
    return after


def lock_order(cursor, order_id, customer_id=None):
    sql = 'SELECT * FROM orders WHERE id=%s'
    params = [order_id]
    if customer_id is not None:
        sql += ' AND customer_id=%s'
        params.append(customer_id)
    cursor.execute(sql + ' FOR UPDATE', tuple(params))
    order = cursor.fetchone()
    if not order or order['deleted_at'] is not None:
        raise ValueError('訂單不存在或已封存')
    return order


def cancel_order(cursor, order, actor_id, note='Order Cancelled'):
    """Call after locking order, before updating status; idempotent for already-cancelled orders."""
    if order['status'] == 'cancelled':
        return False
    cursor.execute('SELECT product_id,quantity FROM order_items WHERE order_id=%s', (order['id'],))
    for item in cursor.fetchall():
        cursor.execute('UPDATE products SET stock_quantity=stock_quantity+%s WHERE id=%s',
                       (item['quantity'], item['product_id']))
        cursor.execute('''INSERT INTO inventory_logs
          (product_id,change_amount,change_type,reference_id,notes,created_by)
          VALUES (%s,%s,'return',%s,%s,%s)''',
          (item['product_id'],item['quantity'],order['id'],note,actor_id))
    used = money(order['stored_value_amount'])
    if used > 0:
        revision = order['financial_revision'] + 1
        change_balance(cursor, order['customer_id'], used, 'refund', actor_id,
                       order['id'], revision, '訂單取消退還儲值金')
        cursor.execute('UPDATE orders SET financial_revision=%s WHERE id=%s', (revision,order['id']))
    cursor.execute("UPDATE orders SET status='cancelled' WHERE id=%s", (order['id'],))
    return True


def restore_order(cursor, order, new_status, actor_id):
    """After locking cancelled order, re-deduct credit and stock atomically."""
    if order['status'] != 'cancelled':
        raise ValueError('只有已取消訂單可恢復')
    cursor.execute('SELECT product_id,quantity FROM order_items WHERE order_id=%s', (order['id'],))
    for item in cursor.fetchall():
        cursor.execute('''UPDATE products SET stock_quantity=stock_quantity-%s,last_sale_date=NOW()
            WHERE id=%s AND stock_quantity >= %s''',
            (item['quantity'],item['product_id'],item['quantity']))
        if cursor.rowcount != 1:
            raise ValueError('產品庫存不足，無法恢復訂單')
        cursor.execute('''INSERT INTO inventory_logs
          (product_id,change_amount,change_type,reference_id,notes,created_by)
          VALUES (%s,%s,'sale',%s,'Order Restored',%s)''',
          (item['product_id'],-item['quantity'],order['id'],actor_id))
    used = money(order['stored_value_amount'])
    if used > 0:
        revision = order['financial_revision'] + 1
        change_balance(cursor, order['customer_id'], -used, 'restore_spend', actor_id,
                       order['id'], revision, '訂單恢復重新扣除儲值金')
        cursor.execute('UPDATE orders SET financial_revision=%s WHERE id=%s', (revision,order['id']))
    cursor.execute('UPDATE orders SET status=%s WHERE id=%s', (new_status,order['id']))
    return True


def archive_order(cursor, order, actor_id):
    """Archive retains items, events, inventory and wallet ledgers."""
    if order['status'] != 'cancelled':
        raise ValueError('請先將訂單取消，系統會自動回補庫存及返還儲值金；取消後才能封存')
    cursor.execute('UPDATE orders SET deleted_at=NOW(),deleted_by_user_id=%s WHERE id=%s',
                   (actor_id, order['id']))
