# JP SPA 06 — 課程販售金額拆分、純預約與混合耗材核銷（05 後增量）

**狀態：Staging-only，未經真實 Railway／MySQL 交易與瀏覽器驗收。**

## 版本與依賴

- 基準：使用者上傳的 04 版 `admin(2).py`、`customer(2).py`、`admin_dashboard(3).html`、`admin_customer_detail(2).html`、`advanced_reports.py` 及之前上傳的 `views.py`、`__init__.py` 等，再套用已交付的 `05_course_sales_after_04.patch` 重建的 **05 程式**。
- 這份 Patch **只含 05 → 06 的差異**。必須先成功安裝 02、04、05 的 MySQL Migration 與 05 程式碼。不能把它直接套在 04 或 03 上。
- 06 只修改 `project/admin.py`、`project/advanced_reports.py`、`project/course_sales.py`、`project/templates/admin_dashboard.html`，並新增 `project/course_service.py`；既有寄店與儲值模組不覆蓋。
- 06 Migration 只新增欄位及資料表，不重寫任何歷史訂單、預約、儲值或寄店容量。DDL 會自動提交，不能單靠 `ROLLBACK` 還原。

## 功能

### 課程販售（同一「預約管理」頁）

- Staff／Admin 仍可販售指定課程的 1／5／10 等堂數（依 05 設定的優惠），可改價，且須以現金、刷卡、轉帳、儲值等合計全額付清。
- **單堂**新增：耗材來源（店內／顧客寄店／混合）、手技費、店內產品收費、顧客寄店已購產品價值（僅註記，不是本次款項）。最後應收價可以手動調整，原價、組成及調價差額記錄在購買紀錄。
- **多堂**繼續使用其指定堂數優惠總價，沿用店內耗材模式；06 不自動為它套用單堂混合耗材的定價規則。
- 已勾選 `uses_store_consumables=1` 的固定價套裝，後端拒絕顧客寄店產品來源。
- 可以「只寄存」、「今天使用」、「同時預約未來」、「連結先前純預約」。前 3 種符合原 05 的安排，不會在販售時扣掉 g／ml。
- 顧客寄店名下應已有可用、帶 ml/g 單位的庫存，否則不能選擇顧客寄店或混合來源。

### 建立／補登預約

- 原有的「直接收費預約」介面已改成 **純預約／使用已購堂數** 二選一，同一視窗內選擇客戶、課程與時段。
- 兩種流程皆在同一預約管理頁；客戶搜尋支援姓名、帳號、電話、ID 的任意子字串（不只姓氏），選擇後以 ID 提交，避免同名誤選。
- **純預約**：`bookings.total_amount=0`，`sessions_purchased=0`、`sessions_remaining=0`，且 `is_unpaid_course_booking=1`；不收款、不發放已購權益、不可直接標記完成。取消可釋放時段；到店完成付款時從販售表單選「連結先前純預約」，不新增重複預約。
- **使用已購堂數**：只提供該客戶有可用堂數的購買批次；先保留，完成後才正式核銷。新預約本身不建立一筆新的課程商品銷售。
- 原 04 的**產品加購／補登**另外保留為「獨立產品訂單」按鈕，仍可分筆付款、加總金額；此操作不再偷偷建立收費的課程預約。若需要把產品與課程合併成同一張發票／同一個交易批次，需另定義發票與關聯規則。

### 完成服務及混合耗材

- 新 06 購買的已購堂數預約必須走「完成／扣堂／核銷耗材」，舊的狀態下拉不能直接繞過核銷。
- 核銷來源可同時包含：實際服務客戶名下的寄店產品、`store@jparomatic.local` 店內耗材帳戶名下的寄存產品。**店內耗材帳戶不是第二個接受服務的顧客。**
- 每筆選定來源、`customer_inventory.id`、實際 g／ml 使用量；系統在同一 MySQL 交易內鎖定預約及各寄存庫存、寫入客戶與店內獨立的 `customer_inventory_requests` + `customer_inventory_movements`、寫入 06 核銷明細、核銷一堂與服務營收、更新完成狀態及稽核紀錄。任一來源容量不足會全部回滾。
- 同一預約只能有一次 `course_service_completions`、同一來源庫存不得重複列出，杜絕重複扣堂／扣料。
- 新 06 售出的課程要求在結案時填入與販售指定的來源一致的**至少一筆耗材**；若實際完全未使用耗材，需另行決定例外規則，**不要以虛構 g／ml 結案**。
- 客戶寄店已購產品價值僅作銷售價格拆分與稽核備註；**沒有依 g/ml 自動推導貨幣價值**，也不把已購商品當新收款或重新計入產品售價。

## Staging 檢查與套用

1. 確認 Git 工作樹沒有要被覆蓋的其他改動，備份程式及 **Staging** MySQL，並確認還原方式。
2. 先在 Staging MySQL 檢查 02/04/05 既有結構存在：

   ```sql
   SHOW TABLES LIKE 'customer_inventory_movements';
   SHOW TABLES LIKE 'manual_checkout_payments';
   SHOW TABLES LIKE 'customer_course_purchases';
   SHOW COLUMNS FROM bookings LIKE 'course_purchase_id';
   SELECT id,email FROM users WHERE email='store@jparomatic.local';
   ```

3. 確認沒有執行過 06：`SHOW COLUMNS FROM bookings LIKE 'is_unpaid_course_booking';` 應無結果。只有在前置 Migration 都完成時，才執行一次 `06_course_booking_materials_migration.sql`。
4. 程式碼放在 Git 專案根目錄後先驗證：

   ```powershell
   git status --short
   git apply --check --ignore-space-change ".\06_course_booking_mixed_materials_after_05.patch"
   ```

5. 通過後才套用與驗證：

   ```powershell
   git apply --ignore-space-change ".\06_course_booking_mixed_materials_after_05.patch"
   python -m py_compile project/admin.py project/advanced_reports.py project/course_sales.py project/course_service.py project/course_entitlements.py
   git -c core.whitespace=cr-at-eol diff --check
   python .\test_05_course_logic.py
   python .\test_06_course_logic.py
   ```

   `test_05_course_logic.py`、`test_06_course_logic.py` 放在專案根目錄後測試即可。新 Patch 沒有修改或安裝實際 Railway DB。

6. 完成下方人工測試後，才考慮提交到正式分支。**不要在未完成 MySQL Migration 的正式資料庫上部署新版程式。**

## 最低人工驗收（Staging MySQL + 真實瀏覽器）

1. 完整課程單堂 $5,000，其中手技 $1,600、店內 $3,400：付款 $5,000，完成時僅扣店內耗材帳戶 g/ml。
2. 單堂 $5,000，客戶寄店產品價值 $3,400：實付 $1,600；完成時僅扣真實客戶寄店產品，不會新收 $3,400。
3. 單堂 $5,000，手技 $1,600、店內產品收費 $1,700、客戶寄店價值 $1,700：現金 $1,000 + 刷卡 $2,300，應收 $3,300。完成時分別核銷 2 個帳戶的用量，`customer_course_allocations` 只認列本次已付 $3,300。
4. 故意讓其中一個來源容量不足：提交失敗；堂數、兩種耗材與服務營收均未變動。
5. 重送同一服務完成請求：不重複扣堂或扣料；完成後試圖透過舊狀態下拉回復亦被拒絕。
6. 建立純預約，不付錢：`total_amount=0`、不增加課程權益或營收；到店買五堂並連結先前預約，再完成一堂，剩餘四堂。
7. 用已購堂數建立預約：只保留一次；取消釋放保留堂數，不能超用。
8. 販售固定價套裝課程，後端阻止顧客寄店來源。
9. 使用特殊店內耗材帳戶的產品補登（非營收訂單），核對後台總覽／進階報表不把它算成銷售收入。
10. 「產品加購／補登」保持 04 的整數金額、分筆付款、庫存扣減與產品訂單收入。
11. Admin／Staff 權限、CSRF、輸入驗證、以姓名與電話任意字元搜尋，及頁面手機版基本可用性。

## 尚未完成或仍有風險（請勿當作已驗收）

- **尚未實測真實 MySQL／Railway／瀏覽器**。離線通過 Python 編譯、Jinja2 解析、Node JS 語法、05/06 純邏輯測試、乾淨 05 基準 `git apply --check` 與實際 `git apply`。
- 02～05 的舊課程與寄店紀錄不被自動轉換：05 的既有已購批次預設不強制新的耗材核銷；有原 04 直接收費預約的歷史金額不被重算。
- **一般公開網站的顧客直接預約流程**（`views.py`）仍保留舊制金額／顯示邏輯，本 Patch **只改後台課程販售與預約**；若要同步公開網站成為純預約，也須先取得最新版 `project/templates/booking_success.html` 等相關未提供頁面，以免顧客看到 0 元而誤以為免費。
- 進階報表既有 HTML 模板尚未提供；此版對 `advanced_reports.py` 做排除純預約的統計修正，但**沒有重新設計報表的收款／已履約／預收款視覺呈現**。舊制未付帳款仍可能影響歷史報表。
- 淨利目前仍沿用課程 `service_fee + product_fee` 估計成本，沒有用實際 g/ml 和歷史產品成本分攤精確算毛利；本版避免把店內耗材特殊帳戶訂單當成對外產品銷售／銷售成本，但完整成本會計需另訂規則。
- 不實作退款、退堂、贈送、已完成後的逆向沖銷，也不把「客戶寄店已購價值」與 ml/g 用量自動作貨幣調節。這些需明確商業規則後才可安全加入。
- 如果專案在套用 05 後有額外改動，06 Patch 可能衝突，**不要使用 `--force`、`--reject` 強制套用**；請以實際最新檔案重產增量 Patch。
