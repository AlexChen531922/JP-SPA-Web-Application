"""Staff-only course sales and redemption bookings (JP SPA 05).

Course purchases are paid in full. Deposited customer products are not a payment
method for fixed-price store-consumable courses. Session booking has no new sale.
"""
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal

import MySQLdb
import MySQLdb.cursors
from flask import Blueprint, request, flash, redirect, url_for, jsonify, current_app

from project.decorators import staff_required
from project.db import get_current_user_id
from project.extensions import database
from project.stored_value import money, change_balance
from project.course_entitlements import (available_sessions, load_tiers, occupy_schedule,
                                         positive_money, reserve_for_booking, record_course_event)
from project.course_service import complete_course_booking

course_sales_bp = Blueprint('course_sales', __name__)
_ALLOWED_METHODS = {'cash', 'credit_card', 'bank_transfer', 'stored_value', 'other'}


def _request_key():
    value = (request.form.get('request_key') or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{20,55}', value):
        raise ValueError('請重新整理頁面再提交課程操作')
    return value


def _actor():
    actor = get_current_user_id()
    if not actor:
        raise ValueError('沒有有效的操作人員')
    return actor


def _payments(raw, total):
    if not raw or len(raw) > 6000:
        raise ValueError('課程付款明細不存在或過長')
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValueError('付款格式錯誤') from exc
    if not isinstance(data, list) or not (1 <= len(data) <= 20):
        raise ValueError('請填寫 1～20 筆付款明細')
    result = []
    for entry in data:
        if not isinstance(entry, dict) or entry.get('method') not in _ALLOWED_METHODS:
            raise ValueError('不支援的付款方式：套裝課程不可使用寄店抵扣')
        amount = money(entry.get('amount'))
        if amount < 0 or amount != amount.to_integral_value():
            raise ValueError('付款金額須為非負整數元')
        if amount > 0:
            result.append((entry['method'], amount))
    if sum((a for _, a in result), Decimal('0')) != total:
        raise ValueError('課程必須全額付清，所有付款方式金額合計須等於實際售價')
    return result


def _nonnegative_integer(raw, label):
    amount = money(raw if raw not in (None, '') else '0')
    if amount < 0 or amount != amount.to_integral_value() or amount > Decimal('99999999.99'):
        raise ValueError(f'{label}必須為非負整數元')
    return amount


def _sale_components(form, course, sessions, customer_id, cursor):
    # Retail pricing components, not inventory costs and not payment methods.
    if sessions != 1:
        # Multi-session fixed sales retain their own discounted price and use shop materials.
        return 'store', Decimal('0'), Decimal('0'), Decimal('0'), 1
    mode = (form.get('material_mode') or 'store').strip()
    if mode not in ('store', 'customer', 'mixed'):
        raise ValueError('課程耗材來源不正確')
    if course['uses_store_consumables'] and mode != 'store':
        raise ValueError('此固定價套裝課程只使用店內耗材')
    hand = _nonnegative_integer(form.get('hand_fee'), '手技費')
    store_charge = _nonnegative_integer(form.get('store_product_fee'), '店內產品收費')
    customer_value = _nonnegative_integer(form.get('customer_product_value'), '客戶寄店產品已購價值')
    if mode == 'store' and customer_value:
        raise ValueError('僅用店內耗材時不可填寫客戶寄店產品價值')
    if mode == 'customer' and store_charge:
        raise ValueError('僅用客戶寄店產品時不可再填店內產品收費')
    if mode in ('customer', 'mixed'):
        cursor.execute('''SELECT COUNT(*) AS n FROM customer_inventory
                          WHERE customer_id=%s AND remaining_amount>0
                            AND capacity_unit IN ('ml','g')''', (customer_id,))
        if cursor.fetchone()['n'] == 0:
            raise ValueError('客戶尚無可用的寄店產品容量，不能選擇寄店來源')
    return mode, hand, store_charge, customer_value, 1


def _audit(cursor, actor, action, target_id, details):
    cursor.execute('''INSERT INTO audit_logs
        (user_id,action,target_type,target_id,details,ip_address)
        VALUES (%s,%s,'course_purchase',%s,%s,%s)''',
        (actor, action, target_id, json.dumps(details, ensure_ascii=False), request.remote_addr))


def _make_booking(cursor, purchase_id, customer_id, course_id, appointment, actor, request_key=None):
    cursor.execute('SELECT duration FROM courses WHERE id=%s AND is_active=1', (course_id,))
    course = cursor.fetchone()
    if not course:
        raise ValueError('課程不存在或已停用')
    schedule_id = occupy_schedule(cursor, appointment, int(course['duration'] or 60))
    cursor.execute('''INSERT INTO bookings
        (customer_id,course_id,global_schedule_id,total_amount,is_first_time,
         sessions_purchased,sessions_remaining,status,booking_date,payment_method,
         course_booking_request_key)
        VALUES (%s,%s,%s,0,0,0,0,'confirmed',%s,'prepaid_course',%s)''',
        (customer_id,course_id,schedule_id,appointment,request_key))
    booking_id = cursor.lastrowid
    reserve_for_booking(cursor, purchase_id, customer_id, course_id, booking_id, actor)
    return booking_id


@course_sales_bp.route('/course-sales', methods=['POST'])
@staff_required
def sell():
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        key = _request_key()
        actor = _actor()
        customer_id = request.form.get('customer_id', type=int)
        course_id = request.form.get('course_id', type=int)
        count = request.form.get('sessions', type=int)
        if not customer_id or not course_id or not count or count < 1 or count > 100:
            raise ValueError('客戶、課程或購買堂數不正確')
        final_price = positive_money(request.form.get('final_price'), '實際售價')
        if final_price != final_price.to_integral_value():
            raise ValueError('課程銷售金額須為整數元')
        payment_lines = _payments(request.form.get('payments_json'), final_price)
        use_mode = request.form.get('use_mode', 'save')
        if use_mode not in ('save', 'now', 'future', 'existing'):
            raise ValueError('使用安排不正確')
        appt = None
        if use_mode in ('now', 'future'):
            try:
                appt = datetime.strptime(request.form.get('appointment_time') or '', '%Y-%m-%dT%H:%M')
            except ValueError as exc:
                raise ValueError('請填寫正確的預約時間') from exc
            today = datetime.now(ZoneInfo('Asia/Taipei')).date()
            if use_mode == 'now' and appt.date() != today:
                raise ValueError('現場使用僅限台灣今日服務；其他日期請選擇未來預約')
            if use_mode == 'future' and appt.date() <= today:
                raise ValueError('未來預約請選擇台灣明日之後的日期')
        database.connection.begin()
        cursor.execute("SELECT id,email FROM users WHERE id=%s AND role='customer'", (customer_id,))
        user = cursor.fetchone()
        if not user or user['email'] == 'store@jparomatic.local':
            raise ValueError('客戶帳號不存在，或屬於店內損耗專用帳號')
        cursor.execute('''SELECT id,regular_price,experience_price,is_active,uses_store_consumables
                          FROM courses WHERE id=%s FOR UPDATE''', (course_id,))
        course = cursor.fetchone()
        if not course or not course['is_active']:
            raise ValueError('課程已停用，無法販售')
        pricing_mode = (request.form.get('pricing_mode') or 'regular').strip()
        if pricing_mode not in ('regular', 'experience'):
            raise ValueError('課程售價類型不正確')
        if count != 1 and pricing_mode == 'experience':
            raise ValueError('多堂優惠不得同時選用單堂體驗價')
        tiers = load_tiers(cursor, course_id)
        if count == 1:
            if pricing_mode == 'experience':
                if not course['experience_price'] or money(course['experience_price']) <= 0:
                    raise ValueError('此課程未設定可用的體驗價')
                default_price = money(course['experience_price'])
            else:
                default_price = money(course['regular_price'])
        else:
            default_price = tiers.get(count)
        if default_price is None:
            raise ValueError('此課程沒有設定該購買堂數，請先到課程管理設定優惠')
        mode, hand, store_charge, client_value, must_reconcile = _sale_components(
            request.form, course, count, customer_id, cursor)
        # Client-owned product value was paid on a historical product order.
        # It must not be charged or treated as new cash on this sale.
        adjustment = final_price - (hand + store_charge) if count == 1 else Decimal('0')
        cursor.execute('''INSERT INTO customer_course_purchases
            (request_key,customer_id,course_id,total_sessions,total_paid,default_total,
             completed_sessions,reserved_sessions,status,sold_by,
             material_mode,component_hand_fee,component_store_fee,
             component_customer_value,price_adjustment,requires_material_confirmation)
            VALUES (%s,%s,%s,%s,%s,%s,0,0,'active',%s,%s,%s,%s,%s,%s,%s)''',
            (key,customer_id,course_id,count,final_price,default_price,actor,
             mode,hand,store_charge,client_value,adjustment,must_reconcile))
        purchase_id = cursor.lastrowid
        record_course_event(cursor,purchase_id,None,'sale',actor)
        paid_with_wallet = Decimal('0')
        for method, amount in payment_lines:
            cursor.execute('''INSERT INTO customer_course_payments
                (purchase_id,method,amount,operated_by) VALUES (%s,%s,%s,%s)''',
                (purchase_id,method,amount,actor))
            if method == 'stored_value':
                paid_with_wallet += amount
        if paid_with_wallet:
            change_balance(cursor, customer_id, -paid_with_wallet, 'spend', actor,
                           notes=f'課程購買 #{purchase_id} 儲值扣款', request_key=f'cps_{key}')
        booking_id = None
        if use_mode == 'existing':
            existing_id = request.form.get('link_booking_id', type=int)
            if not existing_id:
                raise ValueError('請選擇要連結的既有純預約')
            cursor.execute('''SELECT id,status FROM bookings
                WHERE id=%s AND customer_id=%s AND course_id=%s
                  AND is_unpaid_course_booking=1 AND course_purchase_id IS NULL
                  FOR UPDATE''', (existing_id, customer_id, course_id))
            existing = cursor.fetchone()
            if not existing or existing['status'] not in ('pending', 'confirmed'):
                raise ValueError('既有預約不存在、已取消、已完成或已關聯其他課程購買')
            reserve_for_booking(cursor,purchase_id,customer_id,course_id,existing_id,actor)
            cursor.execute('''UPDATE bookings SET is_unpaid_course_booking=0,
                payment_method='prepaid_course',sessions_purchased=0,sessions_remaining=0 WHERE id=%s''', (existing_id,))
            booking_id = existing_id
        elif appt:
            booking_id = _make_booking(cursor,purchase_id,customer_id,course_id,appt,actor)
        _audit(cursor, actor, 'create', purchase_id,
               {'course_id':course_id,'sessions':count,'default_total':str(default_price),
                'final_price':str(final_price),'payment_methods':[m for m,_ in payment_lines],
                'appointment_booking_id':booking_id,'material_mode':mode,
                'pricing_mode':pricing_mode,
                'hand_fee':str(hand),'store_product_fee':str(store_charge),
                'customer_deposited_value':str(client_value),
                'price_adjustment':str(adjustment)})
        database.connection.commit()
        flash(f'課程販售成功：已購 {count} 堂'+(f'，預約 #{booking_id} 已保留 1 堂' if booking_id else '，堂數已存入客戶帳戶'), 'success')
    except MySQLdb.IntegrityError as exc:
        database.connection.rollback()
        flash('這份課程操作已送出過，或資料庫約束檢查失敗；未重複銷售', 'error')
        current_app.logger.warning('Course sale integrity conflict: %s', getattr(exc, 'args', [None])[0])
    except (ValueError,TypeError) as exc:
        database.connection.rollback()
        flash(f'課程販售失敗：{exc}', 'error')
    except Exception:
        database.connection.rollback()
        current_app.logger.exception('Course sale failed')
        flash('課程販售失敗，整筆交易已撤銷，請查看伺服器紀錄', 'error')
    finally:
        cursor.close()
    return redirect(url_for('admin.dashboard', tab='bookings'))


@course_sales_bp.route('/api/customer/<int:customer_id>/course-purchases')
@staff_required
def customer_purchases(customer_id):
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        cursor.execute('''SELECT p.id,p.course_id,c.name AS course_name,p.total_sessions,
            p.completed_sessions,p.reserved_sessions
            FROM customer_course_purchases p JOIN courses c ON c.id=p.course_id
            JOIN users u ON u.id=p.customer_id
            WHERE p.customer_id=%s AND p.status='active' AND c.is_active=1
              AND u.email!='store@jparomatic.local'
            ORDER BY p.id DESC''', (customer_id,))
        purchases = [dict(id=r['id'],course_id=r['course_id'],course_name=r['course_name'],
                          available=available_sessions(r),total=r['total_sessions'],
                          completed=r['completed_sessions'],reserved=r['reserved_sessions'])
                     for r in cursor.fetchall() if available_sessions(r)>0]
        return jsonify(purchases)
    finally:
        cursor.close()


@course_sales_bp.route('/course-owned-book', methods=['POST'])
@staff_required
def book_owned():
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        key = _request_key()
        actor = _actor()
        customer_id = request.form.get('customer_id',type=int)
        purchase_id = request.form.get('purchase_id',type=int)
        if not customer_id or not purchase_id:
            raise ValueError('請選擇客戶及已購課程')
        try:
            appt = datetime.strptime(request.form.get('appointment_time') or '', '%Y-%m-%dT%H:%M')
        except ValueError as exc:
            raise ValueError('請選擇預約時間') from exc
        database.connection.begin()
        cursor.execute('''SELECT course_id FROM customer_course_purchases
            WHERE id=%s AND customer_id=%s AND status='active' FOR UPDATE''',(purchase_id,customer_id))
        purchase = cursor.fetchone()
        if not purchase:
            raise ValueError('找不到客戶已購課程')
        booking_id = _make_booking(cursor,purchase_id,customer_id,purchase['course_id'],appt,actor,key)
        _audit(cursor, actor, 'reserve', purchase_id,
               {'booking_id':booking_id,'customer_id':customer_id,'course_id':purchase['course_id']})
        database.connection.commit()
        flash(f'預約 #{booking_id} 已建立，暫時保留一堂；完成服務後才正式扣堂', 'success')
    except MySQLdb.IntegrityError:
        database.connection.rollback()
        flash('這份預約已送出或時段已被占用，請確認預約紀錄', 'error')
    except (ValueError,TypeError) as exc:
        database.connection.rollback()
        flash(f'已購堂數預約失敗：{exc}', 'error')
    except Exception:
        database.connection.rollback()
        current_app.logger.exception('Book owned course failed')
        flash('建立已購課程預約失敗，整筆操作未生效', 'error')
    finally:
        cursor.close()
    return redirect(url_for('admin.dashboard', tab='bookings'))


@course_sales_bp.route('/course-unpaid-book', methods=['POST'])
@staff_required
def book_unpaid():
    # A reservation is not a sale. No cash, revenue or course credit is created.
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        key = _request_key()
        actor = _actor()
        customer_id = request.form.get('customer_id',type=int)
        course_id = request.form.get('course_id',type=int)
        if not customer_id or not course_id:
            raise ValueError('請選擇客戶與課程')
        try:
            appointment = datetime.strptime(request.form.get('appointment_time') or '', '%Y-%m-%dT%H:%M')
        except ValueError as exc:
            raise ValueError('請輸入有效的預約時間') from exc
        database.connection.begin()
        cursor.execute("SELECT id FROM users WHERE id=%s AND role='customer' AND email!='store@jparomatic.local'",
                       (customer_id,))
        if not cursor.fetchone():
            raise ValueError('不可將店內耗材帳戶當成接受服務的客戶')
        cursor.execute('SELECT id,duration FROM courses WHERE id=%s AND is_active=1', (course_id,))
        course = cursor.fetchone()
        if not course:
            raise ValueError('課程已停用或不存在')
        schedule_id = occupy_schedule(cursor,appointment,int(course['duration'] or 60))
        cursor.execute('''INSERT INTO bookings
            (customer_id,course_id,global_schedule_id,total_amount,is_first_time,
             sessions_purchased,sessions_remaining,status,booking_date,payment_method,
             course_booking_request_key,is_unpaid_course_booking)
             VALUES (%s,%s,%s,0,0,0,0,'pending',%s,'unpaid_booking',%s,1)''',
             (customer_id,course_id,schedule_id,appointment,key))
        booking_id = cursor.lastrowid
        _audit(cursor,actor,'create_unpaid_booking',booking_id,
               {'customer_id':customer_id,'course_id':course_id,'appointment_time':str(appointment)})
        database.connection.commit()
        flash(f'純預約 #{booking_id} 已建立，尚未購買課程；不產生收款或已購堂數', 'success')
    except MySQLdb.IntegrityError:
        database.connection.rollback()
        flash('此預約已提交或時段資料衝突，未重複建立', 'error')
    except (ValueError,TypeError) as exc:
        database.connection.rollback()
        flash(f'建立純預約失敗：{exc}', 'error')
    except Exception:
        database.connection.rollback()
        current_app.logger.exception('Unpaid course booking failed')
        flash('建立純預約失敗，未修改資料庫', 'error')
    finally:
        cursor.close()
    return redirect(url_for('admin.dashboard',tab='bookings'))


@course_sales_bp.route('/api/customer/<int:customer_id>/unpaid-bookings')
@staff_required
def unpaid_bookings(customer_id):
    course_id = request.args.get('course_id',type=int)
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        if not course_id:
            return jsonify([])
        cursor.execute('''SELECT b.id, s.start_time FROM bookings b
            LEFT JOIN shop_schedules s ON s.id=b.global_schedule_id
            WHERE b.customer_id=%s AND b.course_id=%s
              AND b.is_unpaid_course_booking=1 AND b.course_purchase_id IS NULL
              AND b.status IN ('pending','confirmed') ORDER BY s.start_time,b.id''',
              (customer_id,course_id))
        return jsonify([{'id':r['id'], 'time':r['start_time'].strftime('%Y-%m-%d %H:%M')
                         if r['start_time'] else '未設定時間'} for r in cursor.fetchall()])
    finally:
        cursor.close()


@course_sales_bp.route('/course-booking/<int:booking_id>/complete', methods=['POST'])
@staff_required
def complete(booking_id):
    cursor = database.connection.cursor(MySQLdb.cursors.DictCursor)
    try:
        key = _request_key()
        actor = _actor()
        raw = request.form.get('materials_json','[]')
        database.connection.begin()
        summary = complete_course_booking(cursor,booking_id,key,raw,actor,request.remote_addr)
        database.connection.commit()
        # External notification is sent only after the atomic DB commit.
        try:
            cursor.execute('''SELECT u.firstname,u.email FROM bookings b
                JOIN users u ON u.id=b.customer_id WHERE b.id=%s''', (booking_id,))
            recipient = cursor.fetchone()
            if recipient:
                from project.notifications import notify_booking_status_update
                notify_booking_status_update(booking_id,recipient['firstname'],recipient['email'],'completed')
        except Exception:
            current_app.logger.warning('06 completion notification failed for booking %s',booking_id)
        flash(f"課程 #{booking_id} 已完成並核銷 1 堂；實際耗材共 {summary['lines']} 筆",'success')
    except MySQLdb.IntegrityError:
        database.connection.rollback()
        flash('此課程已結案或核銷請求重複，未再次扣除', 'error')
    except (ValueError,TypeError) as exc:
        database.connection.rollback()
        flash(f'完成課程失敗：{exc}', 'error')
    except Exception:
        database.connection.rollback()
        current_app.logger.exception('Atomic course material completion failed')
        flash('課程核銷未成功，堂數與耗材皆未扣除', 'error')
    finally:
        cursor.close()
    return redirect(url_for('admin.dashboard',tab='bookings'))
