# JP SPA Web Application

A comprehensive web application designed for **JP SPA** customers to review services, book courses, and purchase products, while providing a robust admin panel for business owners to manage daily operations.

> [點此跳轉至中文版說明 (Traditional Chinese)](#-晶品芳療網站系統-jp-spa-web-application)

---

## ✨ Features

### 👤 Customer Portal
* **Browse & Search:** Intuitive interface to discover SPA courses and beauty products with category filters.
* **Online Booking:** Real-time scheduling system allowing customers to book specific courses and time slots.
* **E-Commerce Cart:** Seamless shopping experience with a secure cart and checkout process for products.
* **Member Center:** Dashboard for users to manage profiles, view booking history, and track order status.

### 🟣 Admin Management Panel
* **Dashboard:** Visualized overview of sales revenue, booking statistics, and customer growth.
* **Content Management (CMS):** Create, read, update, and delete (CRUD) products, courses, and blog posts.
* **Order & Booking Management:** Process customer orders, confirm bookings, and manage schedule availability.
* **Inventory Control:** Automatic stock tracking and inventory adjustments.
* **Role-Based Access Control:** Secure access levels for Administrators and Staff members.

## 💻 Tech Stack

* **Frontend:** HTML5, CSS3, Bootstrap 5, JavaScript
* **Backend:** Python 3.10+, Flask
* **Database:** MySQL (Production ready)
* **Template Engine:** Jinja2
* **Security:** SHA-256 / PBKDF2 Password Hashing, Session-based Authentication, CSRF Protection

## 📋 Setup & Installation

### Prerequisites
* Python 3.8 or higher
* MySQL Server installed and running

### Installation Steps

1.  **Clone the repository**
    ```bash
    git clone [https://github.com/YourUsername/JP-SPA-Web-Application.git](https://github.com/YourUsername/JP-SPA-Web-Application.git)
    cd JP-SPA-Web-Application
    ```

2.  **Set up Virtual Environment**
    ```bash
    # Windows
    python -m venv venv
    venv\Scripts\activate

    # Mac/Linux
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Database Configuration**
    * Create a MySQL database named `ecommerce_booking_system`.
    * Import the provided `database.sql` file to initialize tables and dummy data.
    * Create a `.env` file in the root directory and configure your database credentials:
        ```text
        MYSQL_HOST=localhost
        MYSQL_USER=root
        MYSQL_PASSWORD=your_password
        MYSQL_DB=ecommerce_booking_system
        SECRET_KEY=your_secret_key
        ```

5.  **Run the Application**
    ```bash
    # Windows
    python run.py

    # Mac/Linux
    python3 run.py
    ```

6.  **Access the Website**
    * Open your browser and navigate to: `http://127.0.0.1:5000`

## 📄 License & Copyright

**© 2025 JP AROMATIC SPA. All Rights Reserved.**

This software is proprietary and developed exclusively for the use of JP AROMATIC SPA.
Unauthorized copying, modification, distribution, or commercial use of this software without written permission is strictly prohibited.

---
---

# 晶品芳療網站系統 (JP SPA Web Application)

這是一個為 **晶品芳療 (JP AROMATIC SPA)** 量身打造的全方位網站應用程式。整合了前台客戶服務（課程瀏覽、線上預約、產品購物）與強大的後台管理系統，協助業主數位化營運並提升管理效率。

## ✨ 功能特色

### 👤 客戶端功能 (Front-End)
* **瀏覽與搜尋**：輕鬆探索各類芳療課程與美容產品，支援分類篩選。
* **線上預約系統**：即時查看可預約時段，線上完成課程預約，減少人工溝通成本。
* **電子商務購物車**：完整的購物流程，支援將產品加入購物車並進行結帳。
* **會員中心**：客戶可登入管理個人資料、查看歷史預約紀錄與訂單處理進度。

### 🟣 後台管理系統 (Admin Panel)
* **營運儀表板**：視覺化呈現銷售額、預約數與客戶成長數據，掌握營運狀況。
* **產品與課程管理**：完整的 CRUD 功能，可新增、修改、上架或下架產品與課程資訊。
* **訂單與預約管理**：處理客戶訂單狀態，管理預約排程與人員調度。
* **庫存管理**：自動扣減庫存，並提供手動調整功能，精準掌握庫存水位。
* **權限控制**：區分「管理員」與「員工」權限，確保資料安全。

## 💻 技術架構

* **前端**：HTML5, CSS3, Bootstrap 5, JavaScript
* **後端**：Python 3.10+, Flask 框架
* **資料庫**：MySQL (關聯式資料庫)
* **模板引擎**：Jinja2
* **資安防護**：PBKDF2 密碼加密、Session 驗證機制、CSRF 防護

## 📋 安裝與執行指南

### 前置需求
* Python 3.8 或以上版本
* MySQL 資料庫伺服器

### 安裝步驟

1.  **下載專案程式碼**
    ```bash
    git clone [https://github.com/YourUsername/JP-SPA-Web-Application.git](https://github.com/YourUsername/JP-SPA-Web-Application.git)
    cd JP-SPA-Web-Application
    ```

2.  **建立虛擬環境**
    ```bash
    # Windows 使用者
    python -m venv venv
    venv\Scripts\activate

    # Mac/Linux 使用者
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **安裝必要套件**
    ```bash
    pip install -r requirements.txt
    ```

4.  **資料庫設定**
    * 在 MySQL 中建立一個名為 `ecommerce_booking_system` 的資料庫。
    * 匯入專案中的 `database.sql` 檔案以初始化資料表與範例資料。
    * 在專案根目錄建立 `.env` 檔案，並設定您的資料庫連線資訊：
        ```text
        MYSQL_HOST=localhost
        MYSQL_USER=root
        MYSQL_PASSWORD=你的資料庫密碼
        MYSQL_DB=ecommerce_booking_system
        SECRET_KEY=隨機生成的亂碼
        ```

5.  **啟動應用程式**
    ```bash
    # Windows
    python run.py

    # Mac/Linux
    python3 run.py
    ```

6.  **開啟網站**
    * 打開瀏覽器並前往：`http://127.0.0.1:5000`

## 📄 版權與授權聲明

**© 2025 晶品芳療 (JP AROMATIC SPA). 版權所有。**

本軟體為 **晶品芳療** 之專有軟體。
未經書面授權，嚴禁任何形式的複製、修改、散佈或用於商業用途。