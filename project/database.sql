
CREATE DATABASE IF NOT EXISTS IFN582;
USE IFN582;

DROP TABLE IF EXISTS payments;
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS cart_items;
DROP TABLE IF EXISTS carts;
DROP TABLE IF EXISTS image_license;
DROP TABLE IF EXISTS image_category;
DROP TABLE IF EXISTS licenses;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS images;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(100) UNIQUE NOT NULL,
  firstname VARCHAR(100),
  surname VARCHAR(100),
  email VARCHAR(100) UNIQUE NOT NULL,
  password_hash VARCHAR(255),
  role ENUM('admin', 'vendor', 'customer') NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE events (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  event_date DATE,
  location VARCHAR(255),
  description TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE images (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  title VARCHAR(255) NOT NULL,
  description TEXT,
  resolution VARCHAR(50),
  format VARCHAR(10),
  uploaded_at DATE,
  price DECIMAL(10,2),
  event_id INT NOT NULL,
  vendor_id INT,
  url VARCHAR(255),
  views INT,
  downloads INT,
  deleted_at DATETIME NULL,
  -- protect specific data even if user is deleted images from cart or orders
  FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE RESTRICT,
  -- when vender is deleted, set to vendor id NULL
  FOREIGN KEY (vendor_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX idx_images_event_id ON images(event_id);
CREATE INDEX idx_images_vendor_id ON images(vendor_id);

CREATE TABLE categories (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) UNIQUE NOT NULL
);

CREATE TABLE image_category (
  image_id INT,
  category_id INT,
  added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (image_id, category_id),
  -- When a parent table record is deleted, the child table records that refer to that record are also automatically deleted
  FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE,
  FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
);

-- improve the performance of queries filtering by image_id or category_id
CREATE INDEX idx_image_category_image_id ON image_category(image_id);
CREATE INDEX idx_image_category_category_id ON image_category(category_id);

CREATE TABLE licenses (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  type VARCHAR(50) NOT NULL,
  terms TEXT
);

CREATE TABLE image_license (
  image_id INT,
  license_id INT,
  price_override DECIMAL(10,2),
  PRIMARY KEY (image_id, license_id),
  FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE,
  FOREIGN KEY (license_id) REFERENCES licenses(id) ON DELETE CASCADE
);
CREATE INDEX idx_image_license_image_id ON image_license(image_id);
CREATE INDEX idx_image_license_license_id ON image_license(license_id);

CREATE TABLE carts (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id INT UNIQUE NOT NULL,
  created_at DATETIME,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX idx_carts_user_id ON carts(user_id);

CREATE TABLE cart_items (
  cart_id INT NOT NULL,
  image_id INT NOT NULL,
  added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (cart_id, image_id),
  FOREIGN KEY (cart_id) REFERENCES carts(id) ON DELETE CASCADE,
  FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
);
CREATE INDEX idx_cart_items_cart_id ON cart_items(cart_id);
CREATE INDEX idx_cart_items_image_id ON cart_items(image_id);

CREATE TABLE orders (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  created_at DATETIME,
  status VARCHAR(50),
  total_amount DECIMAL(10,2),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE order_items (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  order_id   INT NOT NULL,
  image_id   INT NULL,
  license_id INT NOT NULL,
  price DECIMAL(10,2) NOT NULL,
  quantity INT NOT NULL DEFAULT 1,
  image_title VARCHAR(255) NULL,
  image_url   VARCHAR(255) NULL,
  CONSTRAINT fk_order_items_order
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
  CONSTRAINT fk_order_items_image
    FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE SET NULL,
  CONSTRAINT fk_order_items_license
    FOREIGN KEY (license_id) REFERENCES licenses(id) ON DELETE RESTRICT,
  -- restriction that prevents the same image and license from being duplicated within the same order.
  UNIQUE KEY uq_order_item_unique (order_id, image_id, license_id),

  -- the same reason as above, improve query performance
  INDEX idx_order_items_order_id (order_id),
  INDEX idx_order_items_image_id (image_id),
  INDEX idx_order_items_license_id (license_id)
);

CREATE TABLE payments (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  order_id INT,
  amount DECIMAL(10,2),
  method VARCHAR(50),
  status VARCHAR(50),
  paid_at DATE,
  account_name VARCHAR(100),
  FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
);
-- the same reason as above, improve query performance
CREATE INDEX idx_payments_order_id ON payments(order_id);

INSERT INTO users (id, username, firstname, surname, email, password_hash, role) VALUES
(1, 'adabell', 'Ada', 'Bell', 'ada.bell@example.com', '5f6fcf358f1d94f7ccc683fa2056d82721f2d6c2a81b2676861a4d5d385d7c7f','admin'),
(2, 'nolansmith', 'Nolan', 'Smith', 'nolan.smith@example.com', 'bffc5bda5fbfcf60756392516fd2f63ed69572cbfd0227158f8601953838f412','admin'),
(3, 'admin', 'Admin', 'System', 'admin.system@example.com', '8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918', 'admin'),
(4, 'veramartinez', 'Vera', 'Martinez', 'vera.martinez@example.com', '7823dcdae7981ce97bdce89c29016631ca61904fdfadc1a8d671fd7e7422ca5b', 'vendor'),
(5, 'omargabi', 'Omar', 'Gabi', 'omar.gabi@example.com', '2c0ccdae44015a4e1f7373d724655d613f3cb0cfd1bb71215e210d0a1cd8b255', 'vendor'),
(6, 'venTest', 'Ven', 'Dor', 'ven.dor@example.com', '630ba09448af522154f38ef7685ef1f44b0f3e9430f80829a03ce24f400f3754', 'vendor'),
(7, 'chloewill', 'Chloe', 'Will', 'chloe.will@example.com', '218a2e9b3f918fd16ae888d7e287c5b07e049fe35bee30d8515df5f790ca7f9d', 'customer'),
(8, 'benjohnson', 'Ben', 'Johnson', 'ben.johnson@example.com', '3730ef77e186d9bb70162ee5a6e109b2ccb31592d187f9c6328fb3b89abfd114', 'customer'),
(9, 'cusTest', 'Cus', 'Tomer', 'cus.tomer@example.com', 'b6c45863875e34487ca3c155ed145efe12a74581e27befec5aa661b8ee8ca6dd', 'customer');

INSERT INTO events (id, name, event_date, location, description) VALUES
(1, 'Tourism', '2025-09-07', 'Australia', 'The best view in Australia.'),
(2, 'Photography Contest', '2025-08-10', 'QUT Campus', 'Public photographic contest in QUT.'),
(3, 'WorldTour', '2025-09-28', 'Worldwide', 'Every corner in the world.');

INSERT INTO categories (id, name) VALUES
(1, 'nature'), (2, 'architecture'), (3, 'event'), (4, 'night'), (5, 'day'), (6, 'festival');

INSERT INTO licenses (id, type, terms) VALUES
(1, 'non-commercial', 'Personal use only; no redistribution.'),
(2, 'commercial', 'Commercial use allowed with attribution.'),
(3, 'editorial', 'Editorial use in news and blogs only.');

INSERT INTO images (id, title, description, resolution, format, uploaded_at, price, event_id, vendor_id, url, views, downloads) VALUES
(1, 'Polar Bear', 'Polar Bear in Arctic', '4000x2667', 'jpg', '2025-09-01', 9.99, 2, 3, 'img/category_animals.jpg','102','132'),
(2, 'White Building', 'Beautiful Architecture', '4096x2731', 'jpg', '2025-09-01', 12.0, 2, 3, 'img/category_architecture.jpg','212','45'),
(3, 'Festival Crowd', 'Sydney Opera', '3840x2160', 'jpg', '2025-09-07', 11.5, 1, 4, 'img/category_australia.jpg','124','33'),
(4, 'Healthy Food', 'The picture of healthy food', '4032x2268', 'jpg', '2025-09-07', 10.0, 2, 4, 'img/category_food.jpg','234','45'),
(5, 'Planets', 'The corner in the house', '4000x2667', 'jpg', '2025-08-12', 8.5, 2, 3, 'img/category_lifestyle.jpg','122','33'),
(6, 'Blue Mountain', 'The great mountain view', '4000x2667', 'jpg', '2025-08-10', 7.5, 1, 3, 'img/category_nature.jpg','98','22'),
(7, 'People', 'The crowd of people', '4096x2731', 'jpg', '2025-08-10', 9.0, 2, 4, 'img/category_people.jpg','22','34'),
(8, 'River View', 'The view of river', '4000x2667', 'jpg', '2025-07-15', 12.0, 1, 4, 'img/category_wallpapers.jpg','22','12'),
(9, 'Arts', 'The great arts from a famous artist', '3840x2160', 'jpg', '2025-09-28', 13.5, 2, 3, 'img/gallery_1.jpg','123','34'),
(10, 'Ocean View', 'Ocean view in Australia', '6000x4000', 'jpg', '2025-09-28', 14.0, 3, 3, 'img/gallery_2.jpg','456','32'),
(11, 'Wallpaper', 'Classic style of the wallpaper', '4000x2667', 'jpg', '2025-07-30', 6.99, 2, 4, 'img/gallery_3.jpg','245','45'),
(12, 'Aurora', 'Aurora in Tasmina', '4096x2731', 'jpg', '2025-07-30', 9.99, 3, 4, 'img/gallery_4.jpg','345','54'),
(13, 'Geometry', 'Geometry for the wallpaper', '4000x2667', 'jpg', '2025-09-06', 8.0, 2, 3, 'img/gallery_5.jpg','44','55'),
(14, 'White Curtain', 'The white world', '4000x2667', 'jpg', '2025-08-05', 7.25, 2, 3, 'img/gallery_6.jpg','543','54'),
(15, 'River Side', 'Calm in the river', '4096x2731', 'jpg', '2025-08-05', 8.75, 3, 4, 'img/gallery_7.jpg','65','34');

INSERT INTO image_category (image_id, category_id) VALUES
(1,1),(1,5),(2,2),(2,5),(3,3),(3,4),(4,5),(5,1),(6,1),(7,5),
(8,1),(9,3),(10,1),(10,5),(11,2),(12,1),(12,4),(13,3),(14,3),(15,1);

INSERT INTO image_license (image_id, license_id) VALUES
(1,1),(2,2),(3,2),(4,3),(5,2),(6,1),(7,2),(8,3),(9,2),
(10,2),(11,1),(12,2),(13,3),(14,1),(15,2);

INSERT INTO carts (id, user_id, created_at) VALUES
(1,5,'2025-09-20'), (2,9,'2025-09-22');

INSERT INTO cart_items (cart_id, image_id) VALUES
(1,1),(1,3),(2,10);

INSERT INTO orders (id, user_id, created_at, status, total_amount) VALUES
(1,5,'2025-09-21','completed',21.49),
(2,9,'2025-09-23','completed',26.99),
(3,5,'2025-09-25','completed',20.99);

INSERT INTO order_items (order_id, image_id, license_id, price, quantity, image_title, image_url)
SELECT 1, i.id, 2,  9.99, 1, i.title, i.url FROM images i WHERE i.id=1;
INSERT INTO order_items (order_id, image_id, license_id, price, quantity, image_title, image_url)
SELECT 1, i.id, 3, 11.50, 1, i.title, i.url FROM images i WHERE i.id=3;

INSERT INTO order_items (order_id, image_id, license_id, price, quantity, image_title, image_url)
SELECT 2, i.id, 2, 14.00, 1, i.title, i.url FROM images i WHERE i.id=10;
INSERT INTO order_items (order_id, image_id, license_id, price, quantity, image_title, image_url)
SELECT 2, i.id, 1, 12.99, 1, i.title, i.url FROM images i WHERE i.id=11;

INSERT INTO order_items (order_id, image_id, license_id, price, quantity, image_title, image_url)
SELECT 3, i.id, 2,  9.99, 1, i.title, i.url FROM images i WHERE i.id=12;
INSERT INTO order_items (order_id, image_id, license_id, price, quantity, image_title, image_url)
SELECT 3, i.id, 2, 11.00, 1, i.title, i.url FROM images i WHERE i.id=5;

INSERT INTO payments (id, order_id, amount, method, status, paid_at, account_name) VALUES
(1,1,21.49,'credit_card','paid','2025-09-21','Ada Bell'),
(2,2,26.99,'paypal','paid','2025-09-23','Nolan Smith'),
(3,3,20.99,'bank_transfer','paid','2025-09-25','Vera Martinez');