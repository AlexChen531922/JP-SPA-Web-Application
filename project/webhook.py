import os
from flask import Blueprint, request

webhook_bp = Blueprint('webhook', __name__)

# ==========================================
# Webhook 入口 (純 Log 紀錄版)
# ==========================================


@webhook_bp.route("/callback", methods=['POST', 'GET'])
def callback():
    # 1. 讓瀏覽器可以開啟，確認網站活著
    if request.method == 'GET':
        return "<h1>Server is Running!</h1><p>請將機器人加入群組，然後去 Railway 看 Log。</p>", 200

    # 2. 收到 LINE 的資料
    body = request.get_data(as_text=True)

    # 3. ⭐ 直接把整坨資料印出來！
    print("==========================================")
    print("🚀 [LINE 資料] 收到 Webhook 請求：")
    print(body)
    print("==========================================")

    # 4. 無條件回傳 OK，讓 LINE 開心
    return 'OK', 200
