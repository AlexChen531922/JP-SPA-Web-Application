# 晶品芳療 JP SPA — 05 課程販售／寄存堂數／核銷（04 後增量版）

**目前狀態：Staging-only。已完成離線程式檢查與獨立 Git 套用檢查；尚未驗證真實 MySQL、Railway、業務驗收。**

## 使用基準

本 Patch 是根據使用者於 2026-11-19 提供的最新版 `admin(2).py`、`customer(2).py`、`admin_dashboard(3).html`、`admin_customer_detail(2).html`、`advanced_reports.py`，以及先前提供的 `views.py`、`course_detail.html`、`customer_dashboard.html`、`__init__.py` 所製作。假設本機 **已套用 04_mixed_checkout_after_03.patch**。**不要**重新套用 02／03／04。

### 交付內容

- `05_course_sales_after_04.patch`：11 份程式檔修改（含新增 `project/course_entitlements.py`、`project/course_sales.py`）
- `05_course_purchases_migration.sql`：增量資料庫結構；不會修改／重建既有客戶交易或堂數資料
- `test_05_course_logic.py`：不依賴 MySQL 的純邏輯測試；可放在專案根目錄執行

## 重要：先確認 04 Migration 已執行

04 Patch 套用成功 **不代表 04 資料庫 Migration 已執行**。請先對 **Staging MySQL** 執行檢查：

```sql
SHOW TABLES LIKE 'manual_checkout_payments';
SHOW COLUMNS FROM bookings LIKE 'deposit_credit_amount';
SHOW TABLES LIKE 'customer_inventory_movements';
```

以上應有結果。如缺少，先核對並按 02／04 的安裝文件處理，不可盲目直接執行 05。

## 安裝順序（先在 Staging）

1. 備份 MySQL（以及程式碼），並確認資料庫恢復方案。MySQL DDL 無法依賴一般 `ROLLBACK` 回復。
2. 若 `04` Migration 已完成，且 05 尚未執行，在 **Staging DB** 執行一次 `05_course_purchases_migration.sql`。**不可重複執行**。
3. 放 `05_course_sales_after_04.patch` 於 Git 專案根目錄，先檢查：

```powershell
 git status --short
 git apply --check --ignore-space-change ".\05_course_sales_after_04.patch"
```

4. 上述檢查成功，且 Staging Migration 完成後才正式套用 Patch：

```powershell
 git apply --ignore-space-change ".\05_course_sales_after_04.patch"
 python -m py_compile project/admin.py project/customer.py project/views.py project/advanced_reports.py project/course_sales.py project/course_entitlements.py
 git -c core.whitespace=cr-at-eol diff --check
 git diff --stat
 python test_05_course_logic.py
```

5. 尚未通過下列人工驗收前，不要直接推送到正式 Railway 服務。

如果 `git apply --check` 有任何衝突，先停止，不要使用 `--force`／`--reject`，也不要以整份舊檔覆蓋你目前的本機版本。

## 實作邏輯

- **課程設定**：一堂依 `regular_price`；額外的堂數優惠採輸入格式 `5:11000,10:20000`（也可自訂 2–100 的不同堂數），各課程獨立設定；Staff／Admin 可操作。
- **售價**：自動帶入該課程堂數優惠，可改動最終總價，後端記錄預設價和實際價。
- **付款**：當次購買須全額付清，可同時使用現金／信用卡／匯款／儲值扣款／其他；寄店產品不是套裝課程的付款方式。儲值扣款使用既有原子交易函式。
- **使用安排**：販售後可僅寄存、今天現場使用（建立當天待完成服務紀錄），或同時預約下次日期。建立預約時先保留一堂，**完成後**核銷。
- **使用已購堂數**：後台的「使用客戶已購堂數預約」以及客戶詳情堂數頁籤，或公開課程頁（僅顯示一般公開課程）中選擇自己的既有購買批次；一律驗證客戶與課程一致。
- **堂數保護**：使用同一筆 `FOR UPDATE` 鎖定購買紀錄，剩餘堂數扣除已完成及保留，防止超用；取消預約釋放保留，完成後禁止直接刪除或改回未完成。每次異動寫入 append-only `customer_course_events`。
- **收益**：新販售金額 **不直接**加到服務營收，服務完成後才把相應折扣價值記錄到 `customer_course_allocations.recognized_amount`；新預約 `bookings.total_amount=0`，避免同筆課程再次認列。報表採服務完成日期計入新制營收；儲值金既有扣款不額外新增營收。
- **不顯示**：課程改成啟用（公開）、不顯示（僅後台）、停用；公開列表／課程詳情／時段 API／一般會員直接預約皆排除不顯示課程。
- **店內耗材套裝課程**：課程可勾選「使用店內耗材」，禁止使用客戶寄店產品抵扣／核銷；**不會擅自建立店內產品扣庫存**（尚未指定課程對應產品品項、g/ml/件數等規則）。
- **既有版本**：04 直接收費預約及產品訂單仍保留其既有流程，沒有自動轉成新制的已購堂數。

## Staging 驗收案例

1. Staff 建立「臉部保養」5 堂優惠，修改預設售價，以現金＋刷卡全額付清；確認 `customer_course_purchases`、付款明細及稽核紀錄一致。
2. 販售後不預約，客戶應保有 5 堂；檢查沒有 `bookings` 記錄且本次服務營收為 0。
3. 販售 10 堂、當日使用 1 堂：先保留一堂，改狀態為 completed 後才扣堂／認列分攤收入，餘 9 堂。
4. 販售 5 堂，安排 2 筆未來預約：已保留 2 堂、可用 3 堂；再同時提交 4 筆請求必須阻止超用。
5. 取消未完成預約：只釋放其保留堂數，不能退款或更改原始課程販售金額；重複取消不可增加堂數。
6. 已完成預約：重複按完成不可多次扣堂，改回 pending、取消、永久刪除均須被拒絕。
7. 客戶在前台公開課程頁選用自己的已購批次，預約成功且 `total_amount=0`、不新增現金收款；用別人的批次必須拒絕。
8. 固定價店內耗材套裝課程：嘗試寄店抵扣及扣客戶寄店容量都應拒絕；店內損耗訂單不納入營收。
9. 啟用／不顯示／停用：不顯示課程公開 GET／排程 API／直接 POST 預約不應可用，Staff／Admin 後台仍可售；停用不可新售。
10. 05 購買後未履約，後台和進階報表的服務收入不增加；完成後僅增加分攤值；儲值付款不重複入帳；店內損耗排除產品銷售額。
11. 比對 04 原有「直接收費預約＋加購」流程，檢查原有報價、付款方式、寄店待核銷不受影響。
12. 驗證 MySQL Migration 後所有外鍵、唯一鍵、防止重複送出，測試 Staging 真交易 rollback。

## 尚未完成／不可假裝完成的內容

- **無真 MySQL 或 Railway 實測**；本 Patch 只通過離線編譯、Jinja 解析、JavaScript 語法、純邏輯測試、獨立 Git Patch 套用。
- **沒有新增課程販售退款／整筆退課／轉讓／特殊爽約扣堂／核銷後帳務更正介面。** 已完成堂數不能直接倒回；若實務需要退費，應先規定退費與沖銷方式並另做審計流程。因此本版暫不適合直接處理正式交易。
- **既有 02～04 舊交易仍依舊 SQL 欄位，並未自動追溯改為新制**；舊制預約尚未收款也可能已被舊報表當成營收。待人工對帳後才可安全遷移舊資料。
- **店內耗材尚不會自動因套裝課程完成而扣庫存**；必須先有各療程的耗材品項與用量／人工耗用規則。已用店內損耗訂單登記的商品，不應再次重複計入產品成本；目前「淨利潤」依舊是估算，仍可能重複計算店內耗材成本。
- 進階報表相關 HTML 模板未重新提供，因此這版修改 `advanced_reports.py` 的計算資料來源，**沒有改動報表 HTML 版面標籤**。若需同時顯示「預收餘額／實際入帳／已履約營收」多欄完整報表，需要最新版 `project/templates/reports_dashboard.html`、`reports_courses.html`、`reports_customers.html`。
- 原 `courses.sessions`／歷史 `bookings.sessions_remaining` 不會直接被視為已付費購買權益，避免憑推測建立客戶堂數。

## 驗證結論

以本次上傳檔案做 04 版本基準，Patch 可成功 `git apply --check` 並實際套用至獨立驗證資料夾，完成 Python、4 個 Jinja 模板、4 個 JS 區塊靜態檢查，且模擬測試涵蓋堂數／核銷／全額付款與分攤尾差。**不代表真實 DB 營運驗收完成**。
