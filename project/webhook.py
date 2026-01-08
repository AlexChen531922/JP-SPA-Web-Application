import os
import json
from flask import Blueprint, request, abort
from linebot import LineBotApi
from linebot.models import TextSendMessage

webhook_bp = Blueprint('webhook', __name__)

# ==========================================
# Webhook 入口 (無驗證直通版)
# ==========================================


@webhook_bp.route("/callback", methods=['POST', 'GET'])
def callback():
    # 1. 瀏覽器測試
    if request.method == 'GET':
        return "System Online (Bypass Mode)", 200

    # 2. 準備工具
    token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
    if not token:
        print("❌ Token missing")
        return 'Token Missing', 500

    line_bot_api = LineBotApi(token)

    # 3. ⭐ 直接讀取內容 (不檢查簽章！)
    body = request.get_data(as_text=True)
    print(f"📩 收到訊息: {body}")  # 印出來確保有收到

    try:
        data = json.loads(body)
    except:
        return 'Invalid JSON', 200  # 就算格式錯也回傳 200 騙過 LINE

    # 4. 手動處理事件
    events = data.get('events', [])
    for event in events:
        try:
            # 偵測加入事件 (join)
            if event.get('type') == 'join':
                source = event.get('source', {})
                group_id = source.get('groupId')
                reply_token = event.get('replyToken')

                print(f"🎉 抓到了！群組 ID: {group_id}")

                if group_id and reply_token:
                    line_bot_api.reply_message(
                        reply_token,
                        TextSendMessage(
                            text=f"成功取得 ID！\n群組 ID 是：\n{group_id}\n\n請趕快去設定 Railway 變數！")
                    )

            # 偵測文字訊息 (輸入 id)
            elif event.get('type') == 'message':
                msg_text = event.get('message', {}).get('text', '').strip()
                if msg_text.lower() == 'id':
                    source = event.get('source', {})
                    # 判斷是群組還是個人
                    target_id = source.get('groupId') or source.get('userId')
                    reply_token = event.get('replyToken')

                    if target_id and reply_token:
                        line_bot_api.reply_message(
                            reply_token,
                            TextSendMessage(text=f"目前的 ID 是：\n{target_id}")
                        )

        except Exception as e:
            print(f"❌ 處理事件失敗: {e}")

    # ⭐ 無論發生什麼事，永遠回傳 200 OK 讓 LINE 開心
    return 'OK', 200
