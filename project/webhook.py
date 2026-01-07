import os
import sys
from flask import Blueprint, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, JoinEvent

# 建立 Blueprint
webhook_bp = Blueprint('webhook', __name__)

# ==========================================
# 初始化設定 (直接從環境變數讀取，避免重複初始化導致事件遺失)
# ==========================================

# 1. 讀取變數
channel_access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
channel_secret = os.environ.get('LINE_BOT_CHANNEL_SECRET')

# 2. 檢查變數是否存在
if not channel_access_token:
    print("❌ 錯誤：未設定 LINE_CHANNEL_ACCESS_TOKEN")
if not channel_secret:
    print("❌ 錯誤：未設定 LINE_BOT_CHANNEL_SECRET")

# 3. 建立 API 與 Handler 實例
# 這些必須在全域建立，讓下方的 @handler.add 可以正確綁定
line_bot_api = LineBotApi(
    channel_access_token) if channel_access_token else None
handler = WebhookHandler(channel_secret) if channel_secret else None


# ==========================================
# Webhook 入口
# ==========================================

@webhook_bp.route("/callback", methods=['POST'])
def callback():
    if not handler:
        print("❌ Handler 未初始化 (可能缺 Secret)")
        return 'Config Missing', 500

    # 1. 取得 Header 簽章
    signature = request.headers.get('X-Line-Signature', '')

    # 2. 取得 Body 內容
    body = request.get_data(as_text=True)

    # 3. 除錯訊息 (這會印在 Railway Log，幫助您確認變數是否正確)
    # 為了安全，只印出前 5 碼
    print(f"DEBUG: Received Body Length: {len(body)}")
    print(
        f"DEBUG: Using Secret: {channel_secret[:5]}..." if channel_secret else "DEBUG: No Secret")

    # 4. 驗證並處理事件
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        # 如果這裡報錯，代表 Railway 上的 LINE_BOT_CHANNEL_SECRET 填錯了
        print("❌ Invalid Signature: 簽章驗證失敗，請檢查 Channel Secret 是否正確")
        abort(400)

    return 'OK'


# ==========================================
# 事件處理邏輯 (取得 ID 專用)
# ==========================================

if handler:
    # 當機器人加入群組時
    @handler.add(JoinEvent)
    def handle_join(event):
        group_id = event.source.group_id
        print(f"========= 您的群組 ID 是: {group_id} =========")

        try:
            if line_bot_api:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(
                        text=f"大家好！\n這個群組的 ID 是：\n{group_id}\n\n請管理員複製此 ID 並設定到系統中。")
                )
        except Exception as e:
            print(f"Reply failed: {e}")

    # 當收到文字訊息 "ID" 時
    @handler.add(MessageEvent, message=TextMessage)
    def handle_message(event):
        msg = event.message.text.strip()
        if msg.lower() == 'id':
            source_id = event.source.group_id if event.source.type == 'group' else event.source.user_id
            try:
                if line_bot_api:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=f"目前的 ID 是：\n{source_id}")
                    )
            except Exception:
                pass
