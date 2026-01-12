"""
Notification System for 晶品芳療
Updated: Uses LINE Messaging API for Group Notifications & Customer Emails
"""

from flask import current_app, url_for
from linebot import LineBotApi
from linebot.models import TextSendMessage
from linebot.exceptions import LineBotApiError
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading
import socket


_original_getaddrinfo = socket.getaddrinfo


def _ipv4_only_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    # 強制指定 family 為 AF_INET (IPv4)
    return _original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


# 套用補丁
socket.getaddrinfo = _ipv4_only_getaddrinfo

# ==========================================
# 📧 EMAIL 基礎函式
# ==========================================


def send_email(to, subject, body, html=None):
    """發送 Email 的通用函式"""
    try:
        mail_server = current_app.config.get('MAIL_SERVER')
        mail_port = current_app.config.get('MAIL_PORT')  # 這裡應該是 465
        mail_username = current_app.config.get('MAIL_USERNAME')
        mail_password = current_app.config.get('MAIL_PASSWORD')
        mail_from = current_app.config.get('MAIL_DEFAULT_SENDER')

        if isinstance(mail_from, tuple):
            mail_from = f"{mail_from[0]} <{mail_from[1]}>"

        if not all([mail_server, mail_username, mail_password]):
            print("⚠️ Email config missing, skipping email.")
            return False

        print(f"📧 [Debug] 準備連線 (SSL): {mail_server}:{mail_port}")

        msg = MIMEMultipart('alternative')
        msg['From'] = mail_from
        msg['To'] = to
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        if html:
            msg.attach(MIMEText(html, 'html', 'utf-8'))

        # ⭐ 重點修改：使用 SMTP_SSL (配合 Port 465)
        # 這種方式一開始就是加密的，不需要 starttls()
        server = smtplib.SMTP_SSL(mail_server, mail_port)

        print("📧 [Debug] 連線成功，正在登入...")
        server.login(mail_username, mail_password)

        print("📧 [Debug] 正在寄送...")
        server.send_message(msg)
        server.quit()

        print("✅ Email 發送成功！")
        return True
    except Exception as e:
        print(f"❌ Email failed: {e}")
        return False


def send_email_async(app, to, subject, body, html=None):
    with app.app_context():
        send_email(to, subject, body, html)

# ==========================================
# 💬 LINE MESSAGING API 基礎函式
# ==========================================


def send_line_push_message(target_id, message_text):
    """
    通用函式：發送訊息給 User ID 或 Group ID
    """
    token = current_app.config.get('LINE_CHANNEL_ACCESS_TOKEN')
    if not token or not target_id:
        return False

    try:
        line_bot_api = LineBotApi(token)
        line_bot_api.push_message(
            target_id, TextSendMessage(text=message_text))
        return True
    except Exception as e:
        print(f"❌ LINE Push failed: {e}")
        return False


def send_group_notification(message_text):
    """
    ⭐ 專門發送給「管理員群組」的函式
    """
    # 從 config 讀取群組 ID
    group_id = current_app.config.get('LINE_ADMIN_GROUP_ID')

    if group_id:
        return send_line_push_message(group_id, message_text)
    else:
        print("⚠️ 未設定 LINE_ADMIN_GROUP_ID，無法發送群組通知")
        return False


def send_customer_line_message(user_line_id, message_text):
    """發送給客戶"""
    return send_line_push_message(user_line_id, message_text)

# ==========================================
# 🔄 整合通知流程
# ==========================================


def notify_new_order_created(order_id, customer_name, customer_email, total_amount, items_text):
    """新訂單成立"""
    app = current_app._get_current_object()

    # 1. LINE 通知管理員群組
    msg_text = f"🛍️ [新訂單] #{order_id}\n客戶：{customer_name}\n金額：NT$ {total_amount:,.0f}\n\n請至後台確認。"
    send_group_notification(msg_text)

    # 2. Email 通知客戶
    if customer_email:
        subject = '晶品芳療 - 訂單申請已收到'
        body = f"""親愛的 {customer_name}，\n\n感謝您的訂購！您的訂單 #{order_id} 申請已收到。\n\n訂購內容：\n{items_text}\n\n總金額：NT$ {total_amount:,.0f}\n\n我們將盡快確認訂單。"""
        threading.Thread(target=send_email_async, args=(
            app, customer_email, subject, body)).start()


def notify_new_booking_created(booking_id, customer_name, customer_email, course_name, time_str):
    """新預約成立 (待確認)"""
    app = current_app._get_current_object()

    # 1. LINE 通知管理員群組
    msg_text = (
        f"📅 [新預約申請] #{booking_id}\n"
        f"狀態：待確認\n"
        f"------------------\n"
        f"客戶：{customer_name}\n"
        f"課程：{course_name}\n"
        f"時段：{time_str}\n"
        f"------------------\n"
        f"請管理員至後台確認。"
    )
    send_group_notification(msg_text)

    # 2. Email 通知客戶
    if customer_email:
        cust_subject = '晶品芳療 - 預約申請已收到'
        cust_body = (
            f"親愛的 {customer_name} 您好：\n\n"
            f"我們已收到您的預約申請！\n"
            f"預約單號：#{booking_id}\n"
            f"課程：{course_name}\n"
            f"時段：{time_str}\n\n"
            f"⚠️ 目前狀態為【待確認】。\n"
            f"服務人員確認時段後，將會發送預約確認信給您。\n"
        )
        threading.Thread(
            target=send_email_async,
            args=(app, customer_email, cust_subject, cust_body)
        ).start()


def notify_order_confirmed(order_id, customer, total_amount):
    """訂單確認 (通知取貨)"""
    app = current_app._get_current_object()
    msg = f"✅ 訂單 #{order_id} 已確認！\n金額：NT$ {total_amount:,.0f}\n請您於營業時間前往店內付款取貨，謝謝！"

    # LINE 通知客戶
    if customer.get('line_id'):
        send_customer_line_message(customer['line_id'], msg)

    # Email 通知客戶 (非同步)
    if customer.get('email'):
        subject = f"晶品芳療 - 訂單 #{order_id} 確認通知"
        threading.Thread(target=send_email_async, args=(
            app, customer['email'], subject, msg)).start()


def notify_booking_confirmed(booking_id, customer, course_name, time_str):
    """預約確認"""
    app = current_app._get_current_object()
    msg = f"✅ 預約 #{booking_id} 已確認！\n課程：{course_name}\n時間：{time_str}\n\n我們已為您保留時段，請準時蒞臨。"

    # LINE 通知客戶
    if customer.get('line_id'):
        send_customer_line_message(customer['line_id'], msg)

    # Email 通知客戶 (非同步)
    if customer.get('email'):
        subject = f"晶品芳療 - 預約 #{booking_id} 確認通知"
        threading.Thread(target=send_email_async, args=(
            app, customer['email'], subject, msg)).start()


def notify_contact_message(name, email, phone, line_id, message):
    """聯絡表單通知"""
    app = current_app._get_current_object()

    # LINE 通知群組
    msg_text = f"📧 [新聯絡訊息]\n姓名：{name}\nEmail：{email}\n電話：{phone}\n內容：{message}"
    send_group_notification(msg_text)

    # Email 回信給客戶 (非同步)
    if email:
        subject = '晶品芳療 - 已收到您的訊息'
        body = f"親愛的 {name}，我們已收到您的訊息，將盡快回覆。\n\n您的訊息：\n{message}"
        threading.Thread(target=send_email_async, args=(
            app, email, subject, body)).start()
    return True


def notify_order_status_update(order_id, customer_name, customer_email, status):
    """訂單狀態變更 (Email)"""
    app = current_app._get_current_object()
    status_map = {'confirmed': '已確認', 'completed': '已完成', 'cancelled': '已取消'}
    status_text = status_map.get(status, status)

    if customer_email:
        subject = f'晶品芳療 - 訂單狀態更新 ({status_text})'
        body = f"親愛的 {customer_name}，訂單 #{order_id} 狀態已更新為：{status_text}。"
        threading.Thread(target=send_email_async, args=(
            app, customer_email, subject, body)).start()


def notify_booking_status_update(booking_id, customer_name, customer_email, course_name, status):
    """預約狀態變更 (Email)"""
    app = current_app._get_current_object()
    status_map = {'confirmed': '已確認', 'completed': '已完成', 'cancelled': '已取消'}
    status_text = status_map.get(status, status)

    if customer_email:
        subject = f'晶品芳療 - 預約狀態更新 ({status_text})'
        body = f"親愛的 {customer_name}，預約 #{booking_id} ({course_name}) 狀態已更新為：{status_text}。"
        threading.Thread(target=send_email_async, args=(
            app, customer_email, subject, body)).start()


def send_password_reset_email(to_email, token):
    """發送密碼重設信"""
    app = current_app._get_current_object()
    reset_url = url_for('auth.reset_password', token=token, _external=True)

    subject = "晶品芳療 - 重設您的密碼"
    body = f"""
親愛的會員您好：

我們收到了您重設密碼的請求。
請點擊下方連結以設定新密碼：

{reset_url}

連結將在 15 分鐘後失效。
如果您沒有要求重設密碼，請忽略此信。

晶品芳療團隊
    """

    # 改為非同步發送
    threading.Thread(target=send_email_async, args=(
        app, to_email, subject, body)).start()
