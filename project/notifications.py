"""
Notification System for 晶品芳療
Supports Email and LINE Notify
"""

from flask import current_app
from linebot import LineBotApi
from linebot.models import TextSendMessage
from linebot.exceptions import LineBotApiError
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests


# ==========================================
# EMAIL FUNCTIONS
# ==========================================

def send_email(to, subject, body, html=None):
    try:
        mail_server = current_app.config.get('MAIL_SERVER')
        mail_port = current_app.config.get('MAIL_PORT')
        mail_username = current_app.config.get('MAIL_USERNAME')
        mail_password = current_app.config.get('MAIL_PASSWORD')
        mail_from = current_app.config.get('MAIL_DEFAULT_SENDER')

        if isinstance(mail_from, tuple):
            mail_from = f"{mail_from[0]} <{mail_from[1]}>"

        if not all([mail_server, mail_username, mail_password]):
            current_app.logger.warning("Email config missing")
            return False

        msg = MIMEMultipart('alternative')
        msg['From'] = mail_from
        msg['To'] = to
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        if html:
            msg.attach(MIMEText(html, 'html', 'utf-8'))

        server = smtplib.SMTP(mail_server, mail_port)
        server.starttls()
        server.login(mail_username, mail_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        current_app.logger.error(f"Email failed: {e}")
        return False


# ==========================================
# LINE NOTIFY FUNCTIONS
# ==========================================

def send_admin_line_notify(message):
    """發送給管理員 (LINE Notify)"""
    token = current_app.config.get('LINE_NOTIFY_TOKEN')
    if not token:
        return False

    try:
        requests.post(
            'https://notify-api.line.me/api/notify',
            headers={'Authorization': f'Bearer {token}'},
            data={'message': message},
            timeout=10
        )
        return True
    except Exception as e:
        current_app.logger.error(f"LINE Notify failed: {e}")
        return False


def send_customer_line_message(user_line_id, message_text):
    """發送給客戶 (Messaging API)"""
    token = current_app.config.get('LINE_CHANNEL_ACCESS_TOKEN')
    if not token or not user_line_id:
        return False

    try:
        line_bot_api = LineBotApi(token)
        line_bot_api.push_message(
            user_line_id, TextSendMessage(text=message_text))
        return True
    except Exception as e:
        current_app.logger.error(f"LINE Push failed: {e}")
        return False


# ==========================================
# NEW ORDER NOTIFICATIONS ADMIN
# ==========================================
def notify_new_order_created(order_id, customer_name, customer_email, total_amount, items_text):
    """新訂單成立 (給客戶的接收通知信)"""

    # 1. 通知管理員 (LINE)
    admin_msg = f"🛍️ [新訂單待確認] #{order_id}\n{customer_name} - NT$ {total_amount:,.0f}\n請至後台確認。"
    send_admin_line_notify(admin_msg)

    # 2. 通知客戶 (Email) - 簡化版內容
    if customer_email:
        subject = '晶品芳療 - 訂單申請已收到'
        body = f"""
親愛的 {customer_name}，

感謝您的訂購！您的訂單 #{order_id} 申請已收到。

訂購項目：
{items_text}
金額：NT$ {total_amount:,.0f}

━━━━━━━━━━━━━━━━━━━━━━
📌 接下來的步驟
━━━━━━━━━━━━━━━━━━━━━━

1. 我們將於 1-2 個工作天內確認您的訂單
2. 確認後會透過 Email 和 LINE 通知您

(此信件為系統自動發送，請勿直接回覆)
"""
        # (HTML 版請自行保留對應的簡化內容)
        send_email(customer_email, subject, body)


def notify_new_booking_created(booking_id, customer_name, customer_email, course_name, time_str):
    """新預約成立 (給客戶的接收通知信)"""

    # 1. 通知管理員 (LINE)
    admin_msg = f"📅 [新預約待確認] #{booking_id}\n{customer_name} - {course_name}\n{time_str}\n請至後台確認。"
    send_admin_line_notify(admin_msg)

    # 2. 通知客戶 (Email)
    if customer_email:
        subject = '晶品芳療 - 預約申請已收到'
        body = f"""
親愛的 {customer_name}，

我們已收到您的課程預約申請。

預約課程：{course_name}
預約時段：{time_str}

━━━━━━━━━━━━━━━━━━━━━━
📌 接下來的步驟
━━━━━━━━━━━━━━━━━━━━━━

1. 我們將於 1-2 個工作天內確認您的預約時段
2. 確認後會透過 Email 和 LINE 通知您

(此信件為系統自動發送，請勿直接回覆)
"""
        send_email(customer_email, subject, body)

# ==========================================
# 2. Customer Confirmation Notifications
# ==========================================


def notify_order_confirmed(order_id, customer, total_amount):
    """訂單確認通知 (告知可取貨/付款)"""

    # LINE 訊息
    line_msg = f"✅ 訂單 #{order_id} 已確認！\n金額：NT$ {total_amount:,.0f}\n\n您現在可以前往店內付款取貨囉！期待您的光臨。"
    if customer.get('line_id'):
        send_customer_line_message(customer['line_id'], line_msg)

    # Email
    subject = f"晶品芳療 - 訂單 #{order_id} 確認通知"
    body = f"""
親愛的 {customer['firstname']}，

好消息！您的訂單 #{order_id} 已經確認。

━━━━━━━━━━━━━━━━━━━━━━
✅ 訂單狀態：已確認 (可取貨)
━━━━━━━━━━━━━━━━━━━━━━

訂單金額：NT$ {total_amount:,.0f}

請您於營業時間內，前往店內取貨並完成付款。
地址：新北市新莊區思源路296巷37號1樓
營業時間：週一至週日 09:00-18:00

期待您的光臨！
"""
    send_email(customer['email'], subject, body)


def notify_booking_confirmed(booking_id, customer, course_name, time_str):
    """預約確認通知 (告知準時出席)"""

    # LINE 訊息
    line_msg = f"✅ 預約 #{booking_id} 已確認！\n課程：{course_name}\n時間：{time_str}\n\n我們已經為您保留時段，請準時蒞臨，期待為您服務！"
    if customer.get('line_id'):
        send_customer_line_message(customer['line_id'], line_msg)

    # Email
    subject = f"晶品芳療 - 預約 #{booking_id} 確認通知"
    body = f"""
親愛的 {customer['firstname']}，

好消息！您的預約已經確認。

━━━━━━━━━━━━━━━━━━━━━━
✅ 預約狀態：已確認
━━━━━━━━━━━━━━━━━━━━━━

課程名稱：{course_name}
預約時段：{time_str}

我們已經為您保留了專屬時段與芳療師。
請您準時蒞臨，讓身心靈享受一段放鬆的旅程。

地址：新北市新莊區思源路296巷37號1樓
"""
    send_email(customer['email'], subject, body)


# ==========================================
# CONTACT FORM NOTIFICATIONS
# ==========================================

def notify_contact_message(name, email, phone, line_id, message):
    """
    Send notification for contact form submission

    Args:
        name (str): Sender name
        email (str): Sender email
        phone (str): Sender phone
        line_id (str): Sender LINE ID
        message (str): Message content

    Returns:
        dict: Status of notifications sent
    """
    results = {
        'customer_email': False,
        'admin_line': False
    }

    # Admin LINE notification
    admin_message = f"""
📧 新聯絡訊息

━━━━━━━━━━━━━━
姓名：{name}
Email：{email}
電話：{phone or '未提供'}
LINE：{line_id or '未提供'}

訊息內容：
{message}
━━━━━━━━━━━━━━

請盡快回覆客戶！
"""

    results['admin_line'] = send_line_notify(admin_message)

    # Confirmation email to customer
    customer_subject = '晶品芳療 - 已收到您的訊息'
    customer_body = f"""
親愛的 {name}，

感謝您的來信！

我們已收到您的訊息，將盡快回覆您。

您的訊息：
{message}

━━━━━━━━━━━━━━━━━━━━━━

如需緊急協助，歡迎透過以下方式聯絡：
• LINE：請搜尋「晶品芳療」
• 地址：新北市新莊區思源路296巷37號1樓
• 營業時間：週一至週日 09:00-18:00

晶品芳療團隊
    """

    customer_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #2c5aa0;">感謝您的來信！</h2>
            <p>親愛的 {name}，</p>
            <p>我們已收到您的訊息，將盡快回覆您。</p>
            
            <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <h4 style="margin-top: 0;">您的訊息：</h4>
                <p style="white-space: pre-wrap;">{message}</p>
            </div>
            
            <div style="background: #fff3cd; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <h4 style="margin-top: 0;">如需緊急協助</h4>
                <p>歡迎透過以下方式聯絡：</p>
                <ul>
                    <li>LINE：請搜尋「晶品芳療」</li>
                    <li>地址：新北市新莊區思源路296巷37號1樓</li>
                    <li>營業時間：週一至週日 09:00-18:00</li>
                </ul>
            </div>
            
            <p style="color: #666; font-size: 0.9em;">
                晶品芳療團隊<br>
                專業精進不止，感恩之心常存
            </p>
        </div>
    </body>
    </html>
    """

    results['customer_email'] = send_email(
        to=email,
        subject=customer_subject,
        body=customer_body,
        html=customer_html
    )

    return results


# ==========================================
# ORDER STATUS UPDATE NOTIFICATIONS
# ==========================================

def notify_order_status_update(order_id, customer_name, customer_email, status):
    """
    Send notification when order status changes

    Args:
        order_id (int): Order ID
        customer_name (str): Customer name
        customer_email (str): Customer email
        status (str): New order status

    Returns:
        bool: True if sent successfully
    """
    status_messages = {
        'confirmed': '已確認',
        'completed': '已完成',
        'cancelled': '已取消'
    }

    status_text = status_messages.get(status, status)

    subject = f'晶品芳療 - 訂單狀態更新 ({status_text})'
    body = f"""
親愛的 {customer_name}，

您的訂單狀態已更新！

訂單編號：#{order_id}
最新狀態：{status_text}

{"感謝您的訂購，歡迎再次光臨！" if status == 'completed' else ""}
{"如有任何問題，歡迎隨時與我們聯絡。" if status == 'cancelled' else ""}

晶品芳療團隊
    """

    return send_email(customer_email, subject, body)


# ==========================================
# BOOKING STATUS UPDATE NOTIFICATIONS
# ==========================================

def notify_booking_status_update(booking_id, customer_name, customer_email, course_name, status):
    """
    Send notification when booking status changes

    Args:
        booking_id (int): Booking ID
        customer_name (str): Customer name
        customer_email (str): Customer email
        course_name (str): Course name
        status (str): New booking status

    Returns:
        bool: True if sent successfully
    """
    status_messages = {
        'confirmed': '已確認',
        'completed': '已完成',
        'cancelled': '已取消'
    }

    status_text = status_messages.get(status, status)

    subject = f'晶品芳療 - 預約狀態更新 ({status_text})'
    body = f"""
親愛的 {customer_name}，

您的預約狀態已更新！

預約編號：#{booking_id}
課程名稱：{course_name}
最新狀態：{status_text}

{"感謝您的預約，期待下次再見！" if status == 'completed' else ""}
{"如有任何問題，歡迎隨時與我們聯絡。" if status == 'cancelled' else ""}

晶品芳療團隊
    """

    return send_email(customer_email, subject, body)

# ==========================================
# LINE MESSAGING API (給顧客)
# ==========================================


def send_customer_line_message(user_line_id, message_text):
    """
    使用 Messaging API 發送訊息給特定顧客
    需在 Config 加入 LINE_CHANNEL_ACCESS_TOKEN
    """
    channel_access_token = current_app.config.get('LINE_CHANNEL_ACCESS_TOKEN')

    if not channel_access_token or not user_line_id:
        return False

    line_bot_api = LineBotApi(channel_access_token)

    try:
        line_bot_api.push_message(
            user_line_id, TextSendMessage(text=message_text))
        return True
    except LineBotApiError as e:
        current_app.logger.error(f"LINE Messaging API failed: {e}")
        return False

# ==========================================
# 更新版預約通知 (整合行事曆資訊)
# ==========================================


def notify_new_booking_v2(booking_id, customer, course, schedule, total_amount):
    """
    發送預約通知 (Admin: LINE Notify / Email, Customer: LINE Messaging / Email)
    """

    # 1. 準備訊息內容
    booking_time_str = schedule['start_time'].strftime('%Y-%m-%d %H:%M')

    msg_content = f"""
【預約確認】
親愛的 {customer['firstname']}，您已成功預約！

單號：#{booking_id}
課程：{course['name']}
時間：{booking_time_str}
金額：NT$ {total_amount:,.0f}

請準時蒞臨，如需更改請提前告知。
"""

    # 2. 寄送 Email 給顧客
    send_email(
        to=customer['email'],
        subject=f"預約成功通知 - {booking_time_str}",
        body=msg_content
    )

    # 3. 寄送 LINE 給顧客 (前提是 user.line_id 是有效的 User ID)
    if customer.get('line_id'):
        send_customer_line_message(customer['line_id'], msg_content)

    # 4. 通知管理員 (使用原本的 LINE Notify)
    # 這裡可以沿用您原本 notifications.py 的 send_line_notify 函式
    from .notifications import send_line_notify

    admin_msg = f"""
📅 新增預約通知
客戶：{customer['firstname']} {customer['surname']}
課程：{course['name']}
時間：{booking_time_str}
"""
    send_line_notify(admin_msg)

    # 5. 通知管理員 Email (可選)
    admin_email = current_app.config.get('MAIL_USERNAME')  # 或其他設定的管理員信箱
    if admin_email:
        send_email(to=admin_email, subject="新預約通知", body=admin_msg)
