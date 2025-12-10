"""
Notification System for 晶品芳療
Updated: Uses LINE Messaging API for ALL notifications (Admin & Customer)
Replaces deprecated LINE Notify service.
"""

from flask import current_app
# ⭐ 必須安裝 line-bot-sdk: pip install line-bot-sdk
from linebot import LineBotApi
from linebot.models import TextSendMessage
from linebot.exceptions import LineBotApiError
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import url_for

# ==========================================
# 📧 EMAIL 基礎函式
# ==========================================


def send_email(to, subject, body, html=None):
    """發送 Email 的通用函式"""
    try:
        mail_server = current_app.config.get('MAIL_SERVER')
        mail_port = current_app.config.get('MAIL_PORT')
        mail_username = current_app.config.get('MAIL_USERNAME')
        mail_password = current_app.config.get('MAIL_PASSWORD')
        mail_from = current_app.config.get('MAIL_DEFAULT_SENDER')

        # 處理 tuple 格式的 sender (name, email)
        if isinstance(mail_from, tuple):
            mail_from = f"{mail_from[0]} <{mail_from[1]}>"

        if not all([mail_server, mail_username, mail_password]):
            current_app.logger.warning(
                "⚠️ Email config missing, skipping email.")
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
        current_app.logger.error(f"❌ Email failed: {e}")
        return False


# ==========================================
# 💬 LINE MESSAGING API 基礎函式 (核心整合)
# ==========================================

def send_line_push_message(user_id, message_text):
    """
    通用函式：使用 Messaging API 發送訊息給指定 User ID
    適用於：通知管理員、通知顧客
    """
    token = current_app.config.get('LINE_CHANNEL_ACCESS_TOKEN')

    if not token:
        current_app.logger.error("⚠️ LINE_CHANNEL_ACCESS_TOKEN not set")
        return False

    if not user_id:
        current_app.logger.warning("⚠️ Target LINE user_id is empty")
        return False

    try:
        line_bot_api = LineBotApi(token)
        # 發送純文字訊息
        line_bot_api.push_message(user_id, TextSendMessage(text=message_text))
        return True
    except LineBotApiError as e:
        current_app.logger.error(f"❌ LINE API Error: {e}")
        return False
    except Exception as e:
        current_app.logger.error(f"❌ LINE Push failed: {e}")
        return False


def send_admin_line_alert(message):
    """
    專門發送給管理員 (取代舊版 LINE Notify)
    需在 .env 設定 LINE_ADMIN_USER_ID
    """
    admin_user_id = current_app.config.get('LINE_ADMIN_USER_ID')

    if not admin_user_id:
        current_app.logger.warning("⚠️ LINE_ADMIN_USER_ID not configured")
        return False

    # 加上前綴以區分是系統通知
    formatted_msg = f"🔔 【後台通知】\n{message}"

    return send_line_push_message(admin_user_id, formatted_msg)


def send_customer_line_message(user_line_id, message_text):
    """發送給客戶 (維持介面名稱，底層呼叫通用函式)"""
    return send_line_push_message(user_line_id, message_text)


# ==========================================
# 🔄 整合通知流程 (同時發 Email & LINE)
# ==========================================

def notify_new_order_created(order_id, customer_name, customer_email, total_amount, items_text):
    """新訂單成立"""
    # 1. 通知管理員 (LINE)
    admin_msg = f"🛍️ [新訂單] #{order_id}\n客戶：{customer_name}\n金額：NT$ {total_amount:,.0f}\n\n請至後台確認。"
    send_admin_line_alert(admin_msg)

    # 2. 通知客戶 (Email)
    if customer_email:
        subject = '晶品芳療 - 訂單申請已收到'
        body = f"""親愛的 {customer_name}，\n\n感謝您的訂購！您的訂單 #{order_id} 申請已收到。\n\n訂購內容：\n{items_text}\n\n總金額：NT$ {total_amount:,.0f}\n\n我們將盡快確認訂單。"""
        send_email(customer_email, subject, body)


def notify_new_booking_created(booking_id, customer_name, customer_email, course_name, time_str):
    """新預約成立"""
    # 1. 通知管理員 (LINE)
    admin_msg = f"📅 [新預約] #{booking_id}\n客戶：{customer_name}\n課程：{course_name}\n時段：{time_str}"
    send_admin_line_alert(admin_msg)

    # 2. 通知客戶 (Email)
    if customer_email:
        subject = '晶品芳療 - 預約申請已收到'
        body = f"""親愛的 {customer_name}，\n\n我們已收到您的預約申請。\n課程：{course_name}\n時段：{time_str}\n\n我們將盡快確認時段。"""
        send_email(customer_email, subject, body)


def notify_order_confirmed(order_id, customer, total_amount):
    """訂單確認 (通知取貨)"""
    msg = f"✅ 訂單 #{order_id} 已確認！\n金額：NT$ {total_amount:,.0f}\n請您於營業時間前往店內付款取貨，謝謝！"

    # LINE 通知客戶
    if customer.get('line_id'):
        send_customer_line_message(customer['line_id'], msg)

    # Email 通知客戶
    subject = f"晶品芳療 - 訂單 #{order_id} 確認通知"
    send_email(customer['email'], subject, msg)


def notify_booking_confirmed(booking_id, customer, course_name, time_str):
    """預約確認"""
    msg = f"✅ 預約 #{booking_id} 已確認！\n課程：{course_name}\n時間：{time_str}\n\n我們已為您保留時段，請準時蒞臨。"

    # LINE 通知客戶
    if customer.get('line_id'):
        send_customer_line_message(customer['line_id'], msg)

    # Email 通知客戶
    subject = f"晶品芳療 - 預約 #{booking_id} 確認通知"
    send_email(customer['email'], subject, msg)


def notify_contact_message(name, email, phone, line_id, message):
    """聯絡表單通知"""
    # 通知管理員 (LINE)
    admin_msg = f"📧 [新聯絡訊息]\n姓名：{name}\nEmail：{email}\n電話：{phone}\n內容：{message}"
    send_admin_line_alert(admin_msg)

    # 自動回覆客戶 (Email)
    subject = '晶品芳療 - 已收到您的訊息'
    body = f"親愛的 {name}，我們已收到您的訊息，將盡快回覆。\n\n您的訊息：\n{message}"
    send_email(email, subject, body)
    return True


def notify_order_status_update(order_id, customer_name, customer_email, status):
    """訂單狀態變更 (Email)"""
    status_map = {'confirmed': '已確認', 'completed': '已完成', 'cancelled': '已取消'}
    status_text = status_map.get(status, status)

    subject = f'晶品芳療 - 訂單狀態更新 ({status_text})'
    body = f"親愛的 {customer_name}，訂單 #{order_id} 狀態已更新為：{status_text}。"
    return send_email(customer_email, subject, body)


def notify_booking_status_update(booking_id, customer_name, customer_email, course_name, status):
    """預約狀態變更 (Email)"""
    status_map = {'confirmed': '已確認', 'completed': '已完成', 'cancelled': '已取消'}
    status_text = status_map.get(status, status)

    subject = f'晶品芳療 - 預約狀態更新 ({status_text})'
    body = f"親愛的 {customer_name}，預約 #{booking_id} ({course_name}) 狀態已更新為：{status_text}。"
    return send_email(customer_email, subject, body)


def send_password_reset_email(to_email, token):
    """發送密碼重設信"""
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

    # 呼叫原本寫好的 send_email 函式
    return send_email(to_email, subject, body)
