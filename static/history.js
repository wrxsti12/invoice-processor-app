// --- 翻譯函式 (保持不變) ---
const valueMap = {
    "Online (PDF)": "線上 PDF 發票",
    "Electronic (QR Code)": "電子發票 (QR Code)",
    "Traditional (OCR)": "傳統紙本發票 (OCR)",
};
function formatAmount(amount) { return amount ? amount : "N/A"; }
function formatTWD(amount) { return amount ? `NT$ ${amount.toFixed(2)}` : "N/A"; }
function formatRate(rate) { return rate ? rate.toFixed(4) : "N/A"; }
function truncate(text) {
    if (!text) return "N/A";
    if (text.length > 30) return text.substring(0, 30) + "...";
    return text;
}
function formatDate(iso_date_str) {
    if (!iso_date_str) return "N/A";
    return iso_date_str;
}

// --- (舊) 階段四：載入彙總資料 ---
async function loadSummary() {
    const summaryBody = document.getElementById('summaryBody');
    const summaryTotalEl = document.getElementById('summaryTotal');

    try {
        const response = await fetch('/summary');
        if (!response.ok) {
            // (修改) 提供更清晰的錯誤提示
            const errorData = await response.json();
            throw new Error(`無法獲取彙總資料: ${errorData.detail || response.statusText}`);
        }

        const summaryData = await response.json();
        const summaries = summaryData.monthly;
        const totalAllTime = summaryData.total_all_time;

        if (summaries.length === 0) {
            summaryBody.innerHTML = '<tr><td colspan="2">尚無資料可彙總。</td></tr>';
        } else {
            summaryBody.innerHTML = '';
            summaries.forEach(item => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${item.month}</td>
                    <td>${formatTWD(item.total_twd)}</td>
                `;
                summaryBody.appendChild(row);
            });
        }

        summaryTotalEl.innerHTML = `<p>總支出 (所有時間): ${formatTWD(totalAllTime)}</p>`;

    } catch (error) {
        summaryBody.innerHTML = `<tr><td colspan="2" class="error-message">${error.message}</td></tr>`;
        summaryTotalEl.innerHTML = '<p class="error-message">無法計算總金額</p>'; // (新) 錯誤時也更新總計
    }
}

// --- (舊) 階段三：載入詳細歷史紀錄 ---
async function loadHistory() {
    const tableBody = document.getElementById('historyBody');
    tableBody.innerHTML = '<tr><td colspan="8">載入中...</td></tr>';

    try {
        const response = await fetch('/invoices');
        if (!response.ok) {
            throw new Error(`無法獲取詳細資料: ${response.statusText}`);
        }

        const invoices = await response.json();

        if (invoices.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="8">資料庫中尚無發票紀錄。</td></tr>';
            return;
        }

        tableBody.innerHTML = '';

        invoices.forEach(invoice => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${invoice.invoice_number}</td>
                <td>${truncate(invoice.company_name)}</td>
                <td>${truncate(invoice.item_description)}</td>
                <td>${formatAmount(invoice.total_amount)}</td>
                <td>${invoice.currency || 'N/A'}</td>
                <td>${formatTWD(invoice.total_amount_twd)}</td>
                <td>${formatRate(invoice.exchange_rate_used)}</td>
                <td>${formatDate(invoice.invoice_date_iso)}</td>
            `;
            tableBody.appendChild(row);
        });

    } catch (error) {
        tableBody.innerHTML = `<tr><td colspan="8" class="error-message">${error.message}</td></tr>`;
    }
}

// --- 主邏輯：頁面載入 ---
document.addEventListener('DOMContentLoaded', () => {
    loadSummary();
    loadHistory();

    // --- (新) 刪除按鈕邏輯 ---
    const deleteAllButton = document.getElementById('deleteAllButton');
    const deleteStatus = document.getElementById('deleteStatus');

    deleteAllButton.addEventListener('click', async () => {
        // 1. 跳出確認視窗
        const confirmed = window.confirm("您確定要刪除所有發票歷史紀錄嗎？此操作無法復原！");

        if (confirmed) {
            deleteStatus.innerText = "刪除中...";
            deleteStatus.style.display = 'block';
            deleteStatus.className = ''; // 清除之前的樣式 (例如 error-message)
            deleteAllButton.disabled = true;

            try {
                // 2. 呼叫後端 DELETE API
                const response = await fetch('/invoices', {
                    method: 'DELETE',
                });

                const data = await response.json();

                if (response.ok) {
                    // 3. 成功後刷新表格
                    deleteStatus.innerText = data.message || "刪除成功！";
                    deleteStatus.className = 'success-message'; // 顯示成功樣式
                    await loadSummary(); // 重新載入彙總 (應為空)
                    await loadHistory(); // 重新載入歷史 (應為空)
                } else {
                    throw new Error(data.detail || "刪除失敗");
                }

            } catch (error) {
                // 4. 處理錯誤
                deleteStatus.innerText = `刪除失敗: ${error.message}`;
                deleteStatus.className = 'error-message'; // 顯示錯誤樣式
            } finally {
                // 5. 無論成功失敗，都恢復按鈕狀態 (延遲一下讓使用者看到訊息)
                setTimeout(() => {
                     deleteAllButton.disabled = false;
                     // 可以選擇是否隱藏狀態訊息
                     // deleteStatus.style.display = 'none';
                }, 3000); // 延遲 3 秒
            }
        } else {
            // 使用者取消
            deleteStatus.innerText = "已取消刪除操作。";
            deleteStatus.style.display = 'block';
             deleteStatus.className = '';
             setTimeout(() => { deleteStatus.style.display = 'none'; }, 2000);
        }
    });
});