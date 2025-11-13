from flask import Blueprint, render_template, request, session, flash, redirect, url_for, abort
from .models import Image
import os
from hashlib import sha256
from .forms import LoginForm, RegisterForm, AddItemForm, CheckoutForm
from functools import wraps
from . import database
from .db import check_for_user, add_user, check_username_exists, get_current_user_id, get_current_user_role, get_user_role
from datetime import datetime
from werkzeug.utils import secure_filename
import MySQLdb.cursors


bp = Blueprint('main', __name__)

UPLOAD_FOLDER = 'project/static/img'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


def login_required(f):
    """Require user to be logged in"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session or not session['logged_in']:
            flash('Please login first', 'warning')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function


def role_required(*roles):
    """Require user to have specific role(s)"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'logged_in' not in session or not session['logged_in']:
                flash('Please login first', 'warning')
                return redirect(url_for('main.login'))

            user_role = get_current_user_role()
            if user_role not in roles:
                flash('You do not have permission to access this page', 'error')
                return redirect(url_for('main.index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def save_image(image_file):
    if image_file and allowed_file(image_file.filename):
        filename = secure_filename(image_file.filename)
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = f"{timestamp}_{filename}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        image_file.save(filepath)
        return f"img/{filename}"
    return None


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@bp.route('/')
def index():
    user = None
    search_query = request.args.get('q', '').strip()
    category_filter = request.args.get('category', '').strip().lower()
    sort = request.args.get('sort', 'latest')

    like_query = f"%{search_query}%" if search_query else None
    category_query = f"%{category_filter}%" if category_filter else None

    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    base_sql = """
        SELECT
            i.id,
            i.title,
            i.price,
            i.url,
            i.resolution,
            i.uploaded_at,
            i.vendor_id,
            u.username AS vendor_name,
            e.name     AS event_name,
            i.views,
            GROUP_CONCAT(DISTINCT c.name ORDER BY c.name SEPARATOR '||') AS category_names_csv,
            GROUP_CONCAT(DISTINCT c.id   ORDER BY c.id   SEPARATOR ',')  AS category_ids_csv,
            GROUP_CONCAT(DISTINCT l.type ORDER BY l.type SEPARATOR '||') AS license_types_csv,
            GROUP_CONCAT(DISTINCT l.id   ORDER BY l.id   SEPARATOR ',')  AS license_ids_csv
        FROM images i
        LEFT JOIN users          u  ON u.id  = i.vendor_id
        LEFT JOIN events         e  ON e.id  = i.event_id
        LEFT JOIN image_category ic ON ic.image_id = i.id
        LEFT JOIN categories     c  ON c.id  = ic.category_id
        LEFT JOIN image_license  il ON il.image_id = i.id
        LEFT JOIN licenses       l  ON l.id  = il.license_id
    """

    filters = ["i.deleted_at IS NULL"]
    params = []
    if like_query:
        filters.append("""
            (
                i.title LIKE %s OR
                COALESCE(u.firstname, '') LIKE %s OR
                COALESCE(u.surname,  '') LIKE %s OR
                e.name LIKE %s OR
                c.name LIKE %s
            )
        """)
        params += [like_query] * 5

    if category_filter:
        filters.append("LOWER(c.name) LIKE %s")
        params.append(category_query)

    if filters:
        base_sql += " AND " + " AND ".join(filters)

    base_sql += """
        GROUP BY
            i.id, i.title, i.price, i.url, i.resolution, i.uploaded_at,
            i.vendor_id, u.username, e.name, i.views
    """

    if sort == 'popular':
        base_sql += " ORDER BY i.views DESC, i.uploaded_at DESC"
    elif sort == 'price-asc':
        base_sql += " ORDER BY i.price ASC, i.uploaded_at DESC"
    elif sort == 'price-desc':
        base_sql += " ORDER BY i.price DESC, i.uploaded_at DESC"
    else:
        base_sql += " ORDER BY i.uploaded_at DESC, i.id DESC"

    cursor.execute(base_sql, params)
    images = cursor.fetchall()
    cursor.close()

    for row in images:
        row['category_names'] = (row.get('category_names_csv') or '').split(
            '||') if row.get('category_names_csv') else []
        row['license_types'] = (row.get('license_types_csv') or '').split(
            '||') if row.get('license_types_csv') else []

    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT name FROM categories ORDER BY name")
    categories = [row['name'] for row in cursor.fetchall()]
    cursor.close()

    return render_template(
        'index.html',
        images=images,
        user=user,
        q=search_query,
        categories=categories,
        active_category=category_filter,
        sort=sort
    )


@bp.route('/item_details/<int:id>')
def item_detail(id):
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute('SELECT * FROM images WHERE id = %s', (id,))
    row = cursor.fetchone()

    if row is None:
        abort(404, description="Image not found")

    cursor.execute(
        'SELECT firstname, surname FROM users WHERE id = %s', (row['vendor_id'],))
    vendor_row = cursor.fetchone()
    vendor = f"{vendor_row['firstname']} {vendor_row['surname']}"
    cursor.execute("""SELECT c.name
        FROM image_category AS ic
        JOIN categories     AS c ON c.id = ic.category_id
        WHERE ic.image_id = %s
        ORDER BY c.name;
        """, (id,))
    categories = cursor.fetchall()
    cursor.close()

    image = Image(
        id=row['id'],
        vendor=vendor,
        title=row['title'],
        description=row['description'],
        categories=categories,
        resolution=row['resolution'],
        format=row['format'],
        file_name=f"{row['id']}.{row['format']}" if row['format'] else None,
        uploaded_at=row['uploaded_at'],
        price=row['price'],
        event_id=row['event_id'],
        url=row['url'],
        featured_in=row.get('featured_in') or [],
        tags=row.get('tags') or [],
        views=row.get('views'),
        downloads=row.get('downloads')
    )

    return render_template('item_details.html', item=image)


@bp.route('/register/', methods=['POST', 'GET'])
def register():
    form = RegisterForm()
    if request.method == 'POST':
        if form.validate_on_submit():
            user_exists = check_username_exists(form.username.data)
            if user_exists:
                flash('User already exists', 'error')
                return redirect(url_for('main.index'))
            form.password.data = sha256(
                form.password.data.encode()).hexdigest()
            success = add_user(form)

            try:
                success
                flash('Registration successful!')
                return redirect(url_for('main.index'))
            except Exception as e:
                flash(f'Registration failed: {str(e)}', 'error')
            return redirect(url_for('main.index'))
        else:
            for _, errs in form.errors.items():
                for msg in errs:
                    flash(msg, 'error')
            return redirect(url_for('main.index'))

    return render_template('index.html', form=form)


@bp.route('/login/', methods=['POST', 'GET'])
def login():
    form = LoginForm()

    if request.method == 'POST':
        if form.validate_on_submit():
            form.password.data = sha256(
                form.password.data.encode()).hexdigest()

            user, role = check_for_user(form.username.data, form.password.data)
            if not user:
                flash('Invalid username or password', 'error')
                return redirect(url_for('main.index'))

            session['user'] = {
                'user_id': user.info.id,
                'username': user.username,
                'firstname': user.info.firstname,
                'surname': user.info.surname,
                'email': user.info.email,
                'role': role,
                'is_admin': role == 'admin',
                'is_vendor': role == 'vendor',
                'is_customer': role == 'customer'
            }
            session['logged_in'] = True
            flash('Login successful!')

            if role == 'admin':
                return redirect(url_for('main.vendor_management'))
            elif role == 'vendor':
                return redirect(url_for('vendor.management'))
            else:
                return redirect(url_for('main.index'))
        else:
            for _, errs in form.errors.items():
                for msg in errs:
                    flash(msg, 'error')

    return render_template('index.html', form=form)


@bp.route('/logout/')
def logout():
    session.pop('user', None)
    session.pop('logged_in', None)
    flash('You have been logged out.')
    return redirect(url_for('main.index'))


@bp.route('/admin/')
@role_required('admin')
def admin():
    if 'user' not in session or session['user']['user_id'] == 0:
        flash('Please log in before managing orders.', 'error')
        return redirect(url_for('main.login'))
    if not session['user']['is_admin']:
        flash('You do not have permission to manage orders.', 'error')
        return redirect(url_for('main.index'))
    itemform = AddItemForm()
    return render_template('vendor_management.html', itemform=itemform)


@bp.route('/admin/vendor customer/<int:user_id>/delete', methods=['POST'])
@role_required('admin')
def delete_user(user_id):
    cursor = database.connection.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    users = cursor.fetchone()

    cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
    database.connection.commit()
    flash('User deleted successfully', 'success')

    cursor.close()
    return redirect(url_for('main.vendor_management'))


@bp.route('/admin/vendor/management', methods=['GET', 'POST'])
@role_required('admin')
def vendor_management():
    tab = request.args.get('tab', 'images')
    edit_id = request.args.get('edit_id', type=int)
    edit_user_id = request.args.get('edit_user_id', type=int)

    form = AddItemForm()
    user_id = get_current_user_id()

    cur = database.connection.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT id, name FROM events ORDER BY name")
    events = cur.fetchall()
    cur.execute("SELECT id, name FROM categories ORDER BY name")
    category_list = cur.fetchall()
    cur.execute("SELECT id, type FROM licenses ORDER BY type")
    licenses = cur.fetchall()
    cur.close()

    form.event_id.choices = [(e['id'], e['name']) for e in events]
    form.category_ids.choices = [(c['id'], c['name']) for c in category_list]
    form.license_id.choices = [(l['id'], l['type']) for l in licenses]

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'edit_user':
            uid = request.form.get('user_id', type=int)
            email = (request.form.get('email') or '').strip()
            role = request.form.get('role')

            if role not in ('admin', 'vendor', 'customer'):
                flash('Invalid role.', 'danger')
                return redirect(url_for('main.vendor_management', tab='users'))

            if not email:
                flash('Email is required.', 'danger')
                return redirect(url_for('main.vendor_management', tab='users', edit_user_id=uid))

            try:
                cur = database.connection.cursor()
                cur.execute("""
                    UPDATE users SET email=%s, role=%s WHERE id=%s
                """, (email, role, uid))
                database.connection.commit()
                flash('User updated.', 'success')
            except Exception as e:
                database.connection.rollback()
                flash(f'Update failed: {e}', 'danger')
            finally:
                cur.close()

            return redirect(url_for('main.vendor_management', tab='users'))

        elif action == 'delete_vendor':
            uid = request.form.get('delete_vendor_id', type=int)
            try:
                cur = database.connection.cursor()
                cur.execute("DELETE FROM users WHERE id=%s", (uid,))
                database.connection.commit()
                flash('User deleted.', 'success')
            except Exception as e:
                database.connection.rollback()
                flash(f'Delete failed: {e}', 'danger')
            finally:
                cur.close()

            return redirect(url_for('main.vendor_management', tab='users'))

        elif action == 'update_order_status':
            order_id = request.form.get('order_id', type=int)
            status = request.form.get('status')

            allowed = {'pending', 'paid', 'completed', 'cancelled'}
            if status not in allowed:
                flash('Invalid status.', 'danger')
                return redirect(url_for('main.vendor_management', tab='orders'))

            try:
                cur = database.connection.cursor()
                cur.execute(
                    "UPDATE orders SET status=%s WHERE id=%s", (status, order_id))
                database.connection.commit()
                flash('Order status updated.', 'success')
            except Exception as e:
                database.connection.rollback()
                flash(f'Failed to update status: {e}', 'danger')
            finally:
                cur.close()

            return redirect(url_for('main.vendor_management', tab='orders'))

        elif action == 'add_event':
            name = (request.form.get('name') or '').strip()
            if not name:
                flash('Event name is required.', 'danger')
            else:
                try:
                    cur = database.connection.cursor()
                    cur.execute(
                        "INSERT INTO events (name) VALUES (%s)", (name,))
                    database.connection.commit()
                    flash('Event added.', 'success')
                except Exception as e:
                    database.connection.rollback()
                    flash(f'Failed to add: {e}', 'danger')
                finally:
                    cur.close()
            return redirect(url_for('main.vendor_management', tab='events'))

        elif action == 'delete_event':
            _id = request.form.get('id', type=int)
            try:
                cur = database.connection.cursor()
                cur.execute("DELETE FROM events WHERE id=%s", (_id,))
                database.connection.commit()
                flash('Event deleted.', 'success')
            except Exception as e:
                database.connection.rollback()
                flash(f'Failed to delete: {e}', 'danger')
            finally:
                cur.close()
            return redirect(url_for('main.vendor_management', tab='events'))

        elif action == 'add_category':
            name = (request.form.get('name') or '').strip()
            if not name:
                flash('Category name is required.', 'danger')
            else:
                try:
                    cur = database.connection.cursor()
                    cur.execute(
                        "INSERT INTO categories (name) VALUES (%s)", (name,))
                    database.connection.commit()
                    flash('Category added.', 'success')
                except Exception as e:
                    database.connection.rollback()
                    flash(f'Failed to add: {e}', 'danger')
                finally:
                    cur.close()
            return redirect(url_for('main.vendor_management', tab='categories'))

        elif action == 'delete_category':
            _id = request.form.get('id', type=int)
            try:
                cur = database.connection.cursor()
                cur.execute("DELETE FROM categories WHERE id=%s", (_id,))
                database.connection.commit()
                flash('Category deleted.', 'success')
            except Exception as e:
                database.connection.rollback()
                flash(f'Failed to delete: {e}', 'danger')
            finally:
                cur.close()
            return redirect(url_for('main.vendor_management', tab='categories'))

        elif action == 'add_license':
            _type = (request.form.get('type') or '').strip()
            if not _type:
                flash('License type is required.', 'danger')
            else:
                try:
                    cur = database.connection.cursor()
                    cur.execute(
                        "INSERT INTO licenses (type) VALUES (%s)", (_type,))
                    database.connection.commit()
                    flash('License added.', 'success')
                except Exception as e:
                    database.connection.rollback()
                    flash(f'Failed to add: {e}', 'danger')
                finally:
                    cur.close()
            return redirect(url_for('main.vendor_management', tab='licenses'))

        elif action == 'delete_license':
            _id = request.form.get('id', type=int)
            try:
                cur = database.connection.cursor()
                cur.execute("DELETE FROM licenses WHERE id=%s", (_id,))
                database.connection.commit()
                flash('License deleted.', 'success')
            except Exception as e:
                database.connection.rollback()
                flash(f'Failed to delete: {e}', 'danger')
            finally:
                cur.close()
            return redirect(url_for('main.vendor_management', tab='licenses'))

        elif action == 'add_image':
            selected_categories = [
                int(x) for x in request.form.getlist('category_ids')]
            if not selected_categories:
                flash("Please select at least one category.", "danger")
                return redirect(url_for('main.vendor_management', tab='images'))

            if not form.validate_on_submit():
                for field, errs in form.errors.items():
                    for err in errs:
                        flash(f"{field}: {err}", 'danger')
                return redirect(url_for('main.vendor_management', tab='images'))

            image_filename = save_image(form.image.data)
            if not image_filename:
                flash("Image file is required.", "danger")
                return redirect(url_for('main.vendor_management', tab='images'))

            try:
                cur = database.connection.cursor()
                cur.execute("""
                    INSERT INTO images
                        (title, description, resolution, format, uploaded_at, price, event_id, vendor_id, url)
                    VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s, %s)
                """, (
                    (form.title.data or '').strip(),
                    form.description.data or '',
                    form.resolution.data,
                    form.format.data,
                    float(form.price.data or 0),
                    int(form.event_id.data),
                    user_id,
                    image_filename,
                ))
                image_id = cur.lastrowid
                if selected_categories:
                    cur.executemany(
                        "INSERT INTO image_category (image_id, category_id) VALUES (%s, %s)",
                        [(image_id, cid) for cid in selected_categories]
                    )
                if form.license_id.data:
                    cur.execute(
                        "INSERT INTO image_license (image_id, license_id) VALUES (%s, %s)",
                        (image_id, int(form.license_id.data))
                    )

                database.connection.commit()
                flash('Image added successfully!', 'success')
            except Exception as e:
                database.connection.rollback()
                flash(f'Failed to add: {e}', 'danger')
            finally:
                cur.close()

            return redirect(url_for('main.vendor_management', tab='images'))

        elif action == 'delete_image':
            image_id = request.form.get('image_id', type=int)
            if not image_id:
                flash('Invalid image id.', 'danger')
                return redirect(url_for('main.vendor_management', tab='images'))

            try:
                cur = database.connection.cursor()
                cur.execute(
                    "UPDATE images SET deleted_at = NOW() WHERE id=%s", (image_id,))
                cur.execute(
                    "DELETE FROM cart_items WHERE image_id=%s", (image_id,))
                cur.execute(
                    "DELETE FROM image_category WHERE image_id=%s", (image_id,))
                cur.execute(
                    "DELETE FROM image_license  WHERE image_id=%s", (image_id,))
                database.connection.commit()
                flash('Image deleted.', 'success')
            except Exception as e:
                database.connection.rollback()
                flash(f'Failed to delete: {e}', 'danger')
            finally:
                cur.close()

            return redirect(url_for('main.vendor_management', tab='images'))

    images, users, orders = [], [], []
    cur = database.connection.cursor(MySQLdb.cursors.DictCursor)

    if tab == 'images':
        cur.execute("""
            SELECT
                i.id, i.title, i.price, i.url, i.resolution, i.format, i.uploaded_at,
                u.username AS vendor_name, e.name AS event_name,
                GROUP_CONCAT(DISTINCT c.name ORDER BY c.name SEPARATOR '||') AS category_names_csv,
                GROUP_CONCAT(DISTINCT l.type ORDER BY l.type SEPARATOR '||') AS license_types_csv
            FROM images i
            LEFT JOIN users          u  ON u.id  = i.vendor_id
            LEFT JOIN events         e  ON e.id  = i.event_id
            LEFT JOIN image_category ic ON ic.image_id = i.id
            LEFT JOIN categories     c  ON c.id  = ic.category_id
            LEFT JOIN image_license  il ON il.image_id = i.id
            LEFT JOIN licenses       l  ON l.id  = il.license_id
            WHERE i.deleted_at IS NULL
            GROUP BY i.id, i.title, i.price, i.url, i.resolution, i.format, i.uploaded_at, u.username, e.name
            ORDER BY i.uploaded_at DESC, i.id DESC
        """)
        images = cur.fetchall()
        for row in images:
            row['category_names'] = (row.get('category_names_csv') or '').split(
                '||') if row.get('category_names_csv') else []
            row['license_types'] = (row.get('license_types_csv') or '').split(
                '||') if row.get('license_types_csv') else []

    elif tab == 'users':
        cur.execute("""
            SELECT u.id, u.username, u.email, u.role, u.created_at,
                   COUNT(i.id) AS image_count
            FROM users u
            LEFT JOIN images i ON u.id = i.vendor_id
            GROUP BY u.id, u.username, u.email, u.role, u.created_at
            ORDER BY u.created_at DESC
        """)
        users = cur.fetchall()

    elif tab == 'orders':
        cur.execute("""
            SELECT o.id, o.created_at, o.status, o.total_amount,
                   u.username AS customer
            FROM orders o
            JOIN users u ON u.id = o.user_id
            ORDER BY o.created_at DESC, o.id DESC
        """)
        orders = cur.fetchall()

    cur.close()

    return render_template(
        'vendor_management.html',
        tab=tab,
        images=images,
        users=users,
        orders=orders,
        events=events,
        category_list=category_list,
        licenses=licenses,
        form=form,
        edit_id=edit_id,
        edit_user_id=edit_user_id,
        current_user_role='admin',
    )


@bp.route("/checkout/", methods=['GET', 'POST'])
def get_cart():
    cur = database.connection.cursor()
    form = CheckoutForm()
    # Fetch the current user_id
    user_id = get_current_user_id()
    if not user_id:
        abort(404, description="We can't find the user")

    # Fetch the corresponding cart which is belong to the current user_id
    cur.execute("SELECT id FROM carts WHERE user_id = %s", (user_id,))
    user_cart = cur.fetchone()

    # Fetch the user's infos(name,email) and store in the user_infos
    cur.execute("SELECT username, email FROM users WHERE id =%s", (user_id,))
    user_info = cur.fetchone()
    user_infos = {
        'name': user_info['username'],
        'email': user_info['email']
    }

    # Fetch selected image_id from corresponding cart_items table
    cur.execute("SELECT image_id from cart_items WHERE cart_id = %s",
                (user_cart['id'],))
    image_id_in_cart = cur.fetchall()
    image_id_in_cart = list(image_id_in_cart)

    cart_details = []
    total = 0
    total_items = 0

    # Fetch license, category(type) data of images
    for ci in image_id_in_cart:
        cur.execute(
            "SELECT license_id FROM image_license WHERE image_id = %s", (ci['image_id'],))
        licenseID = cur.fetchall()
        for lid in licenseID:
            cur. execute("SELECT type FROM licenses WHERE id = %s",
                         (lid['license_id'],))
            licenseName = cur.fetchall()

        cur.execute(
            "SELECT category_id FROM image_category WHERE image_id = %s", (ci['image_id'],))
        typeID = cur.fetchall()
        for ti in typeID:
            cur.execute("SELECT name FROM categories WHERE id = %s",
                        (ti['category_id'],))
            typeName = cur.fetchall()

        cur.execute("SELECT * FROM images WHERE id = %s", (ci['image_id'],))
        Image_info = cur.fetchall()

        # Integrate required infos of images into cart_details
        cart_item_clean = []
        for item in Image_info:
            cart_item_clean = {
                "image_id": item['id'][0] if isinstance(item['id'], list) else item['id'],
                "title": item['title'][0] if isinstance(item['title'], list) else item['title'],
                "price": float(item['price'][0]) if isinstance(item['price'], list) else item['price'],
                "category": typeName,
                "licenses": licenseName,
                "url": item['url'][0] if isinstance(item['url'], list) else item['url']
            }
        cart_details.append(cart_item_clean)
        total_items += 1
        total += item['price']

    # Auto-fill user's information into the form
    form.username.data = user_info['username']
    form.email.data = user_info['email']

    cur.close()
    return render_template("checkout.html", user_id=user_id, cart_item=cart_details,
                           total=round(total, 2), total_items=total_items, user_infos=user_infos, form=form)


@bp.route("/checkout/remove", methods=['GET', 'POST'])
def remove_item():
    # Get the selected image ID from the submitted form
    images_id = request.form.get('image_id')
    user_id = get_current_user_id()

    # Fetch the cart_id of corresponding user
    cur = database.connection.cursor()
    cur.execute("SELECT id FROM carts WHERE user_id = %s", (user_id,))
    user_cart = cur.fetchone()

    # Fetch user_id and image_id
    cur.execute("""
    SELECT ci.cart_id, ci.image_id
    FROM cart_items ci
    JOIN carts c ON ci.cart_id = c.id
    WHERE c.user_id = %s AND ci.image_id = %s
    """, (user_id, images_id))
    result = cur.fetchone()

    # If the user' cart exists
    if result:
        cart_id = result['cart_id']

        # Delete the selected item from the cart
        cur.execute(
            "DELETE FROM cart_items WHERE cart_id = %s AND image_id = %s", (cart_id, images_id))
        database.connection.commit()
        flash("Item removed successfully", "info")

        # Check if there are any remaining items in the cart
        cur.execute(
            "SELECT image_id FROM cart_items WHERE cart_id=%s", (cart_id,))
        remaining_items = cur.fetchall()
        cur.close()

        # If the cart is now empty, show a message and redirect to the cart page
        if not remaining_items:
            flash(
                f'There is nothing in the cart, please choose again. '
                f'<a href="{url_for("main.index")}" class="btn btn-light btn-sm ms-2">Back to Home</a>',
                "warning")
            return redirect(url_for("main.get_cart", user_id=user_id))
        else:
            # Otherwise, reload the cart page to show updated items
            return redirect(url_for("main.get_cart", user_id=user_id))

    # Render the checkout page if the user's cart does not exist or no action was performed
    return render_template("checkout.html", user_id=user_id)


@bp.route("/checkout/clearcart", methods=["GET", "POST"])
def clear_cart():
    # Get the currently user's ID
    user_id = get_current_user_id()
    cur = database.connection.cursor()

    # Proceed if the request method is POST
    if request.method == 'POST':
        # Find the user's cart by user_id
        cur.execute("SELECT id FROM carts WHERE user_id=%s", (user_id,))
        user_cart = cur.fetchone()

        # If the user's cart exists
        if user_cart:
            # Delete all items from the user's cart
            cur.execute("DELETE FROM cart_items WHERE cart_id=%s",
                        (user_cart['id'],))
            database.connection.commit()
            flash("Cart cleared!", "success")
            cur.close()
            return redirect(url_for("main.index"))

    # If the request method is not POST, show a warning message
    flash("Invalid request method", "danger")
    cur.close()
    return redirect(url_for("main.index"))


@bp.route("/checkout/download", methods=['GET', 'POST'])
def get_download():
    # Fetch the current user_id
    user_id = get_current_user_id()

    order_details = []
    # If form submit by POST method
    if request.method == 'POST':
        cur = database.connection.cursor()

        # Fetch the selected cart_id by user_id
        cur.execute("SELECT id FROM carts WHERE user_id = %s", (user_id,))
        user_cart_download = cur.fetchone()

        # Fetch the selected image_id from the carts
        cur.execute(
            "SELECT image_id FROM cart_items WHERE cart_id=%s", (user_cart_download['id'],))
        image_ids = cur.fetchall()

        # If there is no image in cart, give a hint to users
        if not image_ids:
            cur.close()
            flash("Your cart is empty.")
            return redirect(url_for("main.get_cart", user_id=user_id))

        # Fetch info of images and add into order details orderly
        for ci in image_ids:
            cur.execute("SELECT * FROM images WHERE id = %s",
                        (ci['image_id'],))
            Image_info = cur.fetchone()

            if Image_info:
                order_details.append({
                    "image_id": Image_info['id'],
                    "title": Image_info['title'],
                    "price": float(Image_info['price']),
                    "url": Image_info['url']
                })

        cur.close()

        # Render cart_download template, and show the download link with selected images
        return render_template("cart_download.html", user_id=user_id, order_item=order_details)

    # fetch the order details from the session
    order_details = session.get('order_details', [])

    # Render template
    return render_template("cart_download.html", user_id=user_id, order_item=order_details)


@bp.route("/checkout/payment", methods=['GET', 'POST'])
def payment_info():
    cur = database.connection.cursor()
    form = CheckoutForm()
    user_id = get_current_user_id()

    # Fetch user's infos
    cur.execute("SELECT username, email FROM users WHERE id=%s", (user_id,))
    user_info = cur.fetchone()

    # Fetch user's cart
    cur.execute("SELECT id FROM carts WHERE user_id=%s", (user_id,))
    cart_id = cur.fetchone()

    # Fetch images from cart
    cur.execute("SELECT image_id FROM cart_items WHERE cart_id=%s",
                (cart_id['id'],))
    order_items_id = cur.fetchall()

    if not order_items_id:
        cur.close()
        flash("Your cart is empty. Please add items before checkout!", "warning")
        return redirect(url_for("main.get_cart", user_id=user_id))

    # Integrate infos of images
    total_amount = 0
    order_items_info = []
    for item in order_items_id:
        cur.execute("SELECT * FROM images WHERE id=%s", (item['image_id'],))
        row = cur.fetchone()
        if row:
            order_items_info.append(row)

            total_amount += row['price']

    # store details into session, for download page use
    session['order_details'] = order_items_info
    session['total_amount'] = total_amount

    # Auto-fill user's infos
    if request.method == "GET" and user_info:
        form.username.data = user_info["username"]
        form.email.data = user_info["email"]

    # If POST form submit
    if form.validate_on_submit():
        # Retrieve user input values from the Checkout form
        username = form.username.data
        email = form.email.data
        accountname = form.accountname.data
        cardnumber = form.cardnumber.data
        expiry = form.expiry.data
        cvc = form.cvc.data

        payment_status = "paid"
        order_status = "completed"
        method = "credit_card"

        # Add a new order
        cur.execute("""
            INSERT INTO orders (user_id, created_at, status, total_amount)
            VALUES (%s,%s,%s,%s)
        """, (user_id, datetime.now(), order_status, total_amount))

        # Auto generate the ID for orders and payments using auto-increment
        order_id = cur.lastrowid
        payment_id = cur.lastrowid

        # Add images from the cart into the order
        for item in order_items_info:
            cur.execute(
                "SELECT license_id FROM image_license where image_id=%s", (item['id'],))
            licenseid = cur.fetchone()

            license_id = licenseid['license_id']
            cur.execute("""
                INSERT INTO order_items (order_id, image_id, license_id, price, quantity,image_title,image_url) VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (order_id, item['id'], license_id, item['price'], 1, item['title'], item['url']))

        # Add a new payment record into database
        cur.execute("""
            INSERT INTO payments (id,order_id, amount, method, status, paid_at, account_name) VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (payment_id, order_id, total_amount, method, payment_status, datetime.now(), accountname))

        # Clear the images from the cart
        cur.execute("DELETE FROM cart_items where cart_id=%s",
                    (cart_id['id'],))
        database.connection.commit()
        cur.close()

        flash("Payment Succeed！", "success")
        return redirect(url_for("main.get_download", user_id=user_id))

    else:
        # If form validation fails, prompt the user to re-fill the form
        flash("There is something wrong with the information, please check and do it again!", "warning")
        return redirect(url_for("main.get_cart", form=form, user_id=user_id))


@bp.route('/add_to_cart/<int:image_id>', methods=['POST'])
def add_to_cart(image_id):
    user_id = get_current_user_id()
    if not user_id:
        flash('You need to log in to add items to your cart.', 'warning')
        return redirect(url_for('main.login'))

    cursor = database.connection.cursor()
    cursor.execute("SELECT id FROM carts WHERE user_id = %s", (user_id,))
    cart = cursor.fetchone()

    if cart:
        cart_id = cart['id'] if isinstance(cart, dict) else cart[0]
    else:
        cursor.execute(
            "INSERT INTO carts (user_id, created_at) VALUES (%s, NOW())",
            (user_id,)
        )
        database.connection.commit()
        cart_id = cursor.lastrowid

    cursor.execute("""
        SELECT 1 FROM cart_items WHERE cart_id = %s AND image_id = %s
    """, (cart_id, image_id))
    existing_item = cursor.fetchone()

    if existing_item:
        flash("This item is already in your cart.", "info")
        cursor.close()
        return redirect(url_for('main.item_detail', id=image_id))

    try:
        cursor.execute("""
            INSERT INTO cart_items (cart_id, image_id, added_at)
            VALUES (%s, %s, NOW())
        """, (cart_id, image_id))
        database.connection.commit()
        flash('Item added to cart!', 'success')
    except Exception as e:
        database.connection.rollback()
        flash(f'Error adding item: {e}', 'danger')
    finally:
        cursor.close()

    return redirect(url_for('main.item_detail', id=image_id))


@bp.get('/500')
def boom():
    abort(500)
