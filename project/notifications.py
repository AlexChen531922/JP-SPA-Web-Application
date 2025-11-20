"""
Notification System for 晶品芳療
Supports Email and LINE Notify
"""

from flask import current_app
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
import logging


# ==========================================
# EMAIL FUNCTIONS
# ==========================================

def send_email(to, subject, body, html=None):
    """
    Send email notification

    Args:
        to (str): Recipient email address
        subject (str): Email subject
        body (str): Plain text email body
        html (str, optional): HTML email body

    Returns:
        bool: True if sent successfully, False otherwise
    """
    try:
        # Get email config from Flask app
        mail_server = current_app.config.get('MAIL_SERVER')
        mail_port = current_app.config.get('MAIL_PORT')
        mail_username = current_app.config.get('MAIL_USERNAME')
        mail_password = current_app.config.get('MAIL_PASSWORD')
        mail_from = current_app.config.get('MAIL_DEFAULT_SENDER')

        # Check if email is configured
        if not all([mail_server, mail_username, mail_password]):
            current_app.logger.warning(
                "Email not configured, skipping email notification")
            return False

        # Create message
        msg = MIMEMultipart('alternative')
        msg['From'] = mail_from
        msg['To'] = to
        msg['Subject'] = subject

        # Attach plain text
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        # Attach HTML if provided
        if html:
            msg.attach(MIMEText(html, 'html', 'utf-8'))

        # Connect to SMTP server
        server = smtplib.SMTP(mail_server, mail_port)
        server.starttls()
        server.login(mail_username, mail_password)
        server.send_message(msg)
        server.quit()

        current_app.logger.info(f"Email sent successfully to {to}")
        return True

    except Exception as e:
        current_app.logger.error(f"Email sending failed to {to}: {e}")
        return False


# ==========================================
# LINE NOTIFY FUNCTIONS
# ==========================================

def send_line_notify(message):
    """
    Send LINE Notify message

    Args:
        message (str): Message to send

    Returns:
        bool: True if sent successfully, False otherwise
    """
    token = current_app.config.get('LINE_NOTIFY_TOKEN')

    if not token:
        current_app.logger.warning("LINE_NOTIFY_TOKEN not configured")
        return False

    url = 'https://notify-api.line.me/api/notify'
    headers = {'Authorization': f'Bearer {token}'}
    data = {'message': message}

    try:
        response = requests.post(url, headers=headers, data=data, timeout=10)
        if response.status_code == 200:
            current_app.logger.info("LINE Notify sent successfully")
            return True
        else:
            current_app.logger.error(
                f"LINE Notify failed: {response.status_code}")
            return False
    except Exception as e:
        current_app.logger.error(f"LINE Notify failed: {e}")
        return False


# ==========================================
# ORDER NOTIFICATIONS
# ==========================================

def notify_new_order(order_id, customer_name, customer_email, total_amount, items):
    """
    Send notifications for new order

    Args:
        order_id (int): Order ID
        customer_name (str): Customer name
        customer_email (str): Customer email
        total_amount (float): Order total amount
        items (str): Order items description

    Returns:
        dict: Status of notifications sent
    """
    results = {
        'customer_email': False,
        'admin_line': False
    }

    # Customer email
    customer_subject = '晶品芳療 - 訂單確認'
    customer_body = f"""
親愛的 {customer_name}，

感謝您的訂購！

━━━━━━━━━━━━━━━━━━━━━━
📦 訂單資訊
━━━━━━━━━━━━━━━━━━━━━━

訂單編號：#{order_id}
訂單金額：NT$ {total_amount:,.0f}

訂購項目：
{items}

━━━━━━━━━━━━━━━━━━━━━━
📌 接下來的步驟
━━━━━━━━━━━━━━━━━━━━━━

1. 我們將於 1-2 個工作天內確認您的訂單
2. 確認後會透過 Email 和 LINE 通知您
3. 您可於店內取貨並完成付款

如有任何問題，歡迎隨時與我們聯絡。

晶品芳療團隊
地址：新北市新莊區思源路195巷37號1樓
電話：請透過 LINE 聯繫
    """

    customer_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #2c5aa0;">感謝您的訂購！</h2>
            <p>親愛的 {customer_name}，</p>
            
            <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <h3 style="margin-top: 0;">📦 訂單資訊</h3>
                <p><strong>訂單編號：</strong>#{order_id}</p>
                <p><strong>訂單金額：</strong><span style="color: #28a745; font-size: 1.2em;">NT$ {total_amount:,.0f}</span></p>
                <div style="margin-top: 15px;">
                    <strong>訂購項目：</strong>
                    <pre style="background: white; padding: 10px; border-radius: 4px; white-space: pre-wrap;">{items}</pre>
                </div>
            </div>
            
            <div style="background: #e3f2fd; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <h4 style="margin-top: 0;">📌 接下來的步驟</h4>
                <ol>
                    <li>我們將於 1-2 個工作天內確認您的訂單</li>
                    <li>確認後會透過 Email 和 LINE 通知您</li>
                    <li>您可於店內取貨並完成付款</li>
                </ol>
            </div>
            
            <p style="color: #666; font-size: 0.9em;">
                如有任何問題，歡迎隨時與我們聯絡。<br>
                晶品芳療團隊<br>
                地址：新北市新莊區思源路195巷37號1樓
            </p>
        </div>
    </body>
    </html>
    """

    results['customer_email'] = send_email(
        to=customer_email,
        subject=customer_subject,
        body=customer_body,
        html=customer_html
    )

    # Admin LINE notification
    admin_message = f"""
🛍️ 新訂單通知

━━━━━━━━━━━━━━
訂單編號：#{order_id}
客戶：{customer_name}
金額：NT$ {total_amount:,.0f}

訂購項目：
{items}
━━━━━━━━━━━━━━

請盡快確認訂單！
"""

    results['admin_line'] = send_line_notify(admin_message)

    return results


# ==========================================
# BOOKING NOTIFICATIONS
# ==========================================

def notify_new_booking(booking_id, customer_name, customer_email, course_name,
                       sessions, total_amount, is_first_time):
    """
    Send notifications for new booking

    Args:
        booking_id (int): Booking ID
        customer_name (str): Customer name
        customer_email (str): Customer email
        course_name (str): Course name
        sessions (int): Number of sessions
        total_amount (float): Booking total amount
        is_first_time (bool): Is first time booking

    Returns:
        dict: Status of notifications sent
    """
    results = {
        'customer_email': False,
        'admin_line': False
    }

    # Prepare experience text
    experience_text = " 🎁 (首次體驗價)" if is_first_time else ""

    # Customer email
    customer_subject = '晶品芳療 - 課程預約確認'
    customer_body = f"""
親愛的 {customer_name}，

感謝您預約我們的課程！

━━━━━━━━━━━━━━━━━━━━━━
📅 預約資訊
━━━━━━━━━━━━━━━━━━━━━━

預約編號：#{booking_id}
課程名稱：{course_name}{experience_text}
預約堂數：{sessions} 堂
預約金額：NT$ {total_amount:,.0f}

━━━━━━━━━━━━━━━━━━━━━━
📌 接下來的步驟
━━━━━━━━━━━━━━━━━━━━━━

1. 我們將於 1-2 個工作天內與您聯絡確認預約時間
2. 確認後會透過 Email 和 LINE 通知您
3. 請於預約時間準時到店，課程完成後付款
4. 您可隨時在會員中心查看剩餘課程堂數

期待與您見面！

晶品芳療團隊
地址：新北市新莊區思源路195巷37號1樓
電話：請透過 LINE 聯繫
    """

    customer_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #2c5aa0;">感謝您的預約！</h2>
            <p>親愛的 {customer_name}，</p>
            
            <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <h3 style="margin-top: 0;">📅 預約資訊</h3>
                <p><strong>預約編號：</strong>#{booking_id}</p>
                <p><strong>課程名稱：</strong>{course_name}{experience_text}</p>
                <p><strong>預約堂數：</strong>{sessions} 堂</p>
                <p><strong>預約金額：</strong><span style="color: #28a745; font-size: 1.2em;">NT$ {total_amount:,.0f}</span></p>
                {"<p style='background: #d4edda; padding: 10px; border-radius: 4px; color: #155724;'>🎁 您享有首次體驗優惠！</p>" if is_first_time else ""}
            </div>
            
            <div style="background: #e3f2fd; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <h4 style="margin-top: 0;">📌 接下來的步驟</h4>
                <ol>
                    <li>我們將於 1-2 個工作天內與您聯絡確認預約時間</li>
                    <li>確認後會透過 Email 和 LINE 通知您</li>
                    <li>請於預約時間準時到店，課程完成後付款</li>
                    <li>您可隨時在會員中心查看剩餘課程堂數</li>
                </ol>
            </div>
            
            <p style="color: #666; font-size: 0.9em;">
                期待與您見面！<br>
                晶品芳療團隊<br>
                地址：新北市新莊區思源路195巷37號1樓
            </p>
        </div>
    </body>
    </html>
    """

    results['customer_email'] = send_email(
        to=customer_email,
        subject=customer_subject,
        body=customer_body,
        html=customer_html
    )

    # Admin LINE notification
    admin_message = f"""
📅 新課程預約

━━━━━━━━━━━━━━
預約編號：#{booking_id}
客戶：{customer_name}
課程：{course_name}{experience_text}
堂數：{sessions} 堂
金額：NT$ {total_amount:,.0f}
━━━━━━━━━━━━━━

請盡快聯絡客戶確認時間！
"""

    results['admin_line'] = send_line_notify(admin_message)

    return results


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
• 地址：新北市新莊區思源路195巷37號1樓
• 營業時間：週一至週日 10:00-21:00

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
                    <li>地址：新北市新莊區思源路195巷37號1樓</li>
                    <li>營業時間：週一至週日 10:00-21:00</li>
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
