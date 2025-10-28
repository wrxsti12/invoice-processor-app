import re
from datetime import datetime

def normalize_date_to_iso(date_str: str | None) -> str | None:
    """
    將多種格式的日期字串，正規化為 YYYY-MM-DD (ISO 8601) 格式。
    """
    if not date_str:
        return None

    date_str = date_str.strip()

    try:
        # 格式 1: YYYY-MM-DD (例如: 2025-06-13)
        if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
            # 已經是完美格式
            return date_str

        # 格式 2: YYYY/MM/DD (例如: 2025/10/14)
        if re.match(r'^\d{4}/\d{2}/\d{2}$', date_str):
            return date_str.replace('/', '-')

        # 格式 3: M/D/YY (例如: 9/14/25)
        if re.match(r'^\d{1,2}/\d{1,2}/\d{2}$', date_str):
            dt = datetime.strptime(date_str, '%m/%d/%y')
            return dt.strftime('%Y-%m-%d')
            
        # 格式 4: YYYMMDD (民國年, 來自 QR Code, 例如: 1141014)
        if re.match(r'^\d{7}$', date_str):
            roc_year = int(date_str[0:3])
            month = int(date_str[3:5])
            day = int(date_str[5:7])
            ad_year = roc_year + 1911
            # 格式化為 "YYYY-MM-DD"
            return f"{ad_year:04d}-{month:02d}-{day:02d}"

    except Exception as e:
        print(f"日期正規化失敗: {e}, 原始字串: {date_str}")
        return None # 轉換失敗

    # 如果所有格式都匹配失敗
    return None
