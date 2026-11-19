-- JP SPA 06: apply ONCE, after 02/04/05 schema migrations; STAGING FIRST.
-- MySQL ALTER/CREATE DDL commits automatically. Back up before execution.
-- No old booking/order/customer balances are rewritten.

ALTER TABLE bookings
    ADD COLUMN is_unpaid_course_booking TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Pure reservation, no paid course entitlement yet';

ALTER TABLE customer_course_purchases
    ADD COLUMN material_mode ENUM('store','customer','mixed') NOT NULL DEFAULT 'store',
    ADD COLUMN component_hand_fee DECIMAL(12,2) NOT NULL DEFAULT 0,
    ADD COLUMN component_store_fee DECIMAL(12,2) NOT NULL DEFAULT 0,
    ADD COLUMN component_customer_value DECIMAL(12,2) NOT NULL DEFAULT 0
        COMMENT 'Historical customer-owned product value: NOT new cash or a payment method',
    ADD COLUMN price_adjustment DECIMAL(12,2) NOT NULL DEFAULT 0,
    ADD COLUMN requires_material_confirmation TINYINT(1) NOT NULL DEFAULT 0;

CREATE TABLE course_service_completions (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    booking_id INT NOT NULL,
    request_key VARCHAR(64) NOT NULL,
    operated_by INT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_course_service_booking (booking_id),
    UNIQUE KEY uq_course_service_request (request_key),
    CONSTRAINT fk_course_service_booking FOREIGN KEY (booking_id)
        REFERENCES bookings(id) ON DELETE RESTRICT,
    CONSTRAINT fk_course_service_actor FOREIGN KEY (operated_by)
        REFERENCES users(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE course_service_materials (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    completion_id BIGINT NOT NULL,
    owner_type ENUM('customer','store') NOT NULL,
    owner_customer_id INT NOT NULL,
    inventory_id INT NOT NULL,
    request_id BIGINT NOT NULL,
    amount_used DECIMAL(10,2) NOT NULL,
    capacity_unit VARCHAR(2) NOT NULL,
    before_amount DECIMAL(10,2) NOT NULL,
    after_amount DECIMAL(10,2) NOT NULL,
    UNIQUE KEY uq_course_material_unique (completion_id,inventory_id),
    KEY idx_course_material_owner (owner_customer_id),
    CONSTRAINT fk_course_material_completion FOREIGN KEY (completion_id)
        REFERENCES course_service_completions(id) ON DELETE RESTRICT,
    CONSTRAINT fk_course_material_owner FOREIGN KEY (owner_customer_id)
        REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT fk_course_material_inventory FOREIGN KEY (inventory_id)
        REFERENCES customer_inventory(id) ON DELETE RESTRICT,
    CONSTRAINT fk_course_material_request FOREIGN KEY (request_id)
        REFERENCES customer_inventory_requests(id) ON DELETE RESTRICT,
    CONSTRAINT chk_course_material_used CHECK (amount_used > 0),
    CONSTRAINT chk_course_material_after CHECK (after_amount >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 05 purchases default requires_material_confirmation=0; no invented material records.
-- Historical bookings remain unchanged and are NOT auto-marked pure or paid.
