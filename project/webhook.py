import os
import logging
from flask import Blueprint, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
# 引用 csrf 用來設定豁免，避免 400 錯誤
from project.extensions import csrf

webhook_bp = Blueprint('webhook', __name__)

# 設定日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 讀取變數 (正式版建議從環境變數讀取)
channel_secret = os.environ.get('LINE_BOT_CHANNEL_SECRET')
channel_access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')

# 初始化
handler = None
if channel_secret:
    handler = WebhookHandler(channel_secret)

line_bot_api = None
if channel_access_token:
    line_bot_api = LineBotApi(channel_access_token)

# ==========================================
# Webhook 入口 (正式版)
# ==========================================


@webhook_bp.route("/callback", methods=['POST'])
@csrf.exempt  # ⭐ 必備！豁免 CSRF 檢查，這是讓 LINE 通過的關鍵
def callback():
    # 1. 取得 Header 簽章
    signature = request.headers.get('X-Line-Signature', '')
    # 2. 取得 Body
    body = request.get_data(as_text=True)

    if not handler:
        logger.error("❌ LINE_BOT_CHANNEL_SECRET 未設定")
        abort(500)

    # 3. 安全驗證 (加回簽章檢查)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.warning("❌ 簽章驗證失敗 (Invalid Signature)")
        abort(400)

    return 'OK'


# ==========================================
# 事件處理
# ==========================================
if handler:
    # (選用) 保留一個簡單的回聲功能，確認機器人還活著
    # 如果您不希望機器人在群組回話，可以把這段刪除
    @handler.add(MessageEvent, message=TextMessage)
    def handle_message(event):
        msg = event.message.text.strip()
        # 輸入 "ID" 時回傳 ID (方便未來查詢)
        if msg.lower() == 'id':
            try:
                if line_bot_api:
                    target_id = event.source.group_id if event.source.type == 'group' else event.source.user_id
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=f"ID: {target_id}")
                    )
            except Exception as e:
                logger.error(f"Reply failed: {e}")
