# 1. 使用 Python 3.13
FROM python:3.13-slim

# 2. 設定工作目錄
WORKDIR /app

# 3. 安裝系統編譯工具 (這是現場編譯需要的)
RUN apt-get update && apt-get install -y \
    gcc \
    pkg-config \
    default-libmysqlclient-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 4. 先複製需求檔 (利用 Docker 快取層)
COPY requirements_lock.txt .

# 5. ⭐ 關鍵修改：強制重新安裝並編譯 mysqlclient/flask-mysqldb
# --no-binary :all: 表示不使用預編譯包，全部現場編譯
RUN pip install --no-cache-dir --no-binary :all: -r requirements_lock.txt

# 6. 複製剩餘程式碼
COPY . .

# 7. 啟動指令
CMD gunicorn run:app -b 0.0.0.0:$PORT