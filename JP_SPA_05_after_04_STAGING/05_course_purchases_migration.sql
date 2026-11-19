-- JP SPA 05: additive schema; do NOT run before 02 + 04 migrations.
-- MySQL DDL auto-commits: first BACK UP, verify on staging, then apply only ONCE.
-- Never rewrite old bookings, orders or stored value ledger balances.
ALTER TABLE courses
  ADD COLUMN is_public TINYINT(1) NOT NULL DEFAULT 1 COMMENT 'Visible on public website',
  ADD COLUMN uses_store_consumables TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Fixed-price store materials, no customer inventory credit';

CREATE TABLE course_sale_tiers (
  course_id INT NOT NULL,
  sessions SMALLINT NOT NULL,
  default_total DECIMAL(12,2) NOT NULL,
  PRIMARY KEY(course_id,sessions),
  CONSTRAINT fk_course_tier_course FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE CASCADE,
  CONSTRAINT chk_course_tier_count CHECK(sessions BETWEEN 2 AND 100),
  CONSTRAINT chk_course_tier_price CHECK(default_total>0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE customer_course_purchases (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  request_key VARCHAR(64) NOT NULL,
  customer_id INT NOT NULL,
  course_id INT NOT NULL,
  total_sessions SMALLINT NOT NULL,
  completed_sessions SMALLINT NOT NULL DEFAULT 0,
  reserved_sessions SMALLINT NOT NULL DEFAULT 0,
  total_paid DECIMAL(12,2) NOT NULL,
  default_total DECIMAL(12,2) NOT NULL,
  status ENUM('active') NOT NULL DEFAULT 'active',
  sold_by INT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_course_purchase_request(request_key),
  KEY idx_course_purchases_customer(customer_id,course_id),
  CONSTRAINT fk_course_purchase_customer FOREIGN KEY(customer_id) REFERENCES users(id) ON DELETE RESTRICT,
  CONSTRAINT fk_course_purchase_course FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE RESTRICT,
  CONSTRAINT fk_course_purchase_actor FOREIGN KEY(sold_by) REFERENCES users(id) ON DELETE RESTRICT,
  CONSTRAINT chk_course_purchase_sessions CHECK(total_sessions BETWEEN 1 AND 100),
  CONSTRAINT chk_course_purchase_counts CHECK(completed_sessions>=0 AND reserved_sessions>=0
            AND completed_sessions+reserved_sessions<=total_sessions),
  CONSTRAINT chk_course_purchase_paid CHECK(total_paid>0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE customer_course_payments (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  purchase_id BIGINT NOT NULL,
  method ENUM('cash','credit_card','bank_transfer','stored_value','other') NOT NULL,
  amount DECIMAL(12,2) NOT NULL,
  operated_by INT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_course_payments_purchase(purchase_id),
  CONSTRAINT fk_course_payment_purchase FOREIGN KEY(purchase_id) REFERENCES customer_course_purchases(id) ON DELETE RESTRICT,
  CONSTRAINT fk_course_payment_actor FOREIGN KEY(operated_by) REFERENCES users(id) ON DELETE RESTRICT,
  CONSTRAINT chk_course_payment_amount CHECK(amount>0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

ALTER TABLE bookings
  ADD COLUMN course_purchase_id BIGINT NULL,
  ADD COLUMN course_booking_request_key VARCHAR(64) NULL,
  ADD UNIQUE KEY uq_bookings_course_request(course_booking_request_key),
  ADD KEY idx_booking_course_purchase(course_purchase_id),
  ADD CONSTRAINT fk_booking_course_purchase FOREIGN KEY(course_purchase_id)
    REFERENCES customer_course_purchases(id) ON DELETE RESTRICT;

CREATE TABLE customer_course_allocations (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  purchase_id BIGINT NOT NULL,
  booking_id INT NOT NULL,
  status ENUM('reserved','completed','released') NOT NULL DEFAULT 'reserved',
  recognized_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  operated_by INT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at DATETIME NULL,
  UNIQUE KEY uq_course_allocation_booking(booking_id),
  KEY idx_course_allocation_purchase(purchase_id,status),
  CONSTRAINT fk_course_allocation_purchase FOREIGN KEY(purchase_id) REFERENCES customer_course_purchases(id) ON DELETE RESTRICT,
  CONSTRAINT fk_course_allocation_booking FOREIGN KEY(booking_id) REFERENCES bookings(id) ON DELETE RESTRICT,
  CONSTRAINT fk_course_allocation_actor FOREIGN KEY(operated_by) REFERENCES users(id) ON DELETE RESTRICT,
  CONSTRAINT chk_course_allocation_recognition CHECK(recognized_amount>=0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE customer_course_events (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  purchase_id BIGINT NOT NULL,
  booking_id INT NULL,
  action ENUM('sale','reserve','complete','release','restore') NOT NULL,
  delta_reserved SMALLINT NOT NULL DEFAULT 0,
  delta_completed SMALLINT NOT NULL DEFAULT 0,
  recognized_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  operated_by INT NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_course_events_purchase(purchase_id,id),
  KEY idx_course_events_booking(booking_id),
  CONSTRAINT fk_course_event_purchase FOREIGN KEY(purchase_id)
    REFERENCES customer_course_purchases(id) ON DELETE RESTRICT,
  CONSTRAINT fk_course_event_booking FOREIGN KEY(booking_id)
    REFERENCES bookings(id) ON DELETE RESTRICT,
  CONSTRAINT fk_course_event_actor FOREIGN KEY(operated_by)
    REFERENCES users(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- WARNING: historical bookings remain legacy bookings. No automatic entitlements
-- or transfer of their old sessions_remaining are invented in this migration.
