from flask import request, session, current_app
from .extensions import database
import json


def log_activity(action, target_type, target_id, details=None):
    """
    記錄使用者操作 (Debug 版)
    """
    print(f"--- [DEBUG] 準備寫入 Log: {action} {target_type} #{target_id} ---")

    try:
        # 1. 檢查 Session
        user = session.get('user')
        print(f"--- [DEBUG] Session User: {user} ---")

        if not user:
            print("--- [ERROR] Session 中找不到 user，無法記錄 Log ---")
            return

        # ⭐ 關鍵：確認這裡的 key 是 'user_id' 還是 'id'？
        # 如果您的 auth.py 存的是 'id'，這裡就要改。
        user_id = user.get('user_id') or user.get('id')

        if not user_id:
            print("--- [ERROR] User 物件中找不到 ID ---")
            return

        ip_address = request.remote_addr

        if isinstance(details, dict):
            details = json.dumps(details, ensure_ascii=False)

        # 2. 檢查資料庫連線
        if not database.connection:
            print("--- [ERROR] 資料庫連線不存在 ---")
            return

        cursor = database.connection.cursor()
        cursor.execute("""
            INSERT INTO audit_logs (user_id, action, target_type, target_id, details, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user_id, action, target_type, target_id, details, ip_address))

        database.connection.commit()
        cursor.close()

        print("--- [SUCCESS] Log 寫入成功！ ---")

    except Exception as e:
        print(f"--- [FATAL ERROR] 寫入 Log 發生例外: {e} ---")
        import traceback
        traceback.print_exc()
