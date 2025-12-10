# 1. 使用 Python 3.13 作為基底
FROM python:3.13-slim

# 2. 安裝 Linux 系統層級的 MySQL 驅動程式 (這就是解決 libmariadb 的關鍵)
RUN apt-get update && apt-get install -y \
    pkg-config \
    default-libmysqlclient-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 3. 設定工作目錄
WORKDIR /app

# 4. 複製所有檔案進去
COPY . .

# 5. 安裝 Python 套件 (讀取您改名後的 requirements_lock.txt)
RUN pip install --no-cache-dir -r requirements_lock.txt

# 6. 設定啟動指令 (綁定 Railway 提供的 PORT)
CMD gunicorn run:app -b 0.0.0.0:$PORT