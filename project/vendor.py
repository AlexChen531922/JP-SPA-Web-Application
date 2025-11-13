import os
import uuid
import datetime
import MySQLdb
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, session, abort
from werkzeug.utils import secure_filename
from project.db import get_current_user_id, get_current_user_role
from . import database
from .forms import VendorUploadFormDB, VendorEditFormDB
import re
from MySQLdb import IntegrityError

bp = Blueprint('vendor', __name__, url_prefix='/vendor')
ALLOWED = {'jpg', 'jpeg', 'png', 'webp', 'gif'}
# UUID = unique random ID → no filename conflict, no guessable URLs.
UUID_RE = re.compile(r"^[0-9a-f]{32}\.[a-z0-9]+$")
UPLOAD_SUBDIR = "img"


def _is_user_upload(url: str) -> bool:
    return bool(url) and url.lstrip("/").startswith(f"{UPLOAD_SUBDIR}/")


def _abs_static_path(relpath: str) -> str:
    safe = (relpath or "").lstrip("/")
    return os.path.join(current_app.static_folder, safe)


def _delete_file_if_unreferenced(url: str) -> bool:
    if not _is_user_upload(url):
        return False

    cursor = database.connection.cursor()
    cursor.execute("SELECT COUNT(*) AS c FROM images WHERE url=%s", (url,))
    still = cursor.fetchone()["c"]
    cursor.close()
    if still > 0:
        return False

    path = _abs_static_path(url)
    uploads_root = os.path.join(current_app.static_folder, UPLOAD_SUBDIR)
    try:
        if os.path.commonpath([os.path.realpath(path), os.path.realpath(uploads_root)]) != os.path.realpath(uploads_root):
            return False
    except Exception:
        return False

    if os.path.exists(path):
        try:
            os.remove(path)
            return True
        except Exception:
            return False
    return False


def _remove_uploaded_file(url: str):
    if not url:
        return
    try:
        folder = current_app.config['UPLOAD_FOLDER']
        path = os.path.join(folder, os.path.basename(url))
        if os.path.commonpath([folder, os.path.abspath(path)]) != os.path.abspath(folder):
            return
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        current_app.logger.warning(f"Failed to remove file {url}: {e}")


def _save_to_uploads(fs) -> str:
    fn = secure_filename(fs.filename or '')
    if '.' not in fn:
        raise ValueError('Invalid filename')
    ext = fn.rsplit('.', 1)[1].lower()
    if ext not in ALLOWED:
        raise ValueError('Unsupported file type')

    new_name = f"{uuid.uuid4().hex}.{ext}"
    folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(folder, exist_ok=True)
    fs.save(os.path.join(folder, new_name))

    return f"img/{new_name}"


def _get_image(image_id: int, owner_id: int):
    cursor = database.connection.cursor()
    cursor.execute("SELECT * FROM images WHERE id=%s", (image_id,))
    row = cursor.fetchone()
    cursor.close()
    if not row:
        abort(404)
    if get_current_user_role() != 'admin' and int(row['vendor_id']) != int(owner_id):
        abort(403)
    return row


@bp.route('/edit/<int:image_id>', methods=['GET', 'POST'])
def edit(image_id):
    uid = get_current_user_id()
    img = _get_image(image_id, uid)

    form = VendorEditFormDB()
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    cursor.execute("SELECT id, name FROM events ORDER BY name")
    events = cursor.fetchall()
    cursor.execute("SELECT id, name FROM categories ORDER BY name")
    categories = cursor.fetchall()
    cursor.execute("SELECT id, type FROM licenses ORDER BY type")
    licenses = cursor.fetchall()

    form.event_id.choices = [(e['id'], e['name']) for e in events]
    form.category_ids.choices = [(c['id'], c['name']) for c in categories]
    form.license_id.choices = [(l['id'], l['type']) for l in licenses]

    cursor.execute(
        "SELECT category_id FROM image_category WHERE image_id=%s", (image_id,))
    existing = cursor.fetchall()
    existing_ids = [row['category_id'] for row in existing]

    cursor.execute(
        "SELECT license_id FROM image_license WHERE image_id=%s LIMIT 1", (image_id,))
    lic_row = cursor.fetchone()
    current_license_id = lic_row['license_id'] if lic_row else None
    cursor.close()

    if request.method == 'GET':
        form.title.data = img['title']
        form.description.data = img.get('description') or ''
        form.event_id.data = img['event_id']
        form.category_ids.data = existing_ids
        form.license_id.data = current_license_id
        form.resolution.data = img['resolution']
        form.format.data = img['format']
        form.price.data = img.get('price')
        return render_template(
            'vendor_edit.html',
            form=form,
            image=img,
            events=events,
            category_list=categories,
            licenses=licenses,
            selected_category_ids=existing_ids,
            current_license_id=current_license_id
        )

    selected_ids_post = [int(x) for x in request.form.getlist('category_ids')]
    if not selected_ids_post:
        flash("Please select at least one category.", "danger")
        form.category_ids.data = selected_ids_post
        return render_template(
            'vendor_edit.html',
            form=form,
            image=img,
            events=events,
            category_list=categories,
            licenses=licenses,
            selected_category_ids=selected_ids_post,
            current_license_id=request.form.get('license_id', type=int)
        )

    if form.validate_on_submit():
        new_url = img['url']
        if form.image.data:
            new_url = _save_to_uploads(form.image.data)
            _remove_uploaded_file(img['url'])

        cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute(
            """
            UPDATE images
            SET title=%s,
                description=%s,
                resolution=%s,
                format=%s,
                price=%s,
                event_id=%s,
                url=%s
            WHERE id=%s
            """,
            (
                (form.title.data or '').strip(),
                (form.description.data or '') or None,
                form.resolution.data,
                form.format.data,
                float(form.price.data) if form.price.data is not None else 0.0,
                form.event_id.data,
                new_url,
                image_id
            )
        )

        cursor.execute(
            "DELETE FROM image_category WHERE image_id=%s", (image_id,))
        cursor.executemany(
            "INSERT INTO image_category (image_id, category_id) VALUES (%s, %s)",
            [(image_id, cid) for cid in selected_ids_post]
        )

        cursor.execute(
            "DELETE FROM image_license WHERE image_id=%s", (image_id,))
        if form.license_id.data:
            cursor.execute(
                "INSERT INTO image_license (image_id, license_id) VALUES (%s, %s)",
                (image_id, form.license_id.data)
            )

        database.connection.commit()
        cursor.close()

        flash('Image updated!', 'success')
        if get_current_user_role() == 'admin':
            return redirect(url_for('main.vendor_management', tab='images'))
        else:
            return redirect(url_for('vendor.management'))

    return render_template(
        'vendor_edit.html',
        form=form,
        image=img,
        events=events,
        category_list=categories,
        licenses=licenses,
        selected_category_ids=selected_ids_post or existing_ids,
        current_license_id=request.form.get('license_id', type=int) if request.form.get(
            'license_id') else current_license_id
    )


@bp.post('/delete/<int:image_id>')
def delete(image_id):
    uid = get_current_user_id()
    img = _get_image(image_id, uid)

    cursor = database.connection.cursor()
    cursor.execute("DELETE FROM images WHERE id=%s", (image_id,))
    database.connection.commit()
    cursor.close()

    _remove_uploaded_file(img['url'])
    flash('Image deleted.', 'success')
    return redirect(url_for('vendor.management'))


@bp.route('/management', methods=['GET', 'POST'])
def management():
    form = VendorUploadFormDB()
    uid = get_current_user_id()
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)

    cursor.execute("SELECT id, name FROM events ORDER BY name")
    events = cursor.fetchall()
    cursor.execute("SELECT id, name FROM categories ORDER BY name")
    categories = cursor.fetchall()
    cursor.execute("SELECT id, type FROM licenses ORDER BY type")
    licenses = cursor.fetchall()

    form.event_id.choices = [(e['id'], e['name']) for e in events]
    form.category_ids.choices = [(c['id'], c['name']) for c in categories]
    form.license_id.choices = [(l['id'], l['type']) for l in licenses]

    action = request.form.get('action', '')

    if request.method == 'POST' and (action in ('', None, 'add_image')):
        selected_categories = [int(x)
                               for x in request.form.getlist('category_ids')]
        missing_image = (not form.image.data) or (
            getattr(form.image.data, "filename", "") == "")

        if not selected_categories:
            flash("Please select at least one category.", "danger")
        if missing_image:
            flash("Please choose an image file.", "danger")

        if form.validate_on_submit() and selected_categories:
            url = _save_to_uploads(form.image.data)
            uploaded_at = datetime.date.today()
            price = float(
                form.price.data) if form.price.data is not None else 0.0

            cursor.execute(
                """
                INSERT INTO images
                (title, description, resolution, format, uploaded_at, price, event_id, vendor_id, url)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    (form.title.data or '').strip(),
                    (form.description.data or '') or None,
                    form.resolution.data,
                    form.format.data,
                    uploaded_at,
                    price,
                    form.event_id.data,
                    uid,
                    url,
                )
            )
            image_id = cursor.lastrowid

            cursor.executemany(
                "INSERT INTO image_category (image_id, category_id) VALUES (%s, %s)",
                [(image_id, cid) for cid in selected_categories]
            )

            license_id = request.form.get('license_id')
            if license_id:
                cursor.execute(
                    "INSERT INTO image_license (image_id, license_id) VALUES (%s, %s)",
                    (image_id, int(license_id))
                )

            database.connection.commit()
            flash('Image uploaded!', 'success')
            return redirect(url_for('vendor.management'))

    cursor.execute(
        """
        SELECT
            i.id, i.title, i.description, i.resolution, i.format, i.uploaded_at, i.price, i.url,
            i.event_id, e.name AS event_name,
            GROUP_CONCAT(DISTINCT c.name ORDER BY c.name SEPARATOR '||') AS category_names_csv,
            GROUP_CONCAT(DISTINCT c.id   ORDER BY c.id   SEPARATOR ',')  AS category_ids_csv,
            GROUP_CONCAT(DISTINCT l.type ORDER BY l.type SEPARATOR '||') AS license_types_csv,
            GROUP_CONCAT(DISTINCT l.id   ORDER BY l.id   SEPARATOR ',')  AS license_ids_csv
        FROM images i
        LEFT JOIN events e           ON e.id = i.event_id
        LEFT JOIN image_category ic  ON ic.image_id = i.id
        LEFT JOIN categories c       ON c.id = ic.category_id
        LEFT JOIN image_license il   ON il.image_id = i.id
        LEFT JOIN licenses l         ON l.id = il.license_id
        WHERE i.vendor_id = %s
            AND i.deleted_at IS NULL
        GROUP BY i.id, i.title, i.description, i.resolution, i.format, i.uploaded_at, i.price, i.url, i.event_id, e.name
        ORDER BY i.uploaded_at DESC, i.id DESC
        """,
        (uid,)
    )
    images = cursor.fetchall()
    cursor.close()

    for r in images:
        r['category_names'] = (r.get('category_names_csv') or '').split(
            '||') if r.get('category_names_csv') else []
        r['category_ids'] = [int(x) for x in (r.get('category_ids_csv') or '').split(
            ',')] if r.get('category_ids_csv') else []
        r['license_types'] = (r.get('license_types_csv') or '').split(
            '||') if r.get('license_types_csv') else []
        r['license_id'] = int((r.get('license_ids_csv') or '').split(',')[
                              0]) if r.get('license_ids_csv') else None

    return render_template(
        'vendor_management.html',
        form=form,
        images=images,
        events=events,
        category_list=categories,
        licenses=licenses
    )


@bp.get('/gallery')
def my_gallery():
    uid = get_current_user_id()
    if not uid:
        abort(403)
    return redirect(url_for('vendor.gallery', vendor_id=int(uid)))


@bp.get('/gallery/<int:vendor_id>')
def gallery(vendor_id):
    cursor = database.connection.cursor(
        MySQLdb.cursors.DictCursor)  # ✅ DictCursor

    cursor.execute(
        "SELECT id, firstname, surname FROM users WHERE id=%s AND role='vendor'", (vendor_id,))
    vendor_data = cursor.fetchone()
    if vendor_data:
        vendor = {"id": vendor_id,
                  "name": f"{vendor_data['firstname']} {vendor_data['surname']}"}
    else:
        vendor = {"id": vendor_id, "name": f"Vendor #{vendor_id}"}

    cursor.execute("""
        SELECT
            i.id, i.title, i.description, i.resolution, i.format, i.uploaded_at, i.price, i.url,
            i.event_id, e.name AS event_name,
            GROUP_CONCAT(DISTINCT c.name ORDER BY c.name SEPARATOR '||') AS category_names_csv,
            GROUP_CONCAT(DISTINCT c.id   ORDER BY c.id   SEPARATOR ',')  AS category_ids_csv,
            GROUP_CONCAT(DISTINCT l.type ORDER BY l.type SEPARATOR '||') AS license_types_csv,
            GROUP_CONCAT(DISTINCT l.id   ORDER BY l.id   SEPARATOR ',')  AS license_ids_csv
        FROM images i
        LEFT JOIN events e           ON e.id = i.event_id
        LEFT JOIN image_category ic  ON ic.image_id = i.id
        LEFT JOIN categories c       ON c.id = ic.category_id
        LEFT JOIN image_license il   ON il.image_id = i.id
        LEFT JOIN licenses l         ON l.id = il.license_id
        WHERE i.vendor_id = %s
            AND i.deleted_at IS NULL
        GROUP BY i.id, i.title, i.description, i.resolution, i.format, i.uploaded_at, i.price, i.url, i.event_id, e.name
        ORDER BY i.uploaded_at DESC, i.id DESC
    """, (vendor_id,))

    images = cursor.fetchall()
    cursor.close()

    for row in images:
        row['category_names'] = (row.get('category_names_csv') or '').split(
            '||') if row.get('category_names_csv') else []
        row['category_ids'] = [int(x) for x in (row.get('category_ids_csv') or '').split(
            ',')] if row.get('category_ids_csv') else []
        row['license_types'] = (row.get('license_types_csv') or '').split(
            '||') if row.get('license_types_csv') else []
        row['license_ids'] = [int(x) for x in (row.get('license_ids_csv') or '').split(
            ',')] if row.get('license_ids_csv') else []

    total = len(images)

    return render_template(
        'vendor_gallery.html',
        vendor=vendor,
        images=images,
        vendor_id=vendor_id,
        total=total,
    )
