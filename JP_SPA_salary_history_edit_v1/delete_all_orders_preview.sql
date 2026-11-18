-- IMPORTANT: This script does NOT delete orders automatically.
-- Make a verified database backup. Run during a write-free maintenance window.
-- Execute on the intended MySQL database with the same connection throughout.
-- First inspect counts and foreign-key dependencies:
SELECT COUNT(*) AS total_orders FROM orders;
SELECT COUNT(*) AS linked_wallet_records
FROM customer_stored_value_ledger WHERE order_id IS NOT NULL;
SELECT COUNT(*) AS event_links FROM order_events;
SELECT TABLE_NAME, COLUMN_NAME, CONSTRAINT_NAME
FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
WHERE REFERENCED_TABLE_SCHEMA = DATABASE()
  AND REFERENCED_TABLE_NAME = 'orders';

-- Stop if linked_wallet_records > 0: these orders have wallet ledger references.
-- If zero, review these steps before running manually (do not auto-commit):
-- START TRANSACTION;
-- DELETE FROM order_events;
-- DELETE FROM orders;   -- order_items follow ON DELETE CASCADE
-- SELECT COUNT(*) AS remaining_orders FROM orders;
-- COMMIT;               -- ONLY after verifying success; otherwise ROLLBACK

-- Hard deletion does NOT restore inventory or preserve associated customer
-- context inside employee audit views; audit_logs entries may remain orphaned.
