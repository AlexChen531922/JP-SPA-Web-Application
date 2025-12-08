import MySQLdb.cursors
from project.extensions import database

# =====================================================
# ADMIN ORDER STATUS UPDATE WITH INVENTORY SYNC
# =====================================================


def admin_update_order_with_inventory(order_id, new_status, admin_id):
    """
    Update order status and handle inventory accordingly
    """
    # 建立連線
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    try:
        # 1. 取得目前訂單狀態
        cursor.execute("SELECT status FROM orders WHERE id = %s", (order_id,))
        order = cursor.fetchone()

        if not order:
            cursor.close()
            return False

        old_status = order['status']

        # 2. 判斷是否為「取消訂單」(需要回補庫存)
        # 如果是從「非取消」變成「取消」，且原本不是 pending (pending 通常還沒扣庫存，或是看您的邏輯)
        # 根據您的 checkout 邏輯，下單當下(pending)就已經扣庫存了，所以只要取消就要回補
        if old_status != 'cancelled' and new_status == 'cancelled':
            cursor.execute(
                "SELECT product_id, quantity FROM order_items WHERE order_id = %s", (order_id,))
            items = cursor.fetchall()

            # 回補庫存
            for item in items:
                cursor.execute("""
                    UPDATE products SET stock_quantity = stock_quantity + %s WHERE id = %s
                """, (item['quantity'], item['product_id']))

                # 寫入庫存日誌
                cursor.execute("""
                    INSERT INTO inventory_logs 
                    (product_id, change_amount, change_type, reference_id, notes, created_by)
                    VALUES (%s, %s, 'return', %s, 'Order cancelled by admin', %s)
                """, (item['product_id'], item['quantity'], order_id, admin_id))

        # 3. 更新訂單狀態
        cursor.execute(
            "UPDATE orders SET status = %s WHERE id = %s", (new_status, order_id))

        database.connection.commit()
        cursor.close()
        return True

    except Exception as e:
        database.connection.rollback()
        cursor.close()
        print(f"Error updating order status: {e}")
        # 如果是開發環境，可以考慮 raise e 來看清楚錯誤，但在這裡我們先回傳 False
        return False
