# HealthPlanet 網頁端點研究 Probe

此 repository 目前只有一個保護隱私的 TANITA HealthPlanet 網頁研究工具，**尚未完成
Home Assistant 或 HACS integration**。本階段只讓帳號擁有者在本機確認目前正常登入
流程、未公開 graph endpoint 是否仍有回應，以及哪些候選體組成 kind 可識別出 schema。

## 安全與隱私界線

- 絕對不要把 HealthPlanet 密碼交給 Codex，也不要貼到聊天中。
- 必須由你本人在本機終端執行。Login ID 使用一般終端輸入；密碼使用 Python
  `getpass`，輸入時不會顯示。
- 不接受 command-line 密碼，也不讀取 `.env` 或明文 credential file。
- Cookie 只存在獨立的記憶體 cookie jar，程序結束時清除；不建立 cookie、token、
  HAR 或完整 response dump。
- 不會把任何健康測量數值寫入磁碟。JSON 結果以嚴格 allowlist 重新建立。
- 一旦遇到 CAPTCHA、MFA/OTP、consent、bot challenge、安全警告、跨網域 redirect 或
  不明登入流程，立即輸出 `MANUAL_INTERACTION_REQUIRED`；不猜測或繞過。
- 所有 request 皆循序執行、timeout 15 秒、不重試；單次執行硬上限為 12 次。

Graph endpoint 是 HealthPlanet 網站未公開的內部介面，不是官方 API，可能隨時變更或
失效。使用者曾手動看到的 `code=-1` 沒有已引用的官方定義，不能假設它代表「沒有
資料」。本工具不可用於醫療判斷；請自行閱讀目前的服務條款並評估是否適合你的帳號。

## 在本機執行

Probe 沒有第三方 runtime 依賴。請在 PowerShell 執行：

```powershell
cd D:\Github\home-assistant-TANITA-healthplanet
py scripts\probe_healthplanet.py
```

也可以使用獨立環境：

```powershell
cd D:\Github\home-assistant-TANITA-healthplanet
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements_probe.txt
py scripts\probe_healthplanet.py
```

Sanitized 結果會寫入 `_local_only/healthplanet_schema_probe.json`。整個
`_local_only/` 已排除於 Git 與 source backup。不要分享密碼，也不要分享網站的完整
原始 response。Probe 完成後，只需告訴 Codex：

> 已完成 probe，請讀取 `_local_only/healthplanet_schema_probe.json` 繼續分析。

## 開發與驗證

Repository 測試完全離線，fixture 全是人工合成資料：

```powershell
python -m compileall scripts tests
python -m pytest
```

公開來源、request 流程、隱私控制、輸出規範與 `code=-1` 的未知狀態，請見
[設計文件](docs/WEB_PROBE_DESIGN.md)。

