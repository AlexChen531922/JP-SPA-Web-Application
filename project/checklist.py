"""JP AROMATIC shop checklist module.

Blueprint registration: app.register_blueprint(checklist_bp)
Global Flask-WTF CSRFProtect is inherited from the host application.
All database timestamps use the host's MySQL session timezone (+08:00).
"""
from collections import defaultdict
from functools import wraps
from datetime import date, datetime, timedelta
from io import BytesIO
import calendar
import json
import unicodedata
from zoneinfo import ZoneInfo

from flask import (Blueprint, abort, jsonify, redirect, render_template,
                   request, send_file, session, url_for, flash)
from project.extensions import database
from project.decorators import staff_required
import MySQLdb.cursors
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# Staff operations and admin-only functions use different route namespaces.
checklist_bp = Blueprint('checklist', __name__, url_prefix='/staff/checklist')
checklist_admin_bp = Blueprint(
    'checklist_admin', __name__, url_prefix='/admin/checklist')


def checklist_admin_required(fn):
    """Enforce a 403 for staff attempting a management URL, not a redirect to legacy admin dashboard."""
    @wraps(fn)
    def inner(*args, **kwargs):
        account = session.get('user') or {}
        if not session.get('logged_in') or account.get('role') != 'admin':
            abort(403, description='此功能僅供管理員使用')
        return fn(*args, **kwargs)
    return inner


CATEGORIES = ('opening', 'operating', 'closing', 'periodic')
ROLES = ('duty', 'therapist', 'all')
PERIODS = ('daily', 'weekday', 'monthday', 'once')
CATEGORY_NAMES = {'opening': '晨間開店', 'operating': '營業中',
                  'closing': '晚班閉店', 'periodic': '特定週期'}
ROLE_NAMES = {'duty': '值日生', 'therapist': '芳療師／助理', 'all': '全員'}
STATE_NAMES = {'pending': '未完成', 'done': '已完成', 'na': '不適用', 'void': '已取消'}


def taiwan_today():
    return datetime.now(ZoneInfo('Asia/Taipei')).date()


def parse_day(text):
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        abort(400, description='日期格式必須為 YYYY-MM-DD')


def current_actor(cursor, admin=False):
    user = session.get('user') or {}
    if not session.get('logged_in') or not user.get('id'):
        abort(403)
    cursor.execute(
        'SELECT id, role, firstname, surname FROM users WHERE id=%s', (user['id'],))
    actor = cursor.fetchone()
    if not actor or actor['role'] not in ('staff', 'admin') or (admin and actor['role'] != 'admin'):
        abort(403)
    return actor


def may_edit_date(actor, work_date):
    # Staff can only change their own calendar day; admins may correct history.
    if actor['role'] != 'admin' and work_date != taiwan_today():
        abort(403, description='非管理員僅能修改今日檢核')


def normalized_signature_name(value):
    """Compare Chinese/English names allowing whitespace and width differences."""
    return ''.join(unicodedata.normalize('NFKC', value).split()).casefold()


def signature_name_matches(actor, entered):
    """Verify the typed name against the authenticated staff account."""
    firstname = (actor.get('firstname') or '').strip()
    surname = (actor.get('surname') or '').strip()
    if not firstname or not surname or not entered or len(entered) > 120:
        return False
    normalized = normalized_signature_name(entered)
    return normalized in {
        normalized_signature_name(firstname + surname),
        normalized_signature_name(surname + firstname),
    }


def staff_choices(cursor):
    cursor.execute(
        "SELECT id, firstname, surname, username FROM users WHERE role='staff' ORDER BY firstname, surname")
    return cursor.fetchall()


def display_names(cursor):
    cursor.execute(
        "SELECT id, firstname, surname, username FROM users WHERE role IN ('staff','admin')")
    return {r['id']: ((r['firstname'] or '')+' '+(r['surname'] or '')).strip() or r['username']
            for r in cursor.fetchall()}


def affected_signoff_roles(snapshot_role):
    """An 'all' task belongs to both signers; a specific task belongs to one."""
    if snapshot_role == 'all':
        return ('duty', 'therapist')
    if snapshot_role in ('duty', 'therapist'):
        return (snapshot_role,)
    return ()


def pending_for_signer(items, signer_role):
    """Only outstanding work assigned to this signer can block their signoff."""
    return sum(item['state'] == 'pending' and
               signer_role in affected_signoff_roles(item['snapshot_role'])
               for item in items)


def can_change_task(actor, record, task):
    """Staff may only mark their assigned role's tasks; all-role tasks allow any staff."""
    if actor['role'] == 'admin':
        return True  # An admin override is captured in the audit history.
    if task['snapshot_role'] == 'all':
        return actor['role'] == 'staff'
    if task['snapshot_role'] == 'duty':
        return actor['id'] == record['duty_user_id']
    if task['snapshot_role'] == 'therapist':
        return actor['id'] == record['therapist_user_id']
    return False


def is_applicable(task, day):
    if task.get('effective_start') and day < task['effective_start']:
        return False
    if task.get('effective_end') and day > task['effective_end']:
        return False
    kind = task['period_type']
    if kind == 'daily':
        return True
    if kind == 'weekday':
        return task['period_val'] == day.isoweekday()
    if kind == 'once':
        return task['one_time_date'] == day
    if kind == 'monthday':
        target = task['period_val']
        if task['missing_day_policy'] == 'last_day':
            target = min(target, calendar.monthrange(day.year, day.month)[1])
        return target == day.day
    return False


def get_active_tasks(cursor):
    cursor.execute(
        "SELECT * FROM checklist_tasks WHERE is_active=1 ORDER BY sort_order, id")
    return cursor.fetchall()


def get_record(cursor, day, lock=False):
    sql = 'SELECT * FROM checklist_daily_records WHERE log_date=%s'
    if lock:
        sql += ' FOR UPDATE'
    cursor.execute(sql, (day,))
    return cursor.fetchone()


def get_items(cursor, record_id):
    cursor.execute('''SELECT i.*, u.firstname AS done_firstname, u.surname AS done_surname
                      FROM checklist_daily_items i
                      LEFT JOIN users u ON i.done_by_user_id = u.id
                      WHERE i.record_id=%s ORDER BY i.sort_order, i.id''', (record_id,))
    return cursor.fetchall()


def audit(cursor, actor_id, action, record_id=None, item_id=None, task_id=None, old=None, new=None):
    cursor.execute('''INSERT INTO checklist_audit_logs
      (actor_user_id, action, record_id, item_id, task_id, old_value, new_value)
      VALUES (%s,%s,%s,%s,%s,%s,%s)''', (
        actor_id, action, record_id, item_id, task_id,
        json.dumps(old, ensure_ascii=False,
                   default=str) if old is not None else None,
        json.dumps(new, ensure_ascii=False,
                   default=str) if new is not None else None
    ))


def bump_revision(cursor, record, actor_id, why, preserve_roles=()):
    """Advance the audit revision, retaining only unaffected role signatures.

    Existing signoffs are immutable; retained signatures are copied with their
    original signer and signed_at into the new revision. Each carry-over is
    separately audited so no new employee signature is fabricated.
    """
    prior_revision = record['revision']
    new_revision = prior_revision + 1
    retained = []
    if preserve_roles:
        cursor.execute('''SELECT signer_role, signed_by_user_id, signed_at
                          FROM checklist_signoffs WHERE record_id=%s AND revision=%s''',
                       (record['id'], prior_revision))
        retained = [r for r in cursor.fetchall() if r['signer_role'] in preserve_roles]
    cursor.execute('''UPDATE checklist_daily_records SET revision=revision+1, locked_at=NULL,
                      status='open' WHERE id=%s''', (record['id'],))
    for signature in retained:
        cursor.execute('''INSERT INTO checklist_signoffs
            (record_id, revision, signer_role, signed_by_user_id, signed_at)
            VALUES (%s,%s,%s,%s,%s)''',
            (record['id'], new_revision, signature['signer_role'],
             signature['signed_by_user_id'], signature['signed_at']))
        audit(cursor, actor_id, 'carry_forward_signoff', record_id=record['id'],
              new={'role': signature['signer_role'], 'from_revision': prior_revision,
                   'to_revision': new_revision, 'signed_by_user_id': signature['signed_by_user_id']})
    audit(cursor, actor_id, 'invalidate_signoffs', record_id=record['id'],
          old={'revision': prior_revision},
          new={'reason': why, 'revision': new_revision,
               'retained_roles': [r['signer_role'] for r in retained]})


def json_error(message, code=400):
    return jsonify(ok=False, error=message), code


def json_payload():
    return request.get_json(silent=True) or {}


def transact(fn):
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        result = fn(cursor)
        database.connection.commit()
        return result
    except Exception:
        database.connection.rollback()
        raise
    finally:
        cursor.close()


def date_span(view, day):
    if view == 'week':
        start = day - timedelta(days=day.weekday())
        return [start + timedelta(days=i) for i in range(7)]
    if view == 'month':
        return [day.replace(day=i) for i in range(1, calendar.monthrange(day.year, day.month)[1]+1)]
    return [day]


def period_grid(cursor, days):
    """Historical records are authoritative. Nonexistent past days are *unfiled*, not 'failed'."""
    active = get_active_tasks(cursor)
    cursor.execute('''SELECT * FROM checklist_daily_records WHERE log_date BETWEEN %s AND %s ORDER BY log_date''',
                   (days[0], days[-1]))
    records = {r['log_date']: r for r in cursor.fetchall()}
    record_ids = [r['id'] for r in records.values()]
    items_by_day = defaultdict(list)
    if record_ids:
        placeholders = ','.join(['%s']*len(record_ids))
        cursor.execute(f'''SELECT i.*, r.log_date FROM checklist_daily_items i
                           JOIN checklist_daily_records r ON i.record_id=r.id
                           WHERE i.record_id IN ({placeholders}) ORDER BY i.sort_order, i.id''', tuple(record_ids))
        for item in cursor.fetchall():
            items_by_day[item['log_date']].append(item)
    rows = {}
    for d in days:
        if d in records:
            for item in items_by_day[d]:
                key = 't' + \
                    str(item['task_id']) if item['task_id'] else 'a' + \
                    str(item['id'])
                rows[key] = {'key': key, 'title': item['snapshot_title'], 'sort_order': item['sort_order'],
                             'category': item['snapshot_category']}
        else:
            for t in active:
                if is_applicable(t, d):
                    key = 't' + str(t['id'])
                    rows.setdefault(key, {
                                    'key': key, 'title': t['title'], 'sort_order': t['sort_order'], 'category': t['category']})
    rows = sorted(rows.values(), key=lambda r: (r['sort_order'], r['key']))
    cells = {}
    summary = {}
    for d in days:
        if d not in records:
            summary[d] = {'status': 'future' if d > taiwan_today(
            ) else 'unfiled', 'total': 0, 'done': 0, 'na': 0, 'pending': 0}
        else:
            its = [i for i in items_by_day[d] if i['state'] != 'void']
            summary[d] = {
                'status': records[d]['status'], 'total': len(its),
                'done': sum(i['state'] == 'done' for i in its),
                'na': sum(i['state'] == 'na' for i in its),
                'pending': sum(i['state'] == 'pending' for i in its)
            }
        for row in rows:
            cells[(row['key'], d.isoformat())] = 'not_applicable'
        if d in records:
            for item in items_by_day[d]:
                key = 't' + \
                    str(item['task_id']) if item['task_id'] else 'a' + \
                    str(item['id'])
                cells[(key, d.isoformat())] = item['state']
        else:
            for t in active:
                if is_applicable(t, d):
                    cells[('t'+str(t['id']), d.isoformat())
                          ] = 'future' if d > taiwan_today() else 'unfiled'
    return rows, cells, summary, records, items_by_day


@checklist_bp.route('/')
@staff_required
def index():
    view = request.args.get('view', 'day')
    if view not in ('day', 'week', 'month'):
        abort(400)
    day = parse_day(request.args.get('date', taiwan_today().isoformat()))
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        actor = current_actor(cursor)
        if view == 'day':
            record = get_record(cursor, day)
            items = get_items(cursor, record['id']) if record else []
            preview = [t for t in get_active_tasks(
                cursor) if is_applicable(t, day)] if not record else []
            approvals = {}
            if record:
                cursor.execute('''SELECT signer_role,signed_by_user_id,signed_at FROM checklist_signoffs
                                  WHERE record_id=%s AND revision=%s''', (record['id'], record['revision']))
                approvals = {r['signer_role']: r for r in cursor.fetchall()}
            staff = staff_choices(cursor)
            stats = {'done': sum(i['state'] == 'done' for i in items),
                     'na': sum(i['state'] == 'na' for i in items),
                     'pending': sum(i['state'] == 'pending' for i in items),
                     'total': sum(i['state'] != 'void' for i in items)}
            pending_by_role = {role: pending_for_signer(items, role)
                               for role in ('duty', 'therapist')}
            return render_template('checklist/index.html', view=view, day=day, actor=actor,
                                   record=record, items=items, preview=preview, staff=staff,
                                   approvals=approvals, stats=stats, pending_by_role=pending_by_role,
                                   today=taiwan_today(),
                                   category_names=CATEGORY_NAMES, role_names=ROLE_NAMES, state_names=STATE_NAMES, can_change_task=can_change_task)
        days = date_span(view, day)
        rows, cells, summary, records, _ = period_grid(cursor, days)
        return render_template('checklist/index.html', view=view, day=day, actor=actor,
                               days=days, rows=rows, cells=cells, summary=summary, records=records, today=taiwan_today(),
                               category_names=CATEGORY_NAMES, role_names=ROLE_NAMES, state_names=STATE_NAMES, can_change_task=can_change_task)
    finally:
        cursor.close()


@checklist_bp.post('/start')
@staff_required
def start_day():
    day = parse_day(request.form.get('date'))

    def op(cursor):
        actor = current_actor(cursor)
        may_edit_date(actor, day)
        record = get_record(cursor, day, lock=True)
        if record:
            return redirect(url_for('checklist.index', date=day.isoformat()))
        # Concurrent initialization: UNIQUE(log_date) guarantees only one winner;
        # repeat a second time if a conflict is shown to the initiating user.
        cursor.execute('INSERT INTO checklist_daily_records (log_date,created_by_user_id) VALUES (%s,%s)',
                       (day, actor['id']))
        record_id = cursor.lastrowid
        tasks = [t for t in get_active_tasks(cursor) if is_applicable(t, day)]
        for task in tasks:
            cursor.execute('''INSERT INTO checklist_daily_items
                (record_id, task_id, snapshot_title, snapshot_description, snapshot_category, snapshot_role, sort_order)
                VALUES (%s,%s,%s,%s,%s,%s,%s)''',
                           (record_id, task['id'], task['title'], task['description'], task['category'], task['role_type'], task['sort_order']))
        audit(cursor, actor['id'], 'start_day', record_id=record_id, new={
              'date': day.isoformat(), 'task_count': len(tasks)})
        return redirect(url_for('checklist.index', date=day.isoformat()))
    return transact(op)


@checklist_admin_bp.post('/month/create')
@checklist_admin_required
def create_month():
    """Create every day in a month without changing any existing records."""
    text = str(request.form.get('month') or '').strip()
    if len(text) != 7 or text[4] != '-' or not text[:4].isdigit() or not text[5:].isdigit():
        abort(400, description='月份格式必須是 YYYY-MM')
    try:
        month_start = date.fromisoformat(text + '-01')
    except ValueError:
        abort(400, description='無效的月份')
    days = date_span('month', month_start)

    def op(cursor):
        actor = current_actor(cursor, admin=True)
        active_tasks = get_active_tasks(cursor)
        created = 0
        skipped = 0
        for work_day in days:
            # The UNIQUE(log_date) index guarantees no duplicates. Handle only
            # duplicate key 1062; other SQL errors must roll back the month.
            try:
                cursor.execute('''INSERT INTO checklist_daily_records
                    (log_date, created_by_user_id) VALUES (%s, %s)''',
                    (work_day, actor['id']))
            except MySQLdb.IntegrityError as exc:
                if exc.args and exc.args[0] == 1062:
                    skipped += 1
                    continue
                raise
            record_id = cursor.lastrowid
            applicable = [t for t in active_tasks if is_applicable(t, work_day)]
            for task in applicable:
                cursor.execute('''INSERT INTO checklist_daily_items
                    (record_id, task_id, snapshot_title, snapshot_description,
                     snapshot_category, snapshot_role, sort_order)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                    (record_id, task['id'], task['title'], task['description'],
                     task['category'], task['role_type'], task['sort_order']))
            audit(cursor, actor['id'], 'bulk_create_day', record_id=record_id,
                  new={'month': text, 'date': work_day.isoformat(), 'task_count': len(applicable)})
            created += 1
        flash(f'{text} 建立完成：新增 {created} 日，略過既有 {skipped} 日；既有檢核紀錄不受影響。', 'success')
        return redirect(url_for('checklist.index', view='month', date=month_start.isoformat()))

    return transact(op)


@checklist_bp.post('/item/<int:item_id>/state')
@staff_required
def set_item_state(item_id):
    payload = json_payload()
    state = payload.get('state')
    note = str(payload.get('note') or '').strip()
    if state not in ('pending', 'done', 'na'):
        return json_error('無效的檢核狀態')
    if state == 'na' and not note:
        return json_error('不適用項目必須填寫原因')
    if len(note) > 2000:
        return json_error('備註不得超過 2000 字')

    def op(cursor):
        actor = current_actor(cursor)
        cursor.execute(
            'SELECT record_id FROM checklist_daily_items WHERE id=%s', (item_id,))
        target = cursor.fetchone()
        if not target:
            abort(404)
        cursor.execute(
            'SELECT * FROM checklist_daily_records WHERE id=%s FOR UPDATE', (target['record_id'],))
        record = cursor.fetchone()
        may_edit_date(actor, record['log_date'])
        if record['status'] == 'locked':
            return json_error('本日已完成雙人簽核，請管理員先重新開啟', 409)
        cursor.execute(
            'SELECT * FROM checklist_daily_items WHERE id=%s FOR UPDATE', (item_id,))
        item = cursor.fetchone()
        if not can_change_task(actor, record, item):
            abort(403, description='只能更新自己當日負責的工作')
        if item['state'] == 'void':
            return json_error('已取消項目不可更改', 409)
        # Employees cannot modify work already confirmed by the relevant signer.
        # Admins may correct it; the corresponding signature is then invalidated.
        affected_roles = affected_signoff_roles(item['snapshot_role'])
        if actor['role'] != 'admin':
            cursor.execute('''SELECT signer_role FROM checklist_signoffs
                WHERE record_id=%s AND revision=%s''', (record['id'], record['revision']))
            signed_roles = {r['signer_role'] for r in cursor.fetchall()}
            if signed_roles.intersection(affected_roles):
                return json_error('此工作所屬角色已簽核，需由管理員修正後重新簽核', 409)
        if item['state'] == state and (item['note'] or '') == note:
            return jsonify(ok=True, unchanged=True)
        cursor.execute('''UPDATE checklist_daily_items SET state=%s,note=%s,
                   done_by_user_id=%s,done_at=IF(%s='done',NOW(),NULL),
                   updated_by_user_id=%s,updated_at=NOW() WHERE id=%s''',
                       (state, note or None, actor['id'] if state == 'done' else None, state, actor['id'], item_id))
        audit(cursor, actor['id'], 'set_state', record_id=record['id'], item_id=item_id,
              old={'state': item['state'], 'note': item['note']}, new={'state': state, 'note': note})
        preserve_roles = tuple(r for r in ('duty', 'therapist') if r not in affected_roles)
        bump_revision(cursor, record, actor['id'], 'item_change', preserve_roles=preserve_roles)
        return jsonify(ok=True)
    return transact(op)


@checklist_admin_bp.post('/record')
@checklist_admin_required
def update_record():
    day = parse_day(request.form.get('date'))

    def op(cursor):
        actor = current_actor(cursor, admin=True)
        record = get_record(cursor, day, lock=True)
        if not record:
            abort(404)
        if record['status'] == 'locked':
            flash('請先重新開啟已簽核的紀錄', 'warning')
            return redirect(url_for('checklist.index', date=day.isoformat()))
        ids = []
        for field in ('duty_user_id', 'therapist_user_id'):
            value = request.form.get(field) or None
            try:
                ids.append(int(value) if value else None)
            except ValueError:
                abort(400)
        allowed = {r['id'] for r in staff_choices(cursor)}
        if any(i is not None and i not in allowed for i in ids):
            abort(400, description='負責人不是有效的員工帳號')
        notes = str(request.form.get('handover_notes') or '').strip()
        if len(notes) > 5000:
            abort(400)
        old = {'duty': record['duty_user_id'],
               'therapist': record['therapist_user_id'], 'notes': record['handover_notes'] or ''}
        new = {'duty': ids[0], 'therapist': ids[1], 'notes': notes}
        if old != new:
            cursor.execute('''UPDATE checklist_daily_records SET duty_user_id=%s,
                              therapist_user_id=%s,handover_notes=%s WHERE id=%s''',
                           (ids[0], ids[1], notes or None, record['id']))
            audit(cursor, actor['id'], 'update_record',
                  record_id=record['id'], old=old, new=new)
            # Assigning or replacing the *other* employee should not revoke an
            # unrelated role's existing confirmation. A handover-note change is
            # shared information and still invalidates both role confirmations.
            preserve_roles = tuple(r for r in ('duty', 'therapist')
                                   if old['notes'] == new['notes'] and old[r] == new[r])
            bump_revision(cursor, record, actor['id'], 'record_change', preserve_roles=preserve_roles)
        flash('負責人與交接資料已儲存', 'success')
        return redirect(url_for('checklist.index', date=day.isoformat()))
    return transact(op)


@checklist_bp.post('/sign/<role>')
@staff_required
def sign_day(role):
    if role not in ('duty', 'therapist'):
        abort(404)
    day = parse_day(request.form.get('date'))
    if day > taiwan_today():
        abort(400, description='不可提前簽核未來日期')

    def op(cursor):
        actor = current_actor(cursor)
        # Assigned employees may complete a historical record reopened by an admin.
        record = get_record(cursor, day, lock=True)
        if not record:
            abort(404)
        if record['status'] == 'locked':
            flash('本日已簽核完成', 'info')
            return redirect(url_for('checklist.index', date=day.isoformat()))
        assigned = record['duty_user_id'] if role == 'duty' else record['therapist_user_id']
        if actor['id'] != assigned:
            abort(403, description='只有被指派的本人可以完成其簽核')
        entered_name = str(request.form.get('sign_name') or '').strip()
        if not signature_name_matches(actor, entered_name):
            flash('請輸入與目前登入帳號相同的姓名，才可以完成本人簽核', 'warning')
            return redirect(url_for('checklist.index', date=day.isoformat()))
        cursor.execute('''SELECT COUNT(*) AS pending_count FROM checklist_daily_items
                          WHERE record_id=%s AND state='pending'
                            AND snapshot_role IN (%s, 'all')''', (record['id'], role))
        if cursor.fetchone()['pending_count']:
            flash('請先處理自己負責及「全員」的待完成項目（可標記不適用並填原因）', 'warning')
            return redirect(url_for('checklist.index', date=day.isoformat()))
        cursor.execute('''SELECT id FROM checklist_signoffs WHERE record_id=%s AND revision=%s AND signer_role=%s''',
                       (record['id'], record['revision'], role))
        if not cursor.fetchone():
            cursor.execute('''INSERT INTO checklist_signoffs
                         (record_id,revision,signer_role,signed_by_user_id) VALUES (%s,%s,%s,%s)''',
                           (record['id'], record['revision'], role, actor['id']))
            audit(cursor, actor['id'], 'signoff', record_id=record['id'], new={
                  'role': role, 'revision': record['revision'], 'confirmed_name': entered_name})
        cursor.execute('''SELECT COUNT(*) AS n FROM checklist_signoffs WHERE record_id=%s AND revision=%s''',
                       (record['id'], record['revision']))
        if cursor.fetchone()['n'] == 2:
            cursor.execute(
                "UPDATE checklist_daily_records SET status='locked',locked_at=NOW() WHERE id=%s", (record['id'],))
            audit(cursor, actor['id'], 'lock_record', record_id=record['id'], new={
                  'revision': record['revision']})
        flash('簽核完成', 'success')
        return redirect(url_for('checklist.index', date=day.isoformat()))
    return transact(op)


@checklist_admin_bp.post('/reopen')
@checklist_admin_required
def reopen_day():
    day = parse_day(request.form.get('date'))

    def op(cursor):
        actor = current_actor(cursor, admin=True)
        record = get_record(cursor, day, lock=True)
        if not record:
            abort(404)
        if record['status'] == 'locked':
            bump_revision(cursor, record, actor['id'], 'admin_reopen')
            audit(cursor, actor['id'], 'reopen_record', record_id=record['id'])
        flash('本日已重新開啟，原簽核仍留在歷史紀錄中', 'success')
        return redirect(url_for('checklist.index', date=day.isoformat()))
    return transact(op)


@checklist_admin_bp.post('/item/add')
@checklist_admin_required
def add_day_item():
    day = parse_day(request.form.get('date'))
    title = str(request.form.get('title') or '').strip()
    description = str(request.form.get('description') or '').strip()
    category = request.form.get('category', 'periodic')
    role = request.form.get('role_type', 'all')
    if not title or len(title) > 255 or len(description) > 5000 or category not in CATEGORIES or role not in ROLES:
        abort(400)

    def op(cursor):
        actor = current_actor(cursor, admin=True)
        record = get_record(cursor, day, lock=True)
        if not record:
            abort(404)
        if record['status'] == 'locked':
            abort(409)
        cursor.execute('''INSERT INTO checklist_daily_items
                 (record_id,snapshot_title,snapshot_description,snapshot_category,snapshot_role,sort_order)
                 VALUES (%s,%s,%s,%s,%s,9999)''', (record['id'], title, description, category, role))
        item_id = cursor.lastrowid
        audit(cursor, actor['id'], 'add_oneoff',
              record_id=record['id'], item_id=item_id, new={'title': title})
        preserve_roles = tuple(r for r in ('duty', 'therapist')
                               if r not in affected_signoff_roles(role))
        bump_revision(cursor, record, actor['id'], 'add_oneoff', preserve_roles=preserve_roles)
        flash('已加入當日臨時工作', 'success')
        return redirect(url_for('checklist.index', date=day.isoformat()))
    return transact(op)


@checklist_admin_bp.post('/item/<int:item_id>/void')
@checklist_admin_required
def void_day_item(item_id):
    def op(cursor):
        actor = current_actor(cursor, admin=True)
        cursor.execute(
            'SELECT record_id FROM checklist_daily_items WHERE id=%s', (item_id,))
        target = cursor.fetchone()
        if not target:
            abort(404)
        cursor.execute(
            'SELECT * FROM checklist_daily_records WHERE id=%s FOR UPDATE', (target['record_id'],))
        record = cursor.fetchone()
        if record['status'] == 'locked':
            abort(409)
        cursor.execute(
            'SELECT state,snapshot_role FROM checklist_daily_items WHERE id=%s FOR UPDATE', (item_id,))
        item = cursor.fetchone()
        state = item['state']
        if state != 'void':
            cursor.execute(
                "UPDATE checklist_daily_items SET state='void',updated_by_user_id=%s,updated_at=NOW() WHERE id=%s", (actor['id'], item_id))
            audit(cursor, actor['id'], 'void_item', record_id=record['id'],
                  item_id=item_id, old={'state': state})
            preserve_roles = tuple(r for r in ('duty', 'therapist')
                                   if r not in affected_signoff_roles(item['snapshot_role']))
            bump_revision(cursor, record, actor['id'], 'void_item', preserve_roles=preserve_roles)
        flash('項目已取消，歷史紀錄仍保留', 'success')
        return redirect(url_for('checklist.index', date=record['log_date'].isoformat()))
    return transact(op)


def validate_template(payload):
    title = str(payload.get('title') or '').strip()
    description = str(payload.get('description') or '').strip()
    category, role, period = payload.get('category'), payload.get(
        'role_type'), payload.get('period_type')
    if not title or len(title) > 255 or len(description) > 5000 or category not in CATEGORIES or role not in ROLES or period not in PERIODS:
        abort(400, description='工作名稱或分類不合法')
    try:
        val = int(payload['period_val']) if payload.get('period_val') else None
        order = int(payload.get('sort_order') or 0)
    except ValueError:
        abort(400)
    one_day = parse_day(payload.get('one_time_date')
                        ) if period == 'once' else None
    start = parse_day(payload.get('effective_start')) if payload.get(
        'effective_start') else None
    end = parse_day(payload.get('effective_end')) if payload.get(
        'effective_end') else None
    if start and end and end < start:
        abort(400)
    if (period == 'weekday' and (val is None or not 1 <= val <= 7)) or (period == 'monthday' and (val is None or not 1 <= val <= 31)):
        abort(400, description='每週請輸入 1–7，每月請輸入 1–31')
    if period not in ('weekday', 'monthday'):
        val = None
    policy = payload.get('missing_day_policy') or 'skip'
    if policy not in ('skip', 'last_day'):
        abort(400)
    return {'title': title, 'description': description, 'category': category, 'role_type': role,
            'period_type': period, 'period_val': val, 'one_time_date': one_day,
            'effective_start': start, 'effective_end': end, 'missing_day_policy': policy, 'sort_order': order}


@checklist_admin_bp.route('/tasks', methods=['GET'])
@checklist_admin_required
def task_admin():
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        current_actor(cursor, admin=True)
        cursor.execute(
            'SELECT * FROM checklist_tasks ORDER BY is_active DESC, sort_order, id')
        tasks = cursor.fetchall()
        return render_template('checklist/tasks.html', tasks=tasks, category_names=CATEGORY_NAMES, role_names=ROLE_NAMES)
    finally:
        cursor.close()


@checklist_admin_bp.post('/tasks/save')
@checklist_admin_required
def task_save():
    values = validate_template(request.form)
    task_id = request.form.get('id')
    try:
        task_id = int(task_id) if task_id else None
    except ValueError:
        abort(400)

    def op(cursor):
        actor = current_actor(cursor, admin=True)
        fields = list(values.keys())
        if task_id:
            cursor.execute(
                'SELECT * FROM checklist_tasks WHERE id=%s FOR UPDATE', (task_id,))
            old = cursor.fetchone()
            if not old:
                abort(404)
            sql = 'UPDATE checklist_tasks SET ' + \
                ', '.join(f'{f}=%s' for f in fields)+' WHERE id=%s'
            cursor.execute(sql, tuple(values[f] for f in fields)+(task_id,))
            audit(cursor, actor['id'], 'edit_template', task_id=task_id, old={
                  k: old[k] for k in fields}, new=values)
        else:
            sql = 'INSERT INTO checklist_tasks ('+', '.join(
                fields)+') VALUES ('+', '.join(['%s']*len(fields))+')'
            cursor.execute(sql, tuple(values[f] for f in fields))
            audit(cursor, actor['id'], 'create_template',
                  task_id=cursor.lastrowid, new=values)
        flash('工作模板已儲存；既有日誌內容不會變更', 'success')
        return redirect(url_for('checklist_admin.task_admin'))
    return transact(op)


@checklist_admin_bp.post('/tasks/<int:task_id>/toggle')
@checklist_admin_required
def task_toggle(task_id):
    def op(cursor):
        actor = current_actor(cursor, admin=True)
        cursor.execute(
            'SELECT is_active FROM checklist_tasks WHERE id=%s FOR UPDATE', (task_id,))
        row = cursor.fetchone()
        if not row:
            abort(404)
        next_val = 0 if row['is_active'] else 1
        cursor.execute(
            'UPDATE checklist_tasks SET is_active=%s WHERE id=%s', (next_val, task_id))
        audit(cursor, actor['id'], 'toggle_template', task_id=task_id, old={
              'active': bool(row['is_active'])}, new={'active': bool(next_val)})
        flash('工作項目已'+('啟用' if next_val else '停用')+'，歷史紀錄不受影響', 'success')
        return redirect(url_for('checklist_admin.task_admin'))
    return transact(op)


def cell_text(value):
    """Excel formula injection defense for user-editable strings."""
    if value is None:
        return ''
    if isinstance(value, (date, datetime)):
        return value.isoformat(sep=' ') if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, str):
        s = value[:32767]
        if s.lstrip().startswith(('=', '+', '-', '@')) or s.startswith(('\t', '\r', '\n')):
            s = "'"+s
        return s
    return value


def excel_sheet(wb, title, headers, data):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for row in data:
        ws.append([cell_text(v) for v in row])
    for c in ws[1]:
        c.fill = PatternFill('solid', fgColor='E6F1EB')
        c.font = Font(bold=True, color='20352E')
        c.alignment = Alignment(wrap_text=True, vertical='center')
    ws.freeze_panes = 'B2'
    ws.auto_filter.ref = ws.dimensions
    for col in ws.columns:
        letter = get_column_letter(col[0].column)
        width = min(55, max(13, max(len(str(cell.value or ''))
                    for cell in col[:150])+2))
        ws.column_dimensions[letter].width = width
    return ws


@checklist_admin_bp.get('/export')
@checklist_admin_required
def export():
    view = request.args.get('view', 'day')
    if view not in ('day', 'week', 'month'):
        abort(400)
    day = parse_day(request.args.get('date', taiwan_today().isoformat()))
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        current_actor(cursor, admin=True)
        days = date_span(view, day)
        rows, cells, summary, records, items_by_day = period_grid(cursor, days)
        wb = Workbook()
        wb.remove(wb.active)
        names = display_names(cursor)
        if view == 'day':
            d = days[0]
            rec = records.get(d)
            record_info = [['日期', '值日生', '芳療師／助理', '簽核狀態', '版本', '交接備註'],
                           [d.isoformat(), names.get(rec['duty_user_id'], '') if rec else '', names.get(rec['therapist_user_id'], '') if rec else '',
                            rec['status'] if rec else '未建檔', rec['revision'] if rec else '', rec['handover_notes'] if rec else '']]
            excel_sheet(wb, '當日資訊', record_info[0], record_info[1:])
        else:
            detail = []
            for d in days:
                s = summary[d]
                detail.append([d, s['status'], s['total'], s['done'], s['na'], s['pending'],
                               round(100*(s['done']+s['na'])/s['total'], 1) if s['total'] else None])
            excel_sheet(wb, '每日統計', ['日期', '日誌狀態', '適用任務',
                        '已完成', '不適用', '未完成', '已處理率(%)'], detail)
            excel_sheet(wb, '週月矩陣', ['工作項目']+[d.strftime('%m/%d') for d in days],
                        [[row['title']]+[{'done': '完成', 'pending': '未完成', 'na': '不適用',
                                          'void': '取消', 'unfiled': '未建檔', 'future': '未開始', 'not_applicable': '—'}
                                         [cells[(row['key'], d.isoformat())]] for d in days] for row in rows])
        rows_detail = []
        for d in days:
            for item in items_by_day[d]:
                rows_detail.append([d, CATEGORY_NAMES[item['snapshot_category']], ROLE_NAMES[item['snapshot_role']],
                                    item['snapshot_title'], item['snapshot_description'], STATE_NAMES[item['state']],
                                    item['note'], names.get(item['done_by_user_id'], '') if item['done_by_user_id'] else '', item['done_at'], item['updated_at']])
        excel_sheet(wb, '逐項明細', ['日期', '工作階段', '負責角色', '工作名稱',
                    '工作內容', '狀態', '備註', '完成者', '完成時間', '最後更新'], rows_detail)
        if records:
            record_ids = [r['id'] for r in records.values()]
            placeholders = ','.join(['%s']*len(record_ids))
            cursor.execute(f'''SELECT r.log_date,s.revision,s.signer_role,s.signed_by_user_id,
                                s.signed_at FROM checklist_signoffs s
                                JOIN checklist_daily_records r ON s.record_id=r.id
                                WHERE s.record_id IN ({placeholders}) ORDER BY r.log_date,s.revision,s.signer_role''', tuple(record_ids))
            signoffs = cursor.fetchall()
        else:
            signoffs = []
        excel_sheet(wb, '簽核紀錄', ['日期', '版本', '簽核角色', '簽核人', '簽核時間'],
                    [[s['log_date'], s['revision'], ROLE_NAMES[s['signer_role']], names.get(s['signed_by_user_id'], '') if s['signed_by_user_id'] else '', s['signed_at']] for s in signoffs])
        if records:
            cursor.execute(f'''SELECT r.log_date, a.created_at, a.action, a.actor_user_id, a.old_value, a.new_value
                                FROM checklist_audit_logs a
                                JOIN checklist_daily_records r ON r.id=a.record_id
                                WHERE a.record_id IN ({placeholders}) ORDER BY a.created_at,a.id''', tuple(record_ids))
            audits = cursor.fetchall()
        else:
            audits = []
        excel_sheet(wb, '操作紀錄', ['檢核日期', '操作時間', '操作類型', '操作人', '修改前', '修改後'],
                    [[a['log_date'], a['created_at'], a['action'], names.get(a['actor_user_id'], '') if a['actor_user_id'] else '', a['old_value'], a['new_value']] for a in audits])
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name=f'JP_AROMATIC_checklist_{view}_{day.isoformat()}.xlsx')
    finally:
        cursor.close()
