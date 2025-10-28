import uvicorn
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
# (移除) sqlalchemy imports for func, desc, null
from collections import defaultdict # 導入 defaultdict for grouping
from datetime import datetime # 導入 datetime for validation

import requests

import database
from database import SessionLocal, Invoice
import datetime_parser
import shutil
import os
import re
import platform
import cv2
from pyzbar.pyzbar import decode
import pytesseract
import pdfplumber

# --- (重要) 貼上您的 API KEY ---
EXCHANGE_RATE_API_KEY = "YOUR_API_KEY" # <--- 請確保您的 Key 在這裡
# ------------------------------------

database.create_db_and_tables()

if platform.system() == 'Windows':
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

app = FastAPI(title="專業發票 API (階段四：彙總最終除錯版)")

TEMP_DIR = "temp_files"
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_exchange_rate(base_currency: str):
    # ... (此函式內容不變，省略) ...
    if base_currency == "TWD":
        return 1.0, None
    if EXCHANGE_RATE_API_KEY == "YOUR_API_KEY":
        print("警告：未使用真實匯率 API Key，將使用預設匯率 1:32")
        if base_currency == "USD": return 32.0, None
        if base_currency == "EUR": return 35.0, None
        return 1.0, None
    try:
        url = f"https://v6.exchangerate-api.com/v6/{EXCHANGE_RATE_API_KEY}/latest/{base_currency.upper()}"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if data.get("result") == "success" and "TWD" in data.get("conversion_rates", {}):
            return data["conversion_rates"]["TWD"], None
        else:
            return None, "無法從 API 獲取 TWD 匯率"
    except requests.RequestException as e:
        return None, f"匯率 API 呼叫失敗: {str(e)}"


def read_pdf_invoice(file_path: str):
    # ... (此函式內容不變，省略) ...
    text = ""
    amount, currency, company_name, item_description, invoice_date = None, None, None, None, None
    number_match = None
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text(x_tolerance=1, y_tolerance=1) # (新) 提高擷取精度
                if page_text:
                    text += page_text.replace('"', '') + "\n" # 保留換行符

        # 清理多餘空格，但保留換行符用於區分段落
        text = re.sub(r'[ \t]+', ' ', text)

        # 1. 辨識號碼
        number_match = re.search(r'([A-Z]{2}\d{8})', text) # Adobe (TC39...) & 神通 (NX47...)
        if not number_match:
             number_match = re.search(r'Invoice #:\s*([A-Z0-9]+)', text) # OpenAI (TC59...)

        # 2. 辨識金額與幣別
        intl_match = re.search(r'(USD|EUR)\s*([\d,]+\.?\d*)', text) # OpenAI (USD 21.00)
        if intl_match:
            currency = intl_match.group(1)
            amount = intl_match.group(2).replace(',', '')
        else:
            twd_match = re.search(r'發票總金額\s*([\d,]+)', text) # Adobe
            if not twd_match:
                # (修改) 神通格式 (總計 1,309) - 更精確匹配
                twd_match = re.search(r'總計\s*([\d,]+)\s*賣方:', text)
            # ... (備用 TWD 格式保持不變) ...
            if not twd_match:
                twd_match = re.search(r'(?:總計|合計)\s*NT\$\s*([\d,]+)', text)
            if not twd_match:
                twd_match = re.search(r'(?:總計|合計)\s*([\d,]+)', text)
            if twd_match:
                currency = "TWD"
                amount = twd_match.group(1).replace(',', '')

        # 3. 辨識公司與品項 (使用更精確的 Regex)
        company_match = re.search(r'Provided by:\s*(OpenAL LLC)', text) # (修改) OpenAI - 精確匹配
        if company_match:
            company_name = company_match.group(1).strip()
            # (修改) OpenAI 品項 - 只抓 "X x Product Name"
            item_match = re.search(r'DESCRIPTION\s*QUANTITY\s*PRICE\s*TAX\s*TOTAL\s*(\d+\s*x\s*.*?)\s*\(at \$[\d\.]+/month\)', text, re.DOTALL | re.IGNORECASE)
            if item_match:
                item_description = item_match.group(1).strip()

        if not company_name:
            # (修改) Adobe - 精確匹配
            company_match = re.search(r'\d{8}\s*(Adobe Systems Software Ireland Limited)', text)
            if company_match:
                company_name = company_match.group(1).strip()
                # (修改) Adobe 品項 - 抓取特定格式
                item_match = re.search(r'品名\s*(.*?)\s*稅別', text, re.DOTALL)
                if item_match:
                    # 移除換行和多餘描述
                    item_desc_raw = item_match.group(1).strip().replace('\n',' ')
                    item_description = re.sub(r'\s*\d+\.\d+.*', '', item_desc_raw).strip()


        if not company_name:
            # (修改) 神通格式 - 處理換行
            company_match = re.search(r'賣方:\s*(.*?)\s*統一編號:', text, re.DOTALL)
            if company_match:
                company_name = re.sub(r'\s+', ' ', company_match.group(1).strip())

            # (修改) 神通格式 - 更精確匹配品項
            item_match = re.search(r'品名\s*數量\s*單價\s*金額\s*備註\s*1:(.*?)\s*銷售額合計', text, re.DOTALL)
            if item_match:
                item_description = re.sub(r'\s+', ' ', item_match.group(1).strip())

        if item_description:
            item_description = re.sub(r'\s+', ' ', item_description).strip() # 最終清理

        # 4. 辨識日期 (優先尋找 YYYY/MM/DD 或 YYYY-MM-DD)
        date_match = re.search(r'(\d{4}[/-]\d{2}[/-]\d{2})', text)
        if date_match:
            invoice_date = date_match.group(1).replace('/', '-')

        if not invoice_date:
            date_match = re.search(r'Invoice date:\s*([\d/]+)', text)
            if date_match:
                invoice_date = date_match.group(1)

        return {
            "type": "Online (PDF)",
            "invoice_number": number_match.group(1) if number_match else None,
            "total_amount": amount,
            "currency": currency,
            "company_name": company_name,
            "item_description": item_description,
            "invoice_date_raw": invoice_date
        }
    except Exception as e:
        print(f"PDF Parsing Error: {e}")
        return {"error": str(e)}

def read_image_invoice(file_path: str):
    # ... (此函式內容不變，省略) ...
    try:
        img = cv2.imread(file_path)
        if img is None: return {"error": "無法讀取圖片"}

        qrs = decode(img)
        if qrs:
            for qr in qrs:
                qr_data = qr.data.decode('utf-8')
                if len(qr_data) > 70 and re.match(r'^[A-Z]{2}\d{8}', qr_data):
                    return {
                        "type": "Electronic (QR Code)",
                        "invoice_number": qr_data[0:10],
                        "invoice_date_raw": qr_data[10:17], # (修改)
                        "total_amount": str(int(qr_data[21:29], 16)),
                        "currency": "TWD",
                        "company_name": None,
                        "item_description": "N/A (QR Code不支援品項)"
                    }

        text = pytesseract.image_to_string(img, lang='chi_tra+eng')
        number_match = re.search(r'([A-Z]{2}-\d{8})', text)
        amount_match = re.search(r'(?:總\s*計|合\s*計)\s*([\d,]+)', text)
        company_name_ocr = text.split('\n')[0].strip()

        return {
            "type": "Traditional (OCR)",
            "invoice_number": number_match.group(1) if number_match else None,
            "total_amount": amount_match.group(1).replace(',', '') if amount_match else None,
            "currency": "TWD",
            "company_name": company_name_ocr,
            "item_description": "N/A (OCR未支援品項)",
            "invoice_date_raw": None # (修改)
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/invoices")
async def get_all_invoices(db: Session = Depends(get_db)):
    invoices = db.query(Invoice).all()
    return invoices

# --- (修改) 階段四 API 端點：GET /summary (增強錯誤捕捉) ---
@app.get("/summary")
async def get_monthly_summary(db: Session = Depends(get_db)):
    """
    獲取所有發票，在 Python 中按月彙總 TWD 金額。
    """
    monthly_totals = defaultdict(float)
    total_all_time = 0.0
    processed_count = 0 # (新) 記錄處理了多少筆

    try:
        all_invoices = db.query(Invoice).all()

        for invoice in all_invoices:
            processed_count += 1 # (新)
            # --- (新) 在迴圈內部加入 try-except ---
            try:
                # 驗證日期格式 YYYY-MM-DD
                if invoice.invoice_date_iso and isinstance(invoice.invoice_date_iso, str) and re.match(r'^\d{4}-\d{2}-\d{2}$', invoice.invoice_date_iso):
                    # 嘗試解析日期以確保有效性
                    datetime.strptime(invoice.invoice_date_iso, '%Y-%m-%d')
                    month_key = invoice.invoice_date_iso[:7] # 提取 "YYYY-MM"
                    if invoice.total_amount_twd is not None and isinstance(invoice.total_amount_twd, (int, float)):
                        monthly_totals[month_key] += invoice.total_amount_twd
                    else:
                         print(f"警告：發票 {invoice.invoice_number} 的 TWD 金額無效: {invoice.total_amount_twd}")

                # 累加總金額 (即使日期無效也要加總)
                if invoice.total_amount_twd is not None and isinstance(invoice.total_amount_twd, (int, float)):
                    total_all_time += invoice.total_amount_twd
                else:
                    print(f"警告：發票 {invoice.invoice_number} 的 TWD 金額無效，無法計入總額: {invoice.total_amount_twd}")

            except Exception as loop_error:
                # (新) 如果單筆發票處理失敗，印出錯誤並跳過
                print("="*30)
                print(f"!!! ERROR PROCESSING INVOICE ID: {invoice.id}, NUMBER: {invoice.invoice_number} !!!")
                print(f"Date ISO: {invoice.invoice_date_iso}, Amount TWD: {invoice.total_amount_twd}")
                import traceback
                traceback.print_exc()
                print("SKIPPING THIS INVOICE FOR SUMMARY...")
                print("="*30)
                continue # 繼續處理下一筆
            # --- (新) try-except 結束 ---

        # 轉換為 API 需要的格式 [{month: "YYYY-MM", total_twd: X.XX}, ...]
        summary_list = [{"month": month, "total_twd": total} for month, total in monthly_totals.items()]
        # 按月份倒序排序
        summary_list.sort(key=lambda x: x['month'], reverse=True)

        return {
            "monthly": summary_list,
            "total_all_time": total_all_time,
            "processed_count": processed_count, # (新) 回報處理了幾筆
            "db_total_count": len(all_invoices) # (新) 回報資料庫總筆數
        }
    except Exception as e:
         # (修改) 如果是獲取 all_invoices 失敗或其他非預期錯誤
        print("="*30)
        print("!!! UNEXPECTED ERROR in /summary calculation !!!")
        import traceback
        traceback.print_exc()
        print("="*30)
        raise HTTPException(status_code=500, detail=f"Python 彙總計算失敗: {str(e)}")


@app.post("/process-invoice")
async def process_invoice(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # ... (此函式內容不變，省略) ...
    file_path = os.path.join(TEMP_DIR, file.filename)
    result_data = {}

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        content_type = file.content_type

        if content_type == 'application/pdf':
            result_data = read_pdf_invoice(file_path)
        elif content_type in ['image/jpeg', 'image/png', 'image/heic', 'image/webp']:
            result_data = read_image_invoice(file_path)
        else:
            raise HTTPException(status_code=400, detail="不支援的檔案格式")

        if "error" in result_data or not result_data.get("invoice_number"):
            raise HTTPException(status_code=400, detail=f"辨識失敗: {result_data.get('error', '找不到發票號碼')}")

        invoice_num = result_data.get("invoice_number") # 先取出號碼

        original_amount_str = result_data.get("total_amount")
        original_currency = result_data.get("currency")

        if not original_amount_str or not original_currency:
            raise HTTPException(status_code=400, detail="辨識失敗: 找不到金額或幣別")

        rate, error = get_exchange_rate(original_currency)
        if error:
            raise HTTPException(status_code=503, detail=f"匯率服務失敗: {error}")

        try:
            original_amount_float = float(original_amount_str)
            twd_amount_float = original_amount_float * rate
        except ValueError:
            raise HTTPException(status_code=400, detail=f"辨識失敗: 金額格式錯誤 ({original_amount_str})")

        raw_date = result_data.get("invoice_date_raw")
        iso_date = datetime_parser.normalize_date_to_iso(raw_date)
        if not iso_date:
            print(f"警告：無法正規化日期 '{raw_date}'，將存為 None")

        try:
            existing_invoice = db.query(Invoice).filter(Invoice.invoice_number == invoice_num).first()

            if existing_invoice:
                print(f"更新已存在的發票: {invoice_num}")
                existing_invoice.type = result_data.get("type")
                existing_invoice.total_amount = original_amount_str
                existing_invoice.invoice_date_iso = iso_date
                existing_invoice.currency = original_currency
                existing_invoice.total_amount_twd = twd_amount_float
                existing_invoice.exchange_rate_used = rate
                existing_invoice.company_name = result_data.get("company_name")
                existing_invoice.item_description = result_data.get("item_description")
                db_invoice = existing_invoice
            else:
                print(f"新增發票: {invoice_num}")
                new_invoice = Invoice(
                    type = result_data.get("type"),
                    invoice_number = invoice_num,
                    total_amount = original_amount_str,
                    invoice_date_iso = iso_date,
                    currency = original_currency,
                    total_amount_twd = twd_amount_float,
                    exchange_rate_used = rate,
                    company_name = result_data.get("company_name"),
                    item_description = result_data.get("item_description")
                )
                db.add(new_invoice)
                db_invoice = new_invoice

            db.commit()
            db.refresh(db_invoice)

            return db_invoice

        except Exception as db_error:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"資料庫儲存失敗: {str(db_error)}")

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        print("="*30)
        print("!!! UNEXPECTED ERROR in /process-invoice !!!")
        import traceback
        traceback.print_exc()
        print("="*30)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    print("啟動伺服器，請用瀏覽器開啟 http://127.0.0.1:8000")
    print("若要讓手機連線，請改用 http://<您的電腦IP位址>:8000")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)