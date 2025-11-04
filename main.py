import uvicorn
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from collections import defaultdict
from datetime import datetime
from sqlalchemy import func, desc, nullslast # 導入 nullslast
import requests
import os
from dotenv import load_dotenv
import traceback # 用於打印更詳細的錯誤

import database
from database import SessionLocal, Invoice
import datetime_parser # 日期剖析器
import shutil
import re
import platform
import cv2
from pyzbar.pyzbar import decode
import pytesseract
import pdfplumber

load_dotenv() # 從 .env 載入

# --- 從環境變數讀取 API KEY ---
EXCHANGE_RATE_API_KEY = os.getenv("EXCHANGE_RATE_API_KEY", "ec45f233b18cc9fd1a31c2c8") # 使用您的 Key 作為預設
# -----------------------------

# 在 App 啟動時嘗試建立資料表
try:
    database.create_db_and_tables()
except Exception as e:
    print(f"資料庫初始化錯誤: {e}")

# Tesseract 路徑設定
try:
    if platform.system() == 'Windows':
        tess_path = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
        if os.path.exists(tess_path):
             pytesseract.pytesseract.tesseract_cmd = tess_path
        else:
             print("警告: 找不到 Windows Tesseract 路徑 C:\\Program Files\\Tesseract-OCR\\tesseract.exe")
    elif platform.system() == 'Linux':
         tess_path = '/usr/bin/tesseract'
         if os.path.exists(tess_path):
              pytesseract.pytesseract.tesseract_cmd = tess_path
         else:
              print("警告: Tesseract 未安裝或找不到路徑")
except Exception as e:
    print(f"設定 Tesseract 路徑時發生錯誤: {e}")


app = FastAPI(title="專業發票 API (本地模式)")

TEMP_DIR = "temp_files"
# 確保暫存目錄存在
os.makedirs(TEMP_DIR, exist_ok=True)

# --- Dependency ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Helper Functions ---
def get_exchange_rate(base_currency: str):
    if base_currency == "TWD":
        return 1.0, None
    
    current_api_key = EXCHANGE_RATE_API_KEY
    if not current_api_key or current_api_key in ["YOUR_API_KEY", "ec45f233b18cc9fd1a31c2c8"]:
        current_api_key = "ec45f233b18cc9fd1a31c2c8"
        if not current_api_key or current_api_key == "YOUR_API_KEY":
            print("警告：未設定或使用預設 ExchangeRate-API Key，將使用假匯率 1:32 / 1:35")
            if base_currency == "USD": return 32.0, None
            if base_currency == "EUR": return 35.0, None
            return 1.0, None
    else:
        pass
    
    print(f"使用 API Key: ...{current_api_key[-4:]}")
    try:
        url = f"https://v6.exchangerate-api.com/v6/{current_api_key}/latest/{base_currency.upper()}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("result") == "success" and "TWD" in data.get("conversion_rates", {}):
            return data["conversion_rates"]["TWD"], None
        else:
            error_type = data.get('error-type', '未知 API 錯誤')
            print(f"匯率 API 錯誤回應: {error_type}")
            return None, f"無法從 API 獲取 TWD 匯率 ({error_type})"

    except requests.Timeout:
        print("匯率 API 請求超時")
        return None, "匯率 API 請求超時"
    except requests.exceptions.HTTPError as e:
        print(f"匯率 API HTTP 錯誤: {e.response.status_code} {e.response.text}")
        return None, f"匯率 API HTTP 錯誤: {e.response.status_code}"
    except requests.RequestException as e:
        print(f"匯率 API 呼叫失敗: {e}")
        return None, f"匯率 API 連線失敗: {str(e)}"
    except Exception as e:
        print(f"處理匯率時發生未知錯誤: {e}")
        traceback.print_exc()
        return None, f"處理匯率時發生未知錯誤: {str(e)}"


def read_pdf_invoice(file_path: str):
    text = ""
    amount, currency, company_name, item_description, invoice_date = None, None, None, None, None
    number_match = None
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text(x_tolerance=3, y_tolerance=1)
                if page_text:
                    text += page_text.replace('"', '') + "\n"

        text_cleaned = re.sub(r'[ \t]+', ' ', text)

        # 1. 辨識號碼
        number_match = re.search(r'([A-Z]{2}\d{8})', text_cleaned)
        if not number_match:
             number_match = re.search(r'Invoice #:\s*([A-Z0-9]+)', text_cleaned)

        # 2. 辨識金額與幣別
        intl_match = re.search(r'(USD|EUR)\s*([\d,]+\.?\d*)', text_cleaned)
        if intl_match:
            currency = intl_match.group(1)
            amount = intl_match.group(2).replace(',', '')
        else:
            twd_match = re.search(r'發票總金額\s*([\d,]+)', text, re.DOTALL)
            if twd_match:
                amount = twd_match.group(1).replace(',', '')
                if re.search(r'幣別:TWD', text, re.IGNORECASE):
                    currency = "TWD"
                else:
                    currency = "TWD"
            else:
                twd_match_multiline = re.search(r'總計\s*([\d,]+)\s*賣方:', text, re.DOTALL)
                if twd_match_multiline:
                    amount = twd_match_multiline.group(1).replace(',', '')
                    currency = "TWD"
            
            if not amount: 
                twd_match = re.search(r'(?:總計|合計)\s*NT\$\s*([\d,]+)', text_cleaned)
                if not twd_match:
                    twd_match = re.search(r'(?:總計|合計)\s*([\d,]+)', text_cleaned)
                if twd_match:
                    amount = twd_match.group(1).replace(',', '')

            if amount and not currency:
                if re.search(r'幣別:TWD', text, re.IGNORECASE) or re.search(r'新臺幣', text):
                    currency = "TWD"

        # 3. 辨識公司與品項
        company_match = re.search(r'Provided by:\s*(OpenAL LLC)', text, re.IGNORECASE)
        if company_match:
            company_name = company_match.group(1).strip()
            item_match = re.search(r'DESCRIPTION\s*QUANTITY\s*PRICE\s*TAX\s*TOTAL\s*(\d+\s*x\s*.*?)\s*\(at \$[\d\.]+/month\)', text, re.DOTALL | re.IGNORECASE)
            if item_match:
                item_description = item_match.group(1).strip()

        if not company_name:
            company_match = re.search(r'\d{8}\s*(Adobe Systems Software Ireland Limited)', text)
            if company_match:
                company_name = company_match.group(1).strip()
                item_match = re.search(r'品名\s*(.*?)\s*稅別', text, re.DOTALL)
                if item_match:
                    item_desc_raw = item_match.group(1).strip().replace('\n',' ')
                    item_description = re.sub(r'\s*\d+\.\d+.*', '', item_desc_raw).strip()

        if not company_name:
            company_match = re.search(r'賣方:\s*(.*?)\s*統一編號:', text, re.DOTALL)
            if company_match:
                company_name = re.sub(r'\s+', ' ', company_match.group(1).strip())
            item_match = re.search(r'品名\s*數量\s*單價\s*金額\s*備註\s*1:(.*?)\s*銷售額合計', text_cleaned, re.DOTALL)
            if item_match:
                item_description = re.sub(r'\s+', ' ', item_match.group(1).strip())

        if item_description:
            item_description = re.sub(r'\s+', ' ', item_description).strip()

        # 4. 辨識日期
        date_match = re.search(r'(\d{4}[/-]\d{2}[/-]\d{2})', text_cleaned)
        if date_match:
            invoice_date = date_match.group(1).replace('/', '-')
        if not invoice_date:
            date_match = re.search(r'發票日期\s*,\s*(\d{4}/\d{2}/\d{2})', text_cleaned)
            if date_match:
                invoice_date = date_match.group(1)
        if not invoice_date:
            date_match = re.search(r'Invoice date:\s*([\d/]+)', text_cleaned)
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
        print(f"PDF Parsing Error for {file_path}: {e}")
        traceback.print_exc()
        return {"error": f"PDF 解析錯誤: {str(e)}"}


def read_image_invoice(file_path: str):
    """
    從圖片檔案中辨識發票 (優先 QR Code, 其次 OCR)
    """
    try:
        img = cv2.imread(file_path)
        if img is None: return {"error": "無法讀取圖片"}

        qrs = decode(img)
        if qrs:
            for qr in qrs:
                qr_data = qr.data.decode('utf-8')
                # 台灣電子發票 QR Code (左邊的) 資料長度通常大於 70
                if len(qr_data) > 70 and re.match(r'^[A-Z]{2}\d{8}', qr_data):
                    try:
                        # --- (關鍵修正) ---
                        # [21:29] 是銷售額 (未稅)
                        # [29:37] 才是總計 (含稅)
                        amount_int = int(qr_data[29:37], 16) # 抓取總計金額
                        # --- (修正結束) ---
                    except ValueError:
                        amount_int = None # Handle potential error
                    return {
                        "type": "Electronic (QR Code)",
                        "invoice_number": qr_data[0:10],
                        "invoice_date_raw": qr_data[10:17],
                        "total_amount": str(amount_int) if amount_int is not None else None,
                        "currency": "TWD",
                        "company_name": None,
                        "item_description": "N/A (QR Code不支援品項)"
                    }
        
        # (舊) OCR 備援 (保持不變)
        if not pytesseract.pytesseract.tesseract_cmd or not os.path.exists(pytesseract.pytesseract.tesseract_cmd):
             print("錯誤: Tesseract OCR 未配置或找不到路徑")
             return {"error": "Tesseract OCR 未配置"}
        
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
            "invoice_date_raw": None
        }
    except pytesseract.TesseractNotFoundError:
        print("錯誤: Tesseract 未安裝或未在 PATH 中")
        return {"error": "Tesseract OCR 未安裝或找不到"}
    except Exception as e:
        print(f"Image Parsing Error for {file_path}: {e}")
        traceback.print_exc()
        return {"error": f"圖片解析錯誤: {str(e)}"}

# --- API Endpoints ---
@app.get("/invoices")
async def get_all_invoices(db: Session = Depends(get_db)):
    try:
        invoices = db.query(Invoice).order_by(nullslast(desc(Invoice.invoice_date_iso))).all()
        return invoices
    except Exception as e:
        print(f"讀取發票列表失敗: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"讀取發票列表失敗: {str(e)}")

@app.get("/summary")
async def get_monthly_summary(db: Session = Depends(get_db)):
    # ... (此函式內容不變，省略) ...
    monthly_totals = defaultdict(float)
    total_all_time = 0.0
    processed_count = 0
    error_invoices = []

    try:
        all_invoices = db.query(Invoice).all()

        for invoice in all_invoices:
            processed_count += 1
            try:
                is_date_valid = False
                if invoice.invoice_date_iso and isinstance(invoice.invoice_date_iso, str) and re.match(r'^\d{4}-\d{2}-\d{2}$', invoice.invoice_date_iso):
                    try:
                        datetime.strptime(invoice.invoice_date_iso, '%Y-%m-%d')
                        is_date_valid = True
                    except ValueError:
                         print(f"警告：發票 {invoice.invoice_number} 日期字串 '{invoice.invoice_date_iso}' 無法解析為有效日期")

                is_amount_valid = invoice.total_amount_twd is not None and isinstance(invoice.total_amount_twd, (int, float))

                if is_date_valid and is_amount_valid:
                    month_key = invoice.invoice_date_iso[:7]
                    monthly_totals[month_key] += invoice.total_amount_twd
                elif not is_date_valid and is_amount_valid:
                     print(f"警告：發票 {invoice.invoice_number} 日期無效 ({invoice.invoice_date_iso})，無法計入月彙總")
                     error_invoices.append(f"{invoice.invoice_number} (日期無效)")
                elif not is_amount_valid:
                     print(f"警告：發票 {invoice.invoice_number} TWD 金額無效 ({invoice.total_amount_twd})，無法計入彙總")
                     error_invoices.append(f"{invoice.invoice_number} (金額無效)")

                if is_amount_valid:
                    total_all_time += invoice.total_amount_twd

            except Exception as loop_error:
                print("="*30)
                print(f"!!! ERROR PROCESSING INVOICE ID: {invoice.id} for summary !!!")
                traceback.print_exc()
                print("SKIPPING...")
                print("="*30)
                error_invoices.append(f"{invoice.invoice_number} (處理錯誤)")
                continue

        summary_list = [{"month": month, "total_twd": total} for month, total in monthly_totals.items()]
        summary_list.sort(key=lambda x: x['month'], reverse=True)

        return {
            "monthly": summary_list,
            "total_all_time": total_all_time,
            "processed_count": processed_count,
            "db_total_count": len(all_invoices),
            "summary_error_invoices": list(set(error_invoices))
        }
    except Exception as e:
        print("="*30)
        print("!!! UNEXPECTED ERROR in /summary calculation !!!")
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
        os.makedirs(TEMP_DIR, exist_ok=True)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        content_type = file.content_type

        if content_type == 'application/pdf':
            result_data = read_pdf_invoice(file_path)
        elif content_type in ['image/jpeg', 'image/png', 'image/heic', 'image/webp']:
            result_data = read_image_invoice(file_path)
        else:
            raise HTTPException(status_code=415, detail=f"不支援的檔案格式: {content_type}")

        if "error" in result_data:
             raise HTTPException(status_code=400, detail=f"辨識核心失敗: {result_data['error']}")
        if not result_data.get("invoice_number"):
            raise HTTPException(status_code=400, detail="辨識失敗: 找不到發票號碼")

        invoice_num = result_data.get("invoice_number")
        original_amount_str = result_data.get("total_amount")
        original_currency = result_data.get("currency")

        if not original_amount_str or not original_currency:
            missing = []
            if not original_amount_str: missing.append("金額")
            if not original_currency: missing.append("幣別")
            raise HTTPException(status_code=400, detail=f"辨識不完整: 找不到 {' 和 '.join(missing)}")

        rate, error = get_exchange_rate(original_currency)
        if error:
            raise HTTPException(status_code=503, detail=f"匯率服務失敗: {error}")

        try:
            original_amount_float = float(original_amount_str)
            twd_amount_float = original_amount_float * rate
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=400, detail=f"辨識失敗: 金額格式錯誤 '{original_amount_str}' ({e})")

        raw_date = result_data.get("invoice_date_raw")
        iso_date = datetime_parser.normalize_date_to_iso(raw_date)
        if not iso_date and raw_date:
            print(f"警告：無法正規化日期 '{raw_date}' (發票: {invoice_num})，將存為 None")

        try:
            existing_invoice = db.query(Invoice).filter(Invoice.invoice_number == invoice_num).first()
            invoice_data = {
                "type": result_data.get("type"),
                "total_amount": original_amount_str,
                "invoice_date_iso": iso_date,
                "currency": original_currency,
                "total_amount_twd": twd_amount_float,
                "exchange_rate_used": rate,
                "company_name": result_data.get("company_name"),
                "item_description": result_data.get("item_description")
            }

            if existing_invoice:
                print(f"更新已存在的發票: {invoice_num}")
                for key, value in invoice_data.items():
                    setattr(existing_invoice, key, value)
                db_invoice = existing_invoice
            else:
                print(f"新增發票: {invoice_num}")
                new_invoice = Invoice(invoice_number=invoice_num, **invoice_data)
                db.add(new_invoice)
                db_invoice = new_invoice

            db.commit()
            db.refresh(db_invoice)
            return db_invoice

        except Exception as db_error:
            db.rollback()
            print("="*30)
            print(f"!!! DATABASE SAVE FAILED for invoice {invoice_num} !!!")
            traceback.print_exc()
            print("="*30)
            raise HTTPException(status_code=500, detail=f"資料庫儲存失敗: {str(db_error)}")

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print("="*30)
        print("!!! UNEXPECTED ERROR in /process-invoice !!!")
        traceback.print_exc()
        print("="*30)
        raise HTTPException(status_code=500, detail=f"伺服器內部錯誤: {str(e)}")
    finally:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                print(f"已刪除暫存檔案: {file_path}")
            except OSError as e:
                print(f"刪除暫存檔案失敗 {file_path}: {e}")


@app.delete("/invoices")
async def delete_all_invoices(db: Session = Depends(get_db)):
    try:
        num_deleted = db.query(Invoice).delete()
        db.commit()
        return {"message": f"成功刪除 {num_deleted} 筆發票紀錄"}
    except Exception as e:
        db.rollback()
        print(f"刪除發票時發生錯誤: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"資料庫刪除失敗: {str(e)}")


# --- 掛載 Static ---
app.mount("/", StaticFiles(directory="static", html=True), name="static")


# --- (新) 加回本地啟動器 ---
if __name__ == "__main__":
    print("啟動本地開發伺服器...")
    print(f"API Key: ...{EXCHANGE_RATE_API_KEY[-4:] if EXCHANGE_RATE_API_KEY and len(EXCHANGE_RATE_API_KEY) > 4 else '未設定或過短'}")
    print(f"Database URL: {database.DATABASE_URL}")
    print("請用瀏覽器開啟 http://127.0.0.1:8000")
    print("若要讓手機連線，請改用 http://<您的電腦IP位址>:8000")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

