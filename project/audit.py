from flask import request, session
from .extensions import database
import json


def log_activity(action, target_type, target_id, details=None):
    """
    記錄使用者操作
    """
    try:
        user = session.get('user')
        if not user:
            return

        user_id = user.get('user_id')
        ip_address = request.remote_addr

        # 如果 details 是字典，轉成 JSON 字串
        if isinstance(details, dict):
            details = json.dumps(details, ensure_ascii=False)

        cursor = database.connection.cursor()
        cursor.execute("""
            INSERT INTO audit_logs (user_id, action, target_type, target_id, details, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user_id, action, target_type, target_id, details, ip_address))

        database.connection.commit()
        cursor.close()
    except Exception as e:
        print(f"Audit log failed: {e}")
