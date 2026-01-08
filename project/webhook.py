import os
import logging
from flask import Blueprint, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, JoinEvent

# 設定 Log (比 print 更穩定)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

webhook_bp = Blueprint('webhook', __name__)

# ==========================================
# Webhook 入口 (支援瀏覽器測試)
# ==========================================


@webhook_bp.route("/callback", methods=['POST', 'GET'])  # ⭐ 重點：新增 GET 方法
def callback():
    # 1. 直接抓環境變數
    secret = os.environ.get('LINE_BOT_CHANNEL_SECRET')

    # ⭐ 2. 瀏覽器測試模式 (GET)
    if request.method == 'GET':
        if not secret:
            return "❌ 錯誤：Server 抓不到 LINE_BOT_CHANNEL_SECRET", 200

        # 直接印在網頁上給你看
        return f"""
        <h1>Status: Online ✅</h1>
        <p>您的 LINE_BOT_CHANNEL_SECRET 前五碼是: <strong>[{secret[:5]}]</strong></p>
        <p>請將這五碼與 LINE Developers 後台的 Channel Secret 比對。</p>
        <p>如果不同，請去 Railway Variables 修正。</p>
        """, 200

    # ==========================================
    # 以下是原本的 POST 邏輯 (給 LINE 用的)
    # ==========================================

    # 3. 檢查變數
    if not secret:
        logger.error("LINE_BOT_CHANNEL_SECRET is missing")
        return 'Config Missing', 500

    # 4. 初始化 Handler
    try:
        handler = WebhookHandler(secret)
    except Exception as e:
        logger.error(f"Handler init failed: {e}")
        return 'Handler Error', 500

    # 5. 取得簽章與 Body
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    # 寫入 Log
    logger.info(
        f"Received webhook. Signature: {signature[:10]}... Secret Prefix: {secret[:5]}")

    # 6. 驗證
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.error("Invalid Signature - Secret mismatch!")
        abort(400)

    return 'OK'


# ==========================================
# 事件處理
# ==========================================
_g_secret = os.environ.get('LINE_BOT_CHANNEL_SECRET')
if _g_secret:
    handler = WebhookHandler(_g_secret)

    @handler.add(JoinEvent)
    def handle_join(event):
        group_id = event.source.group_id
        try:
            _token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
            if _token:
                api = LineBotApi(_token)
                api.reply_message(event.reply_token, TextSendMessage(
                    text=f"群組 ID：\n{group_id}"))
        except:
            pass
