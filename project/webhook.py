import os
from flask import Blueprint, request, current_app, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, JoinEvent

# 建立 Blueprint
webhook_bp = Blueprint('webhook', __name__)

# 全域變數
line_bot_api = None
handler = None


def init_line_bot():
    """
    延遲初始化：確保在 Flask Context 中讀取 Config
    """
    global line_bot_api, handler
    if line_bot_api is None:
        token = current_app.config.get('LINE_CHANNEL_ACCESS_TOKEN')
        secret = current_app.config.get('LINE_BOT_CHANNEL_SECRET')
        if token and secret:
            line_bot_api = LineBotApi(token)
            handler = WebhookHandler(secret)

# ==========================================
# Webhook 入口 (LINE 伺服器會呼叫這裡)
# ==========================================


@webhook_bp.route("/callback", methods=['POST'])
def callback():
    init_line_bot()  # 確保有讀到設定

    if not handler:
        print("❌ LINE Config Missing in Webhook")
        return 'Config Missing', 500

    # 1. 取得簽章與 Body
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    # 2. 處理事件
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("❌ Invalid Signature")
        abort(400)

    return 'OK'

# ==========================================
# 事件處理邏輯 (這段就是您需要的！)
# ==========================================

# 為了讓裝飾器 @handler.add 運作，我們需要一個「暫時」的 handler 實例
# 但因為 handler 是在 callback 內動態初始化的，這裡使用一點小技巧：
# 我們直接讀取環境變數來建立模組層級的 handler，專門給裝飾器用。


_temp_secret = os.environ.get('LINE_BOT_CHANNEL_SECRET')
if _temp_secret:
    handler = WebhookHandler(_temp_secret)

    # ⭐ 當機器人加入群組時
    @handler.add(JoinEvent)
    def handle_join(event):
        # 1. 取得群組 ID
        group_id = event.source.group_id
        print(f"========= 您的群組 ID 是: {group_id} =========")

        # 2. 嘗試回覆群組 (需要重新初始化 api)
        try:
            token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
            if token:
                api = LineBotApi(token)
                api.reply_message(
                    event.reply_token,
                    TextSendMessage(
                        text=f"大家好！\n這個群組的 ID 是：\n{group_id}\n\n請管理員複製此 ID 並設定到系統中。")
                )
        except Exception as e:
            print(f"Reply failed: {e}")

    # (選用) 當收到文字訊息 "ID" 時，也回傳 ID
    @handler.add(MessageEvent, message=TextMessage)
    def handle_message(event):
        msg = event.message.text.strip()
        if msg.lower() == 'id':
            source_id = event.source.group_id if event.source.type == 'group' else event.source.user_id
            try:
                token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
                if token:
                    api = LineBotApi(token)
                    api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=f"目前的 ID 是：\n{source_id}")
                    )
            except Exception:
                pass
