📸 Event Stock Image Platform
This project is a stock image service centred on event and festival photography.
It connects users who need authentic event photos with photographers or organisers who provide them.
Users can search and filter images by event type, date, and location, and sort results by latest or popularity. Each photo contains metadata such as event name, shooting date, location, and photographer. Based on the chosen license, images can be added to the cart and downloaded after payment.
staffs can upload and tag new images, set license types (e.g., free, editorial, commercial), and manage their portfolio. These features provide a reliable way for staffs to distribute and profit from their work, while users can efficiently access the images they need.

✨ Features
🔍 Discover event photos with search & filters
🛜Home Page (Search, Filter, Browse):
   * Search bar on top of the home page, get result by typing at least first 2 characters.
   * Filter by (latest, popular, price Low to High, price High to Low) The uploaded date, views, price shows on the images cards. 
📷 public gallery for customer
   * view image thumbnail, title, uploaded_date, price, resolution, license, event, categories, staff_name
   * go to item detail page
🛒 Add to Cart and Secure Checkout
   * Users can add an unlimited number of images to their shopping cart from the item detail page.
   * Users can view all selected images and the total price in their shopping cart.
   * Users can remove individual images from the cart.
   * Users can clear all images from the cart at once.
   * Users can complete the payment by entering valid credit card details.
   * Credit card details are validated during the checkout process.
   * After a successful payment, users can see the “Download” button on the download page.
📊 staff gallery for specific staff
   * staff can view their own gallery
   * every staff can view other staff's gallery
🎆 staff management (Dashboard)
   * every staff can manage their own images (upload, read, edit, delete)
   * not permitted for accessing another staff's gallery
🟣 Admin management (Dashboard)
   * Admin tabs for managing all images, users, orders, categories, events, licenses (create, read, edit, delete)
👤 Role-based access for admins, staffs, and users

✅ Authentication and Access Controls
💼 User Authentication System
Implement a complete user authentication system, including registration, login, and logout, using hashed passwords and session-based authentication.
   * Clicking the top-right "Sign In" button on the homepage allows users to log in as an admin, staff, or customer.
   * If the user does not have an account, they can switch to the Sign Up tab.
🪪Passwords are hashed using SHA-256 during registration and login.
   * Login details are stored in the session for further use.
👤Admin Access Control
   * Logging in as an admin redirects to the management page, where the admin can:
     1. Upload, edit, and delete images
     2. Manage users and orders
     3. Add, edit, and delete events, categories, and licenses
   * These functions are accessible through different tabs on the management page.
👤staff Access Control
   * Logging in as a staff redirects to the management page, where the staff can:
     1. Upload, edit, and delete their own images
     2. Uploaded images are displayed on both the dashboard and gallery pages.
👤Customer Access Control
   * Logging in as a customer stays on the homepage, where a cart button appears on the top-right corner.
   * Customers can:
     1. Click any image to open the item details page
     2. Add items to the cart
     3. Access the payment page via the cart button to complete the purchase.
     4. Access control is enforced using custom decorators (e.g., @admin_required) or Flask-Login session-based role checks.
🔀Different user roles display different navigation options on the top-right of the homepage.
🎨 Responsive UI
   * support small size for mobile with hamburger menus on navigation
🍔For responsive design, these options also appear in the hamburger menu.
   * desktop, tablet size will include wide version of navigation, header, footer

< Database >
The database IFN582 includes tables for users, images, events, categories, license, carts, orders, and payment. 
Sample data demonstrates multiple categories, license types, and three completed transactions. Foreign keys, unique constraints, and indexes ensure data integrity and efficient queries.
The purpose of using indexes in a database is to improve its efficiency and speed. 
When an index is applied, MySQL does not need to scan all the data from the beginning to find a specific record. 
Instead, it can quickly locate the desired information by jumping directly to the relevant data, similar to how an index in a book helps you find a topic without reading every page. 
By reducing the amount of data that needs to be searched, indexes significantly improve query performance, especially for large tables. 
This makes the database faster and more efficient, allowing applications to handle queries and transactions with better responsiveness.

💻 Tech Stack
- Frontend: HTML5, CSS3, Bootstrap
- Backend: Flask, Jinja2
- Database: MySQL

📋 Setup & Run Instructions

1. Install dependencies:
   pip install -r requirements.txt

2. Run the application:
   python3 run.py Mac
   python run.py  Windows

> The application will be available at http://127.0.0.1:5000