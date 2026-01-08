import os
import sys
import hmac
import hashlib
import base64
from flask import Blueprint, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import JoinEvent, TextSendMessage, MessageEvent, TextMessage

webhook_bp = Blueprint('webhook', __name__)


@webhook_bp.route("/callback", methods=['POST', 'GET'])
def callback():
    # 1. 抓取變數
    secret = os.environ.get('LINE_BOT_CHANNEL_SECRET')

    # 2. 瀏覽器測試 (保持不變)
    if request.method == 'GET':
        if not secret:
            return "Server config error", 200
        return f"<h1>Debug Mode</h1><p>Secret Check: {secret[:5]}... (Len: {len(secret)})</p>", 200

    if not secret:
        print("❌ Error: Secret is missing")
        return 'Config Missing', 500

    # 3. 取得原始資料
    # 使用 get_data() 取得原始 bytes，避免任何編碼轉換導致的差異
    body_bytes = request.get_data()
    body_text = body_bytes.decode('utf-8')
    signature = request.headers.get('X-Line-Signature', '')

    # 4. ⭐ 手動計算簽章 (不透過 SDK)
    # 演算法：HMAC-SHA256(Secret, Body) -> Base64
    try:
        hash_val = hmac.new(secret.encode('utf-8'),
                            body_bytes, hashlib.sha256).digest()
        calculated_signature = base64.b64encode(hash_val).decode('utf-8')
    except Exception as e:
        print(f"❌ 計算簽章時發生錯誤: {e}")
        abort(500)

    # 5. 比對與除錯
    print("------------------------------------------------")
    print(f"🔑 使用的 Secret: [{secret[:5]}...]")
    print(f"📩 收到 LINE 簽章: [{signature}]")
    print(f"🧮 算出 正確 簽章: [{calculated_signature}]")

    if signature == calculated_signature:
        print("✅ 簽章完全符合！(手動驗證成功)")
    else:
        print("❌ 簽章不符！(這是為什麼報 400 的原因)")
        print("   -> 請確認 LINE 後台是否曾按過 'Issue' 或 'Regenerate' 按鈕？")
        print("   -> 請嘗試重新整理 LINE Developers 頁面。")
        abort(400)  # 這裡會觸發錯誤

    # 6. 如果簽章對了，才交給 Handler 處理
    handler = WebhookHandler(secret)
    try:
        handler.handle(body_text, signature)
    except Exception as e:
        print(f"Handler error: {e}")

    return 'OK'


# 事件處理 (保持不變)
_g_secret = os.environ.get('LINE_BOT_CHANNEL_SECRET')
if _g_secret:
    handler = WebhookHandler(_g_secret)

    @handler.add(JoinEvent)
    def handle_join(event):
        try:
            # 簡化版：直接嘗試回覆，不做複雜邏輯
            token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
            if token:
                api = LineBotApi(token)
                group_id = event.source.group_id
                print(f"🎉 成功取得群組 ID: {group_id}")
                api.reply_message(event.reply_token, TextSendMessage(
                    text=f"群組 ID:\n{group_id}"))
        except Exception as e:
            print(f"Reply Error: {e}")
