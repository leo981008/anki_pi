# Apache2 部署指南 (Deployment Guide)

本指南將說明如何在 Linux (如 Raspberry Pi OS, Ubuntu) 上使用 Apache2 與 mod_wsgi 部署此應用程式。

## 1. 安裝必要套件

請更新系統並安裝 Apache2 與 mod_wsgi (Python 3 版本)：

```bash
sudo apt update
sudo apt install apache2 libapache2-mod-wsgi-py3 python3-pip python3-venv
```

## 2. 準備專案環境

建議將專案放置在 `/var/www/` 或使用者家目錄下 (例如 `/home/pi/anki_pi`)。

如果尚未建立虛擬環境 (Virtual Environment)，建議建立一個以隔離依賴套件：

```bash
cd /path/to/anki_pi  # 請替換為您的實際路徑
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 3. 設定 Apache

本專案提供了一個範例設定檔 `anki_pi.conf`。

1. **編輯設定檔**：
   打開 `anki_pi.conf`，將所有的 `/path/to/anki_pi` 替換為您實際的專案路徑。
   如果您使用了虛擬環境，請確保 `WSGIDaemonProcess` 指令中有包含 `python-home=/path/to/anki_pi/venv` (若無使用 venv 則不需要 python-home)。

   範例 (使用 venv)：
   ```apache
   WSGIDaemonProcess anki_pi python-home=/home/pi/anki_pi/venv python-path=/home/pi/anki_pi
   ```

2. **複製設定檔**：
   將修改好的設定檔複製到 Apache 的設定目錄：
   ```bash
   sudo cp anki_pi.conf /etc/apache2/sites-available/anki_pi.conf
   ```

3. **啟用網站**：
   ```bash
   sudo a2dissite 000-default.conf  # 停用預設網站 (選擇性)
   sudo a2ensite anki_pi.conf       # 啟用本專案
   sudo systemctl reload apache2    # 重新載入 Apache 設定
   ```

## 4. 設定檔案權限 (重要！)

由於本專案使用 SQLite 資料庫 (`flashcards.db`) 且支援檔案上傳/建立資料夾，Apache 的執行使用者 (通常是 `www-data`) 必須擁有對資料庫檔案**及其所在目錄**的讀寫權限。

假設專案位於 `/home/pi/anki_pi`：

```bash
# 將專案目錄擁有者改為當前使用者，群組改為 www-data
sudo chown -R pi:www-data /home/pi/anki_pi

# 設定權限，讓群組 (www-data) 可以讀寫
sudo chmod -R 775 /home/pi/anki_pi

# 確保資料庫檔案和目錄可寫
# SQLite 需要在目錄中建立暫存檔，所以目錄也必須可寫
sudo chmod g+w /home/pi/anki_pi
sudo chmod g+w /home/pi/anki_pi/flashcards.db
```

如果有上傳或匯入檔案的功能，確保 `imported_files` 目錄也存在並可寫：
```bash
mkdir -p /home/pi/anki_pi/imported_files
sudo chmod -R 775 /home/pi/anki_pi/imported_files
sudo chown -R pi:www-data /home/pi/anki_pi/imported_files
```

## 5. 測試與除錯

開啟瀏覽器，輸入伺服器的 IP 位址即可看到網站。

如果出現 `500 Internal Server Error`，請查看 Apache 錯誤日誌：

```bash
sudo tail -f /var/log/apache2/anki_pi_error.log
```

常見錯誤原因：
*   Python 套件未安裝 (請確認 requirements.txt 是否已安裝在環境中)。
*   路徑設定錯誤 (檢查 conf 檔中的路徑)。
*   權限不足 (檢查 SQLite db 權限)。
