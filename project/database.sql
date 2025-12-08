-- =====================================================
-- Complete E-Commerce & Booking System Database Schema
-- =====================================================

DROP DATABASE IF EXISTS ecommerce_booking_system;
CREATE DATABASE ecommerce_booking_system
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE ecommerce_booking_system;

-- =====================================================
-- USER MANAGEMENT
-- =====================================================

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    email VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    firstname VARCHAR(100) NOT NULL,
    surname VARCHAR(100) NOT NULL,
    phone VARCHAR(50),
    line_id VARCHAR(100),
    address TEXT,
    role ENUM('customer', 'staff', 'admin') DEFAULT 'customer',
    reset_token VARCHAR(255),
    reset_token_expiry DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_username (username),
    INDEX idx_email (email),
    INDEX idx_role (role)
);

-- =====================================================
-- CUSTOMER SOURCE
-- =====================================================

CREATE TABLE customer_sources (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================
-- PRODUCT MANAGEMENT
-- =====================================================

CREATE TABLE product_categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    image VARCHAR(255),
    display_order INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    category_id INT,
    cost DECIMAL(10,2) DEFAULT 0.00,
    price DECIMAL(10,2) NOT NULL,
    unit VARCHAR(50) DEFAULT '件',
    description TEXT,
    image VARCHAR(255),
    stock_quantity INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (category_id) REFERENCES product_categories(id)
        ON UPDATE CASCADE ON DELETE SET NULL,
    INDEX idx_category (category_id),
    INDEX idx_active (is_active)
);

-- =====================================================
-- COURSE MANAGEMENT
-- =====================================================

CREATE TABLE course_categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    image VARCHAR(255),
    display_order INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE courses (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(150) NOT NULL,
    category_id INT,
    description TEXT,
    service_fee DECIMAL(10,2) DEFAULT 0.00,
    product_fee DECIMAL(10,2) DEFAULT 0.00,
    regular_price DECIMAL(10,2) NOT NULL,
    experience_price DECIMAL(10,2),
    duration INT COMMENT 'Duration in minutes',
    sessions INT DEFAULT 1 COMMENT 'Number of sessions in package',
    image VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (category_id) REFERENCES course_categories(id)
        ON UPDATE CASCADE ON DELETE SET NULL,
    INDEX idx_category (category_id),
    INDEX idx_active (is_active)
);

-- =====================================================
-- ORDERS (PRODUCTS)
-- =====================================================

CREATE TABLE orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    status ENUM('pending', 'confirmed', 'completed', 'cancelled') DEFAULT 'pending',
    total_amount DECIMAL(10,2) NOT NULL,
    payment_method VARCHAR(50) DEFAULT 'offline',
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (customer_id) REFERENCES users(id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    INDEX idx_customer (customer_id),
    INDEX idx_status (status),
    INDEX idx_created (created_at)
);

CREATE TABLE order_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    subtotal DECIMAL(10,2) NOT NULL,
    
    FOREIGN KEY (order_id) REFERENCES orders(id)
        ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id)
        ON DELETE RESTRICT,
    INDEX idx_order (order_id),
    INDEX idx_product (product_id)
);

-- =====================================================
-- BOOKINGS (COURSES)
-- =====================================================

CREATE TABLE bookings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    course_id INT NOT NULL,
    sessions_purchased INT NOT NULL DEFAULT 1,
    sessions_remaining INT NOT NULL DEFAULT 1,
    total_amount DECIMAL(10,2) NOT NULL,
    is_first_time BOOLEAN DEFAULT FALSE,
    status ENUM('pending', 'confirmed', 'completed', 'cancelled') DEFAULT 'pending',
    booking_date DATETIME,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (customer_id) REFERENCES users(id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (course_id) REFERENCES courses(id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    INDEX idx_customer (customer_id),
    INDEX idx_course (course_id),
    INDEX idx_status (status),
    INDEX idx_created (created_at)
);

CREATE TABLE booking_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    booking_id INT NOT NULL,
    session_date DATETIME,
    status ENUM('scheduled', 'completed', 'cancelled') DEFAULT 'scheduled',
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (booking_id) REFERENCES bookings(id)
        ON DELETE CASCADE,
    INDEX idx_booking (booking_id),
    INDEX idx_date (session_date)
);

-- =====================================================
-- SHOPPING CART
-- =====================================================

CREATE TABLE carts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL UNIQUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (customer_id) REFERENCES users(id)
        ON UPDATE CASCADE ON DELETE CASCADE,
    INDEX idx_customer (customer_id)
);

CREATE TABLE cart_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cart_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL DEFAULT 1,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (cart_id) REFERENCES carts(id)
        ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id)
        ON DELETE CASCADE,
    UNIQUE KEY unique_cart_product (cart_id, product_id),
    INDEX idx_cart (cart_id),
    INDEX idx_product (product_id)
);

-- =====================================================
-- EVENTS / ACTIVITIES
-- =====================================================

CREATE TABLE events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(150) NOT NULL,
    description TEXT,
    customer_id INT,
    start_date DATETIME,
    end_date DATETIME,
    duration INT COMMENT 'Duration in minutes',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (customer_id) REFERENCES users(id)
        ON UPDATE CASCADE ON DELETE SET NULL,
    INDEX idx_customer (customer_id),
    INDEX idx_start (start_date)
);

-- =====================================================
-- INVENTORY TRACKING
-- =====================================================

CREATE TABLE inventory_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL,
    change_amount INT NOT NULL,
    change_type ENUM('purchase', 'sale', 'adjustment', 'return') NOT NULL,
    reference_id INT COMMENT 'Order ID or other reference',
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_by INT,
    
    FOREIGN KEY (product_id) REFERENCES products(id)
        ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(id)
        ON DELETE SET NULL,
    INDEX idx_product (product_id),
    INDEX idx_created (created_at)
);

-- =====================================================
-- CONTACT MESSAGES
-- =====================================================

CREATE TABLE contact_messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) NOT NULL,
    phone VARCHAR(50),
    line_id VARCHAR(100),
    message TEXT NOT NULL,
    status ENUM('new', 'read', 'responded') DEFAULT 'new',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_status (status),
    INDEX idx_created (created_at)
);

-- =====================================================
-- BLOG POSTS
-- =====================================================

CREATE TABLE blog_posts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    summary TEXT,
    content LONGTEXT NOT NULL,
    image VARCHAR(255),
    author_id INT,
    status ENUM('draft', 'published', 'archived') DEFAULT 'draft',
    published_at DATETIME,
    views INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (author_id) REFERENCES users(id)
        ON UPDATE CASCADE ON DELETE SET NULL,
    INDEX idx_status (status),
    INDEX idx_published (published_at),
    INDEX idx_created (created_at)
);

-- =====================================================
-- SAMPLE DATA
-- =====================================================

-- Insert admin user (password: admin123)
INSERT INTO users (username, email, password_hash, firstname, surname, role) VALUES
('admin', 'admin@jparomatic.com', '240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9', 'Admin', 'User', 'admin');

-- Insert staff user (password: staff123)
INSERT INTO users (username, email, password_hash, firstname, surname, role) VALUES
('staff', 'staff@jparomatic.com', 'a8ae6c1b0e9b7c4b5e8f3d2a1c9b8e7f6d5c4b3a2e1d0c9b8a7f6e5d4c3b2a1', 'Staff', 'Member', 'staff');

-- Product categories
INSERT INTO product_categories (name, description, display_order) VALUES
('精油系列', '100% 純天然精油', 1),
('護膚產品', '專業護膚保養品', 2),
('芳療用品', '芳香療法相關用品', 3);

-- Course categories
INSERT INTO course_categories (name, description, display_order) VALUES
('臉部護理', '專業臉部芳療課程', 1),
('身體護理', '全身放鬆芳療課程', 2),
('特殊療程', '針對性深層護理', 3);

-- Sample products
INSERT INTO products (name, category_id, price, description, stock_quantity) VALUES
('薰衣草精油 10ml', 1, 580.00, '法國進口純天然薰衣草精油', 50),
('玫瑰保濕精華', 2, 1280.00, '高效保濕修護精華液', 30),
('芳香擴香儀', 3, 2980.00, '智能定時芳香擴香器', 20),
('檀香木', 4, 3980.00, '好香的檀香木', 50);

-- Sample courses
INSERT INTO courses (name, category_id, regular_price, experience_price, duration, description) VALUES
('臉部深層清潔', 1, 1800.00, 1200.00, 90, '深層清潔毛孔，改善膚質'),
('全身精油按摩', 2, 2500.00, 1800.00, 120, '舒緩壓力，放鬆身心'),
('淋巴排毒療程', 3, 3200.00, 2400.00, 150, '促進循環，排除毒素'),
('檀香木芳療', 3, 3980.00, 2980.00, 180, '好香的檀香木');

-- Customer sources
INSERT INTO customer_sources (name) VALUES
('Facebook'), ('Instagram'), ('TikTok'), ('朋友推薦'), ('網路搜尋'), ('其他');

-- Sample blog posts
INSERT INTO blog_posts (title, summary, content, image, author_id, status, published_at) VALUES
('精油芳療的神奇功效', '了解精油如何改善您的身心健康，讓生活更美好', 
'<h2>精油的力量</h2><p>精油是從植物中萃取的天然物質，擁有多種療癒特性...</p>', 
'img/post1.jpg', 1, 'published', NOW()),

('選擇適合您的課程', '從臉部護理到全身按摩，找到最適合您的芳療課程',
'<h2>如何選擇課程</h2><p>選擇適合的芳療課程需要考慮多個因素...</p>',
'img/post2.jpg', 1, 'published', NOW()),

('居家芳療小技巧', '在家也能享受專業級的芳香療法體驗',
'<h2>居家芳療指南</h2><p>創造舒適的居家芳療環境...</p>',
'img/post3.jpg', 1, 'published', NOW());

-- =============================================
-- 1. 建立或確保測試使用者存在 (不指定 ID，讓系統自動產生)
-- =============================================
INSERT IGNORE INTO users (username, email, password_hash, firstname, surname, role, created_at) VALUES
('alice', 'alice@test.com', 'hash123', 'Alice', 'Chen', 'customer', DATE_SUB(NOW(), INTERVAL 30 DAY)),
('bob', 'bob@test.com', 'hash123', 'Bob', 'Wang', 'customer', DATE_SUB(NOW(), INTERVAL 20 DAY)),
('carol', 'carol@test.com', 'hash123', 'Carol', 'Lin', 'customer', DATE_SUB(NOW(), INTERVAL 10 DAY));

-- ⭐ 關鍵步驟：抓取這些使用者的真實 ID 存入變數
SET @alice_id = (SELECT id FROM users WHERE email = 'alice@test.com' LIMIT 1);
SET @bob_id = (SELECT id FROM users WHERE email = 'bob@test.com' LIMIT 1);
SET @carol_id = (SELECT id FROM users WHERE email = 'carol@test.com' LIMIT 1);

-- =============================================
-- 2. 插入產品訂單 (使用變數 @alice_id, @bob_id)
-- =============================================
-- Alice 的訂單 (已完成)
INSERT INTO orders (customer_id, total_amount, status, created_at) 
VALUES (@alice_id, 3560.00, 'completed', DATE_SUB(NOW(), INTERVAL 5 DAY));

SET @order1_id = LAST_INSERT_ID();

-- 插入訂單細項 (動態抓取產品 ID)
INSERT INTO order_items (order_id, product_id, quantity, unit_price, subtotal) 
SELECT @order1_id, id, 2, price, price*2 FROM products WHERE name LIKE '%精油%' LIMIT 1;

INSERT INTO order_items (order_id, product_id, quantity, unit_price, subtotal) 
SELECT @order1_id, id, 1, price, price FROM products WHERE name LIKE '%擴香%' LIMIT 1;

-- Bob 的訂單 (待確認)
INSERT INTO orders (customer_id, total_amount, status, created_at) 
VALUES (@bob_id, 1280.00, 'pending', NOW());

SET @order2_id = LAST_INSERT_ID();

INSERT INTO order_items (order_id, product_id, quantity, unit_price, subtotal) 
SELECT @order2_id, id, 1, price, price FROM products WHERE name LIKE '%精華%' LIMIT 1;

-- =============================================
-- 3. 插入課程預約 (使用變數 @alice_id, @carol_id)
-- =============================================
-- Alice 預約臉部護理 (已確認)
INSERT INTO bookings (customer_id, course_id, sessions_purchased, sessions_remaining, total_amount, is_first_time, status, created_at)
SELECT @alice_id, id, 1, 1, experience_price, TRUE, 'confirmed', DATE_SUB(NOW(), INTERVAL 3 DAY)
FROM courses WHERE name LIKE '%臉部%' LIMIT 1;

-- Carol 預約全身按摩 (已完成)
INSERT INTO bookings (customer_id, course_id, sessions_purchased, sessions_remaining, total_amount, is_first_time, status, created_at)
SELECT @carol_id, id, 5, 4, regular_price * 5 * 0.9, FALSE, 'completed', DATE_SUB(NOW(), INTERVAL 8 DAY)
FROM courses WHERE name LIKE '%全身%' LIMIT 1;

-- =============================================
-- 4. 插入活動 (使用變數)
-- =============================================
-- 過去的活動
INSERT INTO events (title, description, customer_id, start_date, end_date, duration)
VALUES 
('Alice 膚質諮詢', '首次體驗前評估', @alice_id, DATE_SUB(NOW(), INTERVAL 3 DAY), DATE_ADD(DATE_SUB(NOW(), INTERVAL 3 DAY), INTERVAL 1 HOUR), 60);

-- 未來的活動
INSERT INTO events (title, description, customer_id, start_date, end_date, duration)
VALUES 
(
    '店內盤點日', 
    '全店庫存盤點，暫停營業半天', 
    NULL, 
    DATE_ADD(NOW(), INTERVAL 7 DAY), 
    DATE_ADD(NOW(), INTERVAL 7 DAY) + INTERVAL 4 HOUR, -- 修正: 先算出日期，再加 4 小時
    240
),
(
    'Bob 產品教學', 
    '擴香儀使用教學', 
    @bob_id, 
    DATE_ADD(NOW(), INTERVAL 2 DAY), 
    DATE_ADD(NOW(), INTERVAL 2 DAY) + INTERVAL 30 MINUTE, -- 修正: 先算出日期，再加 30 分鐘
    30
);

CREATE TABLE audit_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    action VARCHAR(50) NOT NULL,        -- 例如: create_product, update_course
    target_type VARCHAR(50) NOT NULL,   -- 例如: product, course, event
    target_id INT,                      -- 被操作物件的 ID
    details TEXT,                       -- JSON 格式或文字描述修改內容
    ip_address VARCHAR(50),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT
);

-- 新增課程時段表
CREATE TABLE course_schedules (
    id INT AUTO_INCREMENT PRIMARY KEY,
    course_id INT NOT NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME NOT NULL,
    max_capacity INT DEFAULT 1, -- 該時段最大容納人數
    current_bookings INT DEFAULT 0, -- 目前已預約人數
    is_active BOOLEAN DEFAULT TRUE,
    
    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE,
    INDEX idx_course_time (course_id, start_time)
);

-- 修改 bookings 表，增加關聯到具體時段
ALTER TABLE bookings ADD COLUMN schedule_id INT;
ALTER TABLE bookings ADD CONSTRAINT fk_schedule FOREIGN KEY (schedule_id) REFERENCES course_schedules(id);

INSERT INTO course_schedules (course_id, start_time, end_time, max_capacity)
VALUES (
    (SELECT id FROM courses LIMIT 1), -- 自動抓第一門課的 ID
    DATE_ADD(CURDATE(), INTERVAL 1 DAY) + INTERVAL 10 HOUR, -- 明天 10:00
    DATE_ADD(CURDATE(), INTERVAL 1 DAY) + INTERVAL 11 HOUR + INTERVAL 30 MINUTE, -- 明天 11:30
    1
);

-- 課程 1 的時段：明天下午 2 點
INSERT INTO course_schedules (course_id, start_time, end_time, max_capacity)
VALUES (
    (SELECT id FROM courses LIMIT 1),
    DATE_ADD(CURDATE(), INTERVAL 1 DAY) + INTERVAL 14 HOUR, -- 明天 14:00
    DATE_ADD(CURDATE(), INTERVAL 1 DAY) + INTERVAL 15 HOUR + INTERVAL 30 MINUTE,
    1
);

-- 課程 2 (假設是全身按摩) 的時段：後天下午 3 點
INSERT INTO course_schedules (course_id, start_time, end_time, max_capacity)
VALUES (
    (SELECT id FROM courses LIMIT 1 OFFSET 1), -- 自動抓第二門課的 ID
    DATE_ADD(CURDATE(), INTERVAL 2 DAY) + INTERVAL 15 HOUR, -- 後天 15:00
    DATE_ADD(CURDATE(), INTERVAL 2 DAY) + INTERVAL 17 HOUR,
    1
);

-- 1. 擴充使用者欄位
ALTER TABLE users 
ADD COLUMN gender ENUM('male', 'female', 'other') DEFAULT 'other' AFTER surname,
ADD COLUMN birth_date DATE AFTER gender,
ADD COLUMN occupation VARCHAR(100) AFTER birth_date,
ADD COLUMN source_id INT AFTER line_id;

-- 2. 建立關聯 (如果尚未建立)
ALTER TABLE users
ADD CONSTRAINT fk_user_source FOREIGN KEY (source_id) REFERENCES customer_sources(id) ON DELETE SET NULL;

-- 3. 更新現有 Dummy Data (範例)
UPDATE users SET gender='female', birth_date='1990-05-20', occupation='教師', line_id='U123456', source_id=1 WHERE username='alice';
UPDATE users SET gender='male', birth_date='1985-08-15', occupation='工程師', line_id='U654321', source_id=2 WHERE username='bob';  

-- ========================================================
-- 自動生成未來 90 天的預約時段 (所有課程，09:00-18:00)
-- ========================================================

INSERT INTO course_schedules (course_id, start_time, end_time, max_capacity, current_bookings, is_active)
WITH RECURSIVE 
-- 1. 生成日期範圍 (未來 90 天)
DateRange AS (
    SELECT CURDATE() AS date_val
    UNION ALL
    SELECT date_val + INTERVAL 1 DAY
    FROM DateRange
    WHERE date_val < CURDATE() + INTERVAL 90 DAY
),
-- 2. 定義營業時間的「開場時間點」 (每小時一個時段)
-- 您可以根據需求修改間隔，例如每 30 分鐘： UNION ALL SELECT '09:30:00' ...
TimeSlots AS (
    SELECT '09:00:00' as start_t UNION ALL
    SELECT '10:00:00' UNION ALL
    SELECT '11:00:00' UNION ALL
    SELECT '12:00:00' UNION ALL
    SELECT '13:00:00' UNION ALL
    SELECT '14:00:00' UNION ALL
    SELECT '15:00:00' UNION ALL
    SELECT '16:00:00' UNION ALL
    SELECT '17:00:00' -- 最後一個開場時間 (結束時間會是 17:00 + 課程時長)
)
SELECT 
    c.id, 
    CONCAT(d.date_val, ' ', t.start_t) AS start_time,
    -- 結束時間 = 開始時間 + 該課程的時長 (分鐘)
    DATE_ADD(CONCAT(d.date_val, ' ', t.start_t), INTERVAL c.duration MINUTE) AS end_time,
    1, -- max_capacity (每個時段限 1 人，若要多人可改成 2 或 3)
    0, -- current_bookings
    TRUE
FROM DateRange d
CROSS JOIN TimeSlots t
CROSS JOIN courses c
WHERE c.is_active = TRUE -- 只針對上架中的課程
-- 排除現有的時段 (避免重複插入)
AND NOT EXISTS (
    SELECT 1 FROM course_schedules cs 
    WHERE cs.course_id = c.id 
    AND cs.start_time = CONCAT(d.date_val, ' ', t.start_t)
);

-- 測試資料
-- customer
-- ID:Testcus
-- Password: testcus123 