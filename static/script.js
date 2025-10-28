// --- 翻譯函式 (已更新) ---
function displayFormattedResult(data) {
    const keyMap = {
        "type": "發票類型",
        "invoice_number": "發票號碼",
        "company_name": "公司名稱", // (新)
        "item_description": "項目", // (新)
        "total_amount": "原始金額",
        "currency": "原始幣別",
        "total_amount_twd": "換算台幣",
        "exchange_rate_used": "當時匯率"
    };
    const valueMap = {
        "Online (PDF)": "線上 PDF 發票",
        "Electronic (QR Code)": "電子發票 (QR Code)",
        "Traditional (OCR)": "傳統紙本發票 (OCR)",
    };

    let output = "";
    // (新) 優先顯示 TWD 金額 和 公司/品項
    if (data.total_amount_twd) {
        output += `換算台幣: NT$ ${data.total_amount_twd.toFixed(2)}\n`;
    }
    if (data.company_name) {
        output += `公司名稱: ${data.company_name}\n`;
    }
    if (data.item_description) {
        output += `項目: ${data.item_description}\n`;
    }
    output += "--------------------------------\n"; // 分隔線
    
    for (const key in data) {
        // (修改) 隱藏更多我們已手動顯示的 key
        if (key === 'id' || key === 'status' || 
            key === 'total_amount_twd' || 
            key === 'company_name' || 
            key === 'item_description') continue;
        
        const translatedKey = keyMap[key] || key;
        let value = data[key];
        
        if (valueMap[value]) value = valueMap[value];
        
        if (key === 'date_ymd' && data[key]) {
            const yyy = data[key].substring(0, 3);
            const mm = data[key].substring(3, 5);
            const dd = data[key].substring(5, 7);
            const ad_year = parseInt(yyy, 10) + 1911;
            value = `${ad_year} / ${mm} / ${dd}`;
        }
        
        if (key === 'exchange_rate_used' && data[key]) {
             value = data[key].toFixed(4);
        }
        
        output += `${translatedKey}: ${value || 'N/A'}\n`;
    }
    return output;
}

// --- (舊) 主應用程式邏輯 (保持不變) ---
document.addEventListener('DOMContentLoaded', () => {

    const uploadForm = document.getElementById('uploadForm');
    const fileInput = document.getElementById('fileInput');
    const resultEl = document.getElementById('result');
    const submitButton = document.getElementById('submitButton');
    const successMessage = document.getElementById('successMessage');

    uploadForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (fileInput.files.length === 0) return;

        const formData = new FormData();
        formData.append('file', fileInput.files[0]);

        resultEl.innerText = '辨識中...';
        submitButton.disabled = true;
        submitButton.innerText = '處理中...';
        successMessage.style.display = 'none';

        try {
            const response = await fetch('/process-invoice', {
                method: 'POST',
                body: formData
            });
            
            const data = await response.json();
            
            if (response.ok) {
                resultEl.innerText = displayFormattedResult(data);
                successMessage.style.display = 'block';
            } else {
                throw new Error(data.detail || "辨識失敗");
            }
        } catch (error) {
            resultEl.innerText = '錯誤: ' + error.message;
        } finally {
            submitButton.disabled = false;
            submitButton.innerText = '上傳並辨識';
        }
    });
});