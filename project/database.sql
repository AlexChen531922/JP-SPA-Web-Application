-- =====================================================
-- Railway Production Database Schema
-- Target Database: railway
-- =====================================================

-- 1. 指定使用 Railway 預設資料庫
USE railway;

-- 4. 開啟外鍵檢查
SET FOREIGN_KEY_CHECKS = 1;

-- =====================================================
-- 以下結構保持不變，直接建立表格
-- =====================================================

-- 1. LOOKUP TABLES
CREATE TABLE customer_sources (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE product_categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    image VARCHAR(255),
    display_order INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE course_categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    image VARCHAR(255),
    display_order INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 2. CORE TABLES
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    email VARCHAR(100) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    firstname VARCHAR(100) NOT NULL,
    surname VARCHAR(100) NOT NULL,
    gender ENUM('male', 'female', 'other') DEFAULT 'other',
    birth_date DATE,
    occupation VARCHAR(100),
    phone VARCHAR(50),
    line_id VARCHAR(100),
    source_id INT,
    address TEXT,
    role ENUM('customer', 'staff', 'admin') DEFAULT 'customer',
    reset_token VARCHAR(255),
    reset_token_expiry DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (source_id) REFERENCES customer_sources(id) ON DELETE SET NULL,
    INDEX idx_username (username),
    INDEX idx_email (email),
    INDEX idx_role (role)
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
    last_purchase_date DATETIME DEFAULT NULL,
    last_sale_date DATETIME DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (category_id) REFERENCES product_categories(id)
        ON UPDATE CASCADE ON DELETE SET NULL,
    INDEX idx_category (category_id),
    INDEX idx_active (is_active)
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

-- 3. SCHEDULE & LOGS
CREATE TABLE course_schedules (
    id INT AUTO_INCREMENT PRIMARY KEY,
    course_id INT NOT NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME NOT NULL,
    max_capacity INT DEFAULT 1,
    current_bookings INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    
    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE CASCADE,
    INDEX idx_course_time (course_id, start_time)
);

CREATE TABLE inventory_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL,
    change_amount INT NOT NULL,
    change_type ENUM('purchase', 'sale', 'adjustment', 'return') NOT NULL,
    reference_id INT COMMENT 'Order ID or other reference',
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_by INT,
    
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_product (product_id),
    INDEX idx_created (created_at)
);

CREATE TABLE audit_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    action VARCHAR(50) NOT NULL,
    target_type VARCHAR(50) NOT NULL,
    target_id INT,
    details TEXT,
    ip_address VARCHAR(50),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT
);

-- 4. TRANSACTION TABLES
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
    INDEX idx_status (status)
);

CREATE TABLE order_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    subtotal DECIMAL(10,2) NOT NULL,
    
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT
);

CREATE TABLE bookings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    course_id INT NOT NULL,
    schedule_id INT, 
    sessions_purchased INT NOT NULL DEFAULT 1,
    sessions_remaining INT NOT NULL DEFAULT 1,
    total_amount DECIMAL(10,2) NOT NULL,
    is_first_time BOOLEAN DEFAULT FALSE,
    status ENUM('pending', 'confirmed', 'completed', 'cancelled') DEFAULT 'pending',
    booking_date DATETIME, 
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (customer_id) REFERENCES users(id) ON DELETE RESTRICT,
    FOREIGN KEY (course_id) REFERENCES courses(id) ON DELETE RESTRICT,
    FOREIGN KEY (schedule_id) REFERENCES course_schedules(id) ON DELETE SET NULL,
    INDEX idx_customer (customer_id),
    INDEX idx_status (status)
);

CREATE TABLE booking_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    booking_id INT NOT NULL,
    session_date DATETIME,
    status ENUM('scheduled', 'completed', 'cancelled') DEFAULT 'scheduled',
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (booking_id) REFERENCES bookings(id) ON DELETE CASCADE
);

CREATE TABLE carts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL UNIQUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (customer_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE cart_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    cart_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL DEFAULT 1,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (cart_id) REFERENCES carts(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    UNIQUE KEY unique_cart_product (cart_id, product_id)
);

-- 5. CONTENT & MISC
CREATE TABLE events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(150) NOT NULL,
    description TEXT,
    customer_id INT,
    start_date DATETIME,
    end_date DATETIME,
    duration INT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (customer_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE contact_messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) NOT NULL,
    phone VARCHAR(50),
    line_id VARCHAR(100),
    message TEXT NOT NULL,
    status ENUM('new', 'read', 'responded') DEFAULT 'new',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

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
    
    FOREIGN KEY (author_id) REFERENCES users(id) ON DELETE SET NULL
);

-- =====================================================
-- 6. DUMMY DATA (最簡演示資料)
-- =====================================================

INSERT INTO customer_sources (name) VALUES 
('Facebook'), ('Instagram'), ('Google Search'), ('Friend Recommendation');

INSERT INTO product_categories (name, description, display_order) VALUES
('精油系列', '100% 純天然精油', 1),
('周邊商品', '擴香石、擴香儀等', 2);

INSERT INTO course_categories (name, description, display_order) VALUES
('臉部護理', '專業臉部芳療', 1),
('身體按摩', '全身經絡放鬆', 2);

INSERT INTO products (name, category_id, price, cost, description, stock_quantity) VALUES
('法國真正薰衣草精油 10ml', 1, 580.00, 200.00, '來自普羅旺斯的純淨香氣，助眠放鬆首選。', 50);

INSERT INTO courses (name, category_id, regular_price, experience_price, duration, description) VALUES
('深層紓壓精油按摩', 2, 2500.00, 1800.00, 90, '使用頂級精油進行全身深層肌肉放鬆。');

-- 自動生成未來 30 天的時段 (09:00 - 17:00)
INSERT INTO course_schedules (course_id, start_time, end_time, max_capacity, current_bookings, is_active)
WITH RECURSIVE 
DateRange AS (
    SELECT CURDATE() AS date_val
    UNION ALL
    SELECT date_val + INTERVAL 1 DAY
    FROM DateRange
    WHERE date_val < CURDATE() + INTERVAL 30 DAY
),
TimeSlots AS (
    SELECT '09:00:00' as start_t UNION ALL
    SELECT '11:00:00' UNION ALL
    SELECT '14:00:00' UNION ALL
    SELECT '16:00:00'
)
SELECT 
    c.id, 
    CONCAT(d.date_val, ' ', t.start_t) AS start_time,
    DATE_ADD(CONCAT(d.date_val, ' ', t.start_t), INTERVAL c.duration MINUTE) AS end_time,
    1, 
    0, 
    TRUE
FROM DateRange d
CROSS JOIN TimeSlots t
CROSS JOIN courses c
WHERE c.is_active = TRUE;


-- =====================================================
-- 8. USER TEMPLATES (請在此處填入您的 Hash)
-- =====================================================

-- ⚠️ 請將 'REPLACE_WITH_YOUR_HASHED_PASSWORD' 替換為您用 Python 生成的雜湊字串

-- 1. Insert ADMIN (1位)
INSERT INTO users (username, email, password_hash, firstname, surname, role, created_at) VALUES 
(
    'admin', 
    'admin@example.com', 
    'REPLACE_WITH_YOUR_HASHED_PASSWORD', 
    'Admin', 
    'User', 
    'admin', 
    NOW()
);

-- 2. Insert STAFF (5位)
INSERT INTO users (username, email, password_hash, firstname, surname, role, created_at) VALUES 
(
    'staff01', 
    'staff01@example.com', 
    'REPLACE_WITH_YOUR_HASHED_PASSWORD', 
    'Staff', 
    'One', 
    'staff', 
    NOW()
),
(
    'staff02', 
    'staff02@example.com', 
    'REPLACE_WITH_YOUR_HASHED_PASSWORD', 
    'Staff', 
    'Two', 
    'staff', 
    NOW()
),
(
    'staff03', 
    'staff03@example.com', 
    'REPLACE_WITH_YOUR_HASHED_PASSWORD', 
    'Staff', 
    'Three', 
    'staff', 
    NOW()
),
(
    'staff04', 
    'staff04@example.com', 
    'REPLACE_WITH_YOUR_HASHED_PASSWORD', 
    'Staff', 
    'Four', 
    'staff', 
    NOW()
),
(
    'staff05', 
    'staff05@example.com', 
    'REPLACE_WITH_YOUR_HASHED_PASSWORD', 
    'Staff', 
    'Five', 
    'staff',    
    NOW()
);

-- Sample Blog Post (需有 Admin 存在才能關聯，故放在最後)
INSERT INTO blog_posts (title, summary, content, author_id, status, published_at) 
SELECT '開幕誌慶', '歡迎來到晶品芳療', '<p>我們提供最優質的服務...</p>', id, 'published', NOW()
FROM users WHERE role='admin' LIMIT 1;

-- 1. 在 users 表增加備註欄位 (TEXT 類型可以寫比較多字)
ALTER TABLE users ADD COLUMN notes TEXT;

-- 2. 更新現有的來源名稱 (將英文改成中文)
-- 假設您原本資料庫裡是存英文 name，如果找不到會沒反應，沒關係
UPDATE customer_sources SET name = 'Google搜尋網站' WHERE name = 'google search';
UPDATE customer_sources SET name = '朋友推薦' WHERE name LIKE '%friend%'; 

-- 3. 新增缺少的來源
INSERT INTO customer_sources (name) VALUES ('過路客');
INSERT INTO customer_sources (name) VALUES ('Tiktok');

-- 6. 建立行銷活動表 (Campaigns) 
CREATE TABLE IF NOT EXISTS campaigns (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(100) NOT NULL,
    description TEXT,
    start_date DATE,
    end_date DATE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 7. 補上訂單與活動的關聯 
ALTER TABLE orders ADD COLUMN campaign_id INT;
