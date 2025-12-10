import os
from project import create_app
from project.extensions import database
from werkzeug.security import generate_password_hash

# 初始化 Flask App 以取得資料庫連線
app = create_app()


def reset_user_password(username, new_password):
    # 產生符合新資安標準的加密 Hash
    new_hash = generate_password_hash(new_password)

    with app.app_context():
        cursor = database.connection.cursor()

        # 檢查用戶是否存在
        cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()

        if user:
            # 更新密碼
            cursor.execute("""
                UPDATE users 
                SET password_hash = %s 
                WHERE username = %s
            """, (new_hash, username))
            database.connection.commit()
            print(f"✅ [成功] 用戶 '{username}' 密碼已重設為: {new_password}")
        else:
            print(f"⚠️ [跳過] 找不到用戶 '{username}'")

        cursor.close()


if __name__ == "__main__":
    print("正在重設所有測試帳號密碼...\n")

    # --- 在這裡設定您要重置的帳號與新密碼 ---

    # 1. 管理員 (Admin)
    reset_user_password('admin', 'Admin@123456')

    # 2. 員工 (Staff)
    reset_user_password('staff', 'Staff@123456')

    # 3. 顧客 (Alice)
    reset_user_password('alice', 'Alice@123456')

    # 4. 顧客 (Bob)
    reset_user_password('bob', 'Bob@123456')

    print("\n完成！請使用新密碼登入。")
