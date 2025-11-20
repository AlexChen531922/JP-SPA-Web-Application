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
('芳香擴香儀', 3, 2980.00, '智能定時芳香擴香器', 20);

-- Sample courses
INSERT INTO courses (name, category_id, regular_price, experience_price, duration, description) VALUES
('臉部深層清潔', 1, 1800.00, 1200.00, 90, '深層清潔毛孔，改善膚質'),
('全身精油按摩', 2, 2500.00, 1800.00, 120, '舒緩壓力，放鬆身心'),
('淋巴排毒療程', 3, 3200.00, 2400.00, 150, '促進循環，排除毒素');

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