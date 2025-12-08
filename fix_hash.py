from hashlib import sha256

# 這就是您 auth.py 裡面的加密邏輯


def get_hash(password):
    return sha256(password.encode('utf-8')).hexdigest()


# 產生 alice 的密碼 hash
alice_hash = get_hash('Alice@123456')
print(f"Alice 的 Hash: {alice_hash}")

# 產生一段可以直接複製去 MySQL Workbench 執行的 SQL
print("\n--- 請複製以下這行去 MySQL Workbench 執行 ---")
print(
    f"UPDATE users SET password_hash = '{alice_hash}' WHERE username = 'alice';")
print("COMMIT;")
