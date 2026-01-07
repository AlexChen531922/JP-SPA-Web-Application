import os
import sys
from flask import Blueprint, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, JoinEvent

webhook_bp = Blueprint('webhook', __name__)

# ==========================================
# Webhook 入口 (除錯專用版)
# ==========================================


@webhook_bp.route("/callback", methods=['POST'])
def callback():
    # 1. 直接抓環境變數 (繞過所有 Config 設定，確保抓到最原始的值)
    secret = os.environ.get('LINE_BOT_CHANNEL_SECRET')
    token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')

    # 2. 強制印出變數狀態 (請去 Railway App Logs 查看)
    print("------------------------------------------------")
    print("🔍 [DEBUG] Webhook 被呼叫了！開始檢查變數...")

    if not secret:
        print("❌ [ERROR] LINE_BOT_CHANNEL_SECRET 是空的！")
        return 'Config Missing', 500

    # ⭐ 關鍵：印出前 5 碼
    print(f"🔑 [DEBUG] 伺服器上的 Secret 前五碼: [{secret[:5]}]")
    print(f"📏 [DEBUG] Secret 總長度: {len(secret)}")

    # 3. 初始化 Handler
    try:
        handler = WebhookHandler(secret)
    except Exception as e:
        print(f"❌ [ERROR] Handler 初始化失敗: {e}")
        return 'Handler Error', 500

    # 4. 取得簽章
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    print(f"📝 [DEBUG] 收到簽章: {signature[:10]}...")

    # 5. 驗證
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("------------------------------------------------")
        print("❌ [CRITICAL] 簽章驗證失敗 (Invalid Signature)")
        print(f"⚠️ 請檢查 LINE 後台的 Channel Secret 是否為: [{secret[:5]}...]")
        print("------------------------------------------------")
        abort(400)

    return 'OK'


# ==========================================
# 事件處理 (ID 回覆)
# ==========================================

# 全域 Handler (為了讓裝飾器生效)
_g_secret = os.environ.get('LINE_BOT_CHANNEL_SECRET')
if _g_secret:
    handler = WebhookHandler(_g_secret)

    @handler.add(JoinEvent)
    def handle_join(event):
        group_id = event.source.group_id
        print(f"========= 您的群組 ID 是: {group_id} =========")
        try:
            _token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
            if _token:
                api = LineBotApi(_token)
                api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=f"群組 ID：\n{group_id}")
                )
        except:
            pass
