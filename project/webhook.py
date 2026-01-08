import os
import sys
import logging
from flask import Blueprint, request
# ⭐ 匯入 csrf 物件，這樣才能設定豁免
from project.extensions import csrf

webhook_bp = Blueprint('webhook', __name__)

# 設定標準 Log 格式
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# Webhook 入口 (CSRF 豁免版)
# ==========================================


@webhook_bp.route("/callback", methods=['POST', 'GET'])
@csrf.exempt  # ⭐⭐⭐ 關鍵！這行就是通行證，讓 Flask 不要擋 LINE
def callback():
    # 1. 瀏覽器測試 (GET)
    if request.method == 'GET':
        return "<h1>Server is Running! (CSRF Exempted)</h1><p>現在去邀請機器人，Log 一定會出來！</p>", 200

    # 2. 取得 LINE 資料
    body = request.get_data(as_text=True)

    # 3. ⭐ 強制寫入 Log (三種方法同時用，保證看得到)
    log_msg = f"\n🚀 [LINE DATA] 收到資料:\n{body}\n"

    # 方法 A: print 到 stdout 並強制刷新
    print(log_msg)
    sys.stdout.flush()

    # 方法 B: print 到 stderr (通常不會被緩衝)
    print(log_msg, file=sys.stderr)

    # 方法 C: 使用 logger
    logger.info(log_msg)

    # 4. 回傳 OK
    return 'OK', 200
