# 使用官方 Python 映像 (slim 版本較小)
FROM python:3.11-slim

# 設定工作目錄
WORKDIR /app

# 設定環境變數，避免 Python 緩存 .pyc 檔案，並確保輸出立即顯示
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# 安裝系統依賴：Tesseract OCR 及其繁體中文語言包, PostgreSQL client, OpenCV libs
# 使用 --no-install-recommends 減少映像大小
# 清理 apt 快取以進一步減小大小
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-chi-tra \
    libpq-dev \
    # OpenCV 運行時需要的 libs
    libgl1 \
    libglib2.0-0 \
    # 其他潛在依賴 for OpenCV
    libsm6 \
    libxext6 \
    libxrender-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# 複製 requirements.txt 並安裝 Python 依賴
# 分開複製和安裝，利用 Docker build cache
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 複製整個專案目錄到容器中
COPY . .

# 確保 temp_files 目錄存在 (Render 會在 build 時執行)
# RUN mkdir -p /app/temp_files # 移除這行，因為 gunicorn 會在運行時創建

# 開放 Port (Render 會自動處理，但寫上是好習慣)
EXPOSE 8000

# 設定 Gunicorn 啟動命令
# Render 會自動設定 PORT 環境變數
# 使用 2 個 worker (-w 2)，您可以根據 Render 方案調整
# 使用 uvicorn worker 類別來運行 FastAPI
# 增加 --timeout 參數，給予 OCR/API 更多處理時間
# 增加 --log-level debug 提供更詳細日誌
# (修改) 移除 -b 0.0.0.0:$PORT，Gunicorn 預設監聽 0.0.0.0，Render 會處理 Port
CMD ["gunicorn", "main:app", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "--timeout", "120", "--log-level", "debug"]

