# 專案探索與 Bug 驗證 — 2026-09-08

## 範圍與驗證方式

檢查現行 Flask 路由、卡片／牌組 repository、FSRS 與考試排程、時間處理、SQLite adapter/schema、學習頁 JavaScript、表單、設定頁及安裝／更新／還原腳本；對照 CONTEXT.md 與 5 份 ADR。舊 bug_report.md 描述舊版程式，未把其結論當成現行問題。

此次完成探索與重現，沒有修正產品程式，也沒有操作正式 flashcards.db。新 Python 控具強制使用臨時資料庫、關閉 Discord、固定時間；前端控具執行實際 study.html 的 script，以最小 DOM／網路替身驗證佇列，並非完整瀏覽器視覺測試。

- 現有 `python -m unittest discover -s tests -v`：7/7 通過。
- 現有 `python test_exam_scheduling.py`：9 個整合測試函式全部完成。
- 新 Python 控具：7 個預期使用行為全部失敗，揭露下列 7 個後端問題。
- 新 Node 控具：3 個預期使用行為全部失敗，揭露下列 3 個前端問題。

目前 `.venv/Scripts/python.exe` 無法啟動，因此使用桌面附帶 Python，透過 PYTHONPATH 載入現有 `.venv/Lib/site-packages`。這是本機驗證環境限制，不能據此斷言部署環境也失效。

## 已重現問題

### 1. [P1] 新增較晚考試會把新卡排到近期考試之後

- 位置：`schedulers/exam_scheduler.py:204-206, 224-265, 607-610`。
- 重現：12 張未學新卡，同牌組先建立 3 天後考試，再建立 30 天後考試；固定洗牌順序與 jitter。
- 結果：9/12 張的首次學習時間被移到近期考試當天或之後。使用者可能來不及學完近期考試範圍。
- 根因：分發直接以此次指定考試重新安排所有 reps=0 卡片，沒有逐卡保護仍有效的較早考試期限。
- 修正方向：依每張卡片的所有有效考試取得最早期限；建立、匯入與到期重排共用這項限制。
- 控具：`test_later_exam_must_not_postpone_cards_past_earlier_exam`。

### 2. [P1] 不合法 FSRS 權重可以儲存，之後所有作答失敗

- 位置：`app.py:631-634`、`schedulers/fsrc_scheduler.py:31-36`。
- 重現：設定頁輸入 21 個 `-1`，再對一張卡片評分。
- 結果：設定成功寫入；真正建立 FSRS Scheduler 時拋出 `ValueError: One or more parameters are out of bounds`。一般服務模式下作答 API 回應 500。
- 根因：儲存僅驗證數量與 float 轉換，未採用 FSRS 的參數合法性檢查。
- 修正方向：儲存前以安裝版本的 Scheduler 驗證，拒絕非法值並保留最後有效設定；載入既有壞設定時也需可恢復。
- 控具：`test_invalid_weights_rejected_before_breaking_reviews`。

### 3. [P1] 合併釋義回報成功，新增內容卻被截掉

- 位置：`repos/card_repo.py:157-169, 279-293`。
- 重現：某卡背面已有 500 字元，再新增相同正面、背面為 `new meaning` 的卡片。
- 結果：回傳已合併，但儲存內容仍是原本 500 字元，新釋義完全消失。CSV 合併也使用相同截斷方式。
- 根因：合併後直接 `merged_back[:500]`，沒有向使用者說明資料丟失。
- 修正方向：完整保存合併內容，或在超限時明確拒絕且不宣稱成功；表單新增／編輯的欄位截斷亦應一併處理。
- 控具：`test_merge_does_not_silently_discard_new_meaning`。

### 4. [P2] 背景到期卡插隊後，已作答的新卡仍留在佇列

- 位置：`templates/study.html:250-258, 389, 502-504`。
- 重現：正在作答新卡 A；20 秒輪詢帶回到期複習卡 B；接著提交 A。
- 結果：合併把 B 插到 A 前方，但畫面 currentCard 仍是 A；提交成功僅在隊首為 A 時才移除，於是 A 留在佇列，後續再次出題，可能在 FSRS 到期前再次計入作答。
- 修正方向：currentCard 與待處理佇列分離，或確保插隊不移動當前卡；提交成功按已作答 ID 移除。
- 控具：Node 的 `polling due card must not leave answered card queued`，執行實際 merge、showAnswer、submitReview。

### 5. [P2] 每日新卡上限在不同牌組各算一次

- 位置：`schedulers/exam_scheduler.py:383-404`、`database.py:477-485`。
- 重現：兩個牌組各有一張新卡，全域設定每日上限 1，開啟「今日一般複習」。
- 結果：API 返回 2 張新卡；學完 A 後 B 仍有自己的額度。設定頁描述「每日最多引入指定數量的新卡」，但實作額度依查詢範圍改變。
- 修正方向：全域統計今日首次學習數量，今日集合先去重、再統一套用剩餘額度。
- 控具：`test_daily_limit_applies_across_decks`。

### 6. [P2] 同一牌組也能因背景輪詢突破新卡上限

- 位置：`schedulers/exam_scheduler.py:402-404`、`templates/study.html:228-258`。
- 重現：上限 1，牌組有多張新卡；第一次回應抽到 A，尚未作答，後續輪詢抽到 B。
- 結果：後端每次隨機選不同卡，前端只追加未見過的卡，佇列累積成 2 張。額度用完也不會清除預先累積的未學卡。
- 修正方向：提供穩定的新卡選取／額度機制，前端同步符合最新額度的佇列，而非無條件追加。
- 控具：Node 的 `successive limit=1 responses must not accumulate new cards`。控具提供兩份各一張的合法 API 回應，驗證實際 merge 行為。

### 7. [P2] 考試日期與台灣本地午夜相差 8 小時

- 位置：`templates/exams.html` 的 date input、`schedulers/exam_scheduler.py:575`、`domain/time_provider.py:66-67`。
- 重現：表單選擇 2026-09-10；頁面說明時間為該日凌晨 00:00。
- 結果：儲存 `2026-09-10T00:00:00+00:00`，即台灣 09/10 08:00，而非台灣午夜應有的 `2026-09-09T16:00:00+00:00`；倒數與過期處理因此晚 8 小時。
- 根因：人類輸入的無時區日期與資料庫 UTC 解析共用同一函式。
- 修正方向：輸入邊界先按 UTC+8 解讀再轉 UTC；不要直接更改所有 DB 無時區字串的解讀。顯示日期亦須轉回本地。
- 控具：`test_form_date_is_midnight_in_taipei`。

### 8. [P2] 跨考試／一般牌組共用卡片使首頁重複計數

- 位置：`database.py:601-630`，對照 `database.py:523-524`。
- 重現：一張卡同時屬於考試牌組 A 與一般牌組 B。
- 結果：首頁今日總量為 2，一般複習顯示有卡；但實際兩種今日佇列加總僅 1，一般複習為空。
- 根因：首頁依牌組分類後分開去重，學習佇列則以「任何所屬牌組有考試」分類卡片。
- 修正方向：統計與學習共用逐卡分類、去重邏輯。
- 控具：`test_shared_card_summary_matches_actual_queues`。

### 9. [P2] CSV 超過行數限制時變成伺服器錯誤

- 位置：`app.py:407-410`，`repos/card_repo.py:255-258`。
- 重現：合法表單貼入 10,001 行 `a,b`，總大小約 40KB。
- 結果：repo 正確拋出行數超限 ValueError，路由雖 flash 錯誤卻沒有回傳 response；Flask 拋出 `The view function for 'import_csv' did not return a valid response`。
- 修正方向：例外分支回傳重新顯示的表單或 redirect；不要把失敗頁面的 return 只放在表單驗證失敗的 else 中。
- 控具：`test_oversize_csv_returns_feedback_instead_of_500`。

### 10. [P2] 學習頁待複習／新卡數多算當前卡一次

- 位置：`templates/study.html:283-289, 389-390`。
- 重現：佇列只有一張新卡，呼叫 showNextCard。
- 結果：「新卡片」顯示 2；複習卡亦有相同問題。
- 根因：currentCard 是 activeQueue[0]，已被 filter 計數，之後又加一。
- 修正方向：統一佇列是否包含 currentCard 的定義，避免重複計數。
- 控具：Node 的 `one card must display one remaining`。

## 維運腳本靜態風險（未執行更新／還原）

以下與上面已重現的 10 項分開計算：

- `update.sh:27`、`update.ps1:15` 讀 shell 環境的 DATABASE_PATH，沒有載入 `.env`；app 的 Config 則會讀 `.env`。只在 `.env` 自訂 DB 路徑時，備份可能跳過真正的 DB 或備份另一個檔案；restore 腳本仍指定 flashcards.db。
- `restore.ps1:55-60` 直接複製 SQLite 主檔，沒有關閉服務／連線或處理 WAL。與目前啟用 WAL 的 adapter 不一致，需用臨時 WAL 資料庫進一步驗證完整還原流程後修正。此次未在使用者機器執行還原。

## 重現指令與後續順序

在已安裝 requirements 的 Python 環境，由 repo 根目錄執行：

```text
python docs/audit/reproduce_20260908.py
node docs/audit/reproduce_study_20260908.cjs
```

修正後兩者應以零碼結束。這些控具保留於 docs/audit，不會混入現有 tests discovery。

建議先修 1–3（考前排程、作答阻斷、內容丟失），接著一起整理 4–6、10 的佇列與額度狀態，最後處理日期、統計、失敗回應與維運腳本。這是有範圍的探索結果，不代表已窮盡所有併發、部署或瀏覽器問題。
