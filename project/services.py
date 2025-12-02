# =====================================================
# ADMIN ORDER STATUS UPDATE WITH INVENTORY SYNC
# =====================================================


def admin_update_order_with_inventory(order_id, new_status, admin_id):
    """
    Update order status and handle inventory accordingly
    Called from admin.py when status is changed
    """
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    try:
        # Get current order status
        cursor.execute("""
            SELECT status 
            FROM orders 
            WHERE id = %s
        """, (order_id,))

        order = cursor.fetchone()
        old_status = order['status']

        # If changing from non-cancelled to cancelled
        if old_status != 'cancelled' and new_status == 'cancelled':
            # Get order items
            cursor.execute("""
                SELECT product_id, quantity 
                FROM order_items 
                WHERE order_id = %s
            """, (order_id,))

            items = cursor.fetchall()

            # ⭐ RESTORE INVENTORY
            for item in items:
                cursor.execute("""
                    UPDATE products 
                    SET stock_quantity = stock_quantity + %s 
                    WHERE id = %s
                """, (item['quantity'], item['product_id']))

                # ⭐ LOG RESTORATION
                cursor.execute("""
                    INSERT INTO inventory_logs 
                    (product_id, change_amount, change_type, reference_id, notes, created_by)
                    VALUES (%s, %s, 'return', %s, 'Order cancelled by admin', %s)
                """, (item['product_id'], item['quantity'], order_id, admin_id))

        # Update order status
        cursor.execute("""
            UPDATE orders 
            SET status = %s 
            WHERE id = %s
        """, (new_status, order_id))

        database.connection.commit()
        cursor.close()
        return True

    except Exception as e:
        database.connection.rollback()
        cursor.close()
        print(f"Error updating order status: {e}")
        return False
