# HealthPlanet for Home Assistant

HealthPlanet for Home Assistant 是用於存取使用者本人 TANITA HealthPlanet 量測資料的**非官方** Home Assistant 整合。

本專案為獨立開發的開源專案，與 TANITA Corporation、TANITA Health Link 及 Home Assistant 官方皆無隸屬、無贊助、無背書或官方合作關係。

## 使用 HACS 安裝

### Step 1 — 使用 HACS 安裝程式

**使用 HACS 安裝／下載整合程式：**

[![在 HACS 開啟 repository](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=weihaochiu&repository=home-assistant-TANITA-healthplanet&category=integration)

1. 安裝並設定 [HACS](https://www.hacs.xyz/docs/use/download/download/)。
2. 在 HACS 開啟此 repository，下載 **HealthPlanet for Home Assistant**。

### Step 2 — 重新啟動 Home Assistant

確認 HACS 已將預期版本寫入 `custom_components/tanita_healthplanet/manifest.json` 後才重新啟動。

### Step 3 — 新增／設定整合

完成下方「設定前準備」，再新增整合。

**此按鈕只會開啟 Home Assistant 的整合設定流程，不會下載、重新安裝或更新整合程式。**

[![新增 HealthPlanet for Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=tanita_healthplanet)

## 安全更新

透過 HACS 安裝 HealthPlanet for Home Assistant 後，integration 會原生提供可選的「**安全更新 HealthPlanet**」按鈕；不需要另外匯入 Blueprint、安裝 Add-on、第二個 integration、token 或另一份 HACS repository。整套 HA 只會建立一個 repository-level 按鈕，不會每位家庭成員各建一個。只有使用者明確按下按鈕才會執行，不會無人值守自動更新或突然重啟。

使用前請先完成「設定 → 系統 → 備份」。安全更新會沿用其中的 automatic backup 內容、儲存位置、加密／密碼及 retention 設定。按下後會：

1. 透過 public registry 找到 HACS update entity、由 HA config path 讀取 disk manifest、拒絕 version drift，再確認有新版；
2. 呼叫 `backup.create_automatic`，且必須先證明本次新備份進入 `in_progress`，才接受後續新的 `completed`；
3. 呼叫標準 `update.install`，不傳 HACS 未宣告支援的 native `backup` flag；
4. 確認 HACS `installed_version` 與 disk manifest 都等於事前記錄的目標版本；
5. 視設定呼叫 `homeassistant.restart`（預設啟用）。

若無法自動辨識，可到本 integration 的「設定／Configure」選擇一次 HACS update entity。Fallback 會保存 HACS registry identity，因此 entity 重新命名後不會 hard-code 舊 entity ID。同一頁也可停用成功後自動重新啟動；設定對整套 installation 生效。

備份失敗或 timeout 一定阻止安裝；更新失敗或 timeout 一定阻止 restart。安全更新只會重新啟動 Home Assistant Core，不會重新啟動 Home Assistant OS 主機。Repository 的下載、安裝及 HACS 自己的 rollback 行為仍由 HACS 負責。由於 HACS repository update entity 可能沒有 Home Assistant 原生的「更新前備份」選項，本 integration 會先自行建立並驗證 Home Assistant backup，再呼叫 HACS。

偵測到 HACS 新版絕對不會自動執行 backup、install 或 restart；只有使用者明確按下「安全更新 HealthPlanet」才會開始。HACS metadata 與 disk manifest 在更新前或更新後不一致時一定 fail closed，絕不 restart。

啟動限制：v0.2.0 尚未包含這段程式，因此 v0.2.0 → v0.2.1 這一次仍需使用一般 HACS update，再手動 restart Home Assistant。從 v0.2.1 → v0.2.2 及之後版本才可直接使用 Native Safe Update。

## 可取得的資料

新帳號只使用一個 Hybrid entry，共 13 個 sensors：

| 來源 | 指標 |
| --- | --- |
| HealthPlanet 官方 API | 體重、體脂率、收縮壓、舒張壓、脈搏 |
| Experimental Website source | 體脂肪量、內臟脂肪等級、基礎代謝、肌肉量、推定骨量、體內年齡、體水分率、筋質點數 |

Hybrid 不會從 Website 重複發布 kind 1／2。筋質點數為 null 時維持 unavailable，不補 0。Website endpoint 未公開且屬實驗性，可能隨時改變。

## 設定前準備

**每一套 Home Assistant 只需要申請一次 HealthPlanet API Application。**同一家庭的所有 HealthPlanet 帳號可以共用這組 Client ID / Client Secret，但每位家庭成員都需要各自完成一次帳號授權，並取得各自的 access token。

1. 使用 HACS 安裝整合。
2. [註冊一個 HealthPlanet API Application](docs/HEALTHPLANET_API_SETUP.zh-TW.md)。
3. 到「設定 → 裝置與服務 → Application Credentials／應用程式憑證 → HealthPlanet for Home Assistant」加入憑證。

Client ID / Secret ≠ HealthPlanet 帳號 / 密碼。

| Credential | 用途 | 共用範圍 |
| --- | --- | --- |
| Client ID | HealthPlanet API application | 一台 HA 共用 |
| Client Secret | HealthPlanet API application | 一台 HA 共用 |
| OAuth access token | 官方 API 帳號授權 | 每位家庭成員 |
| Website login ID | Experimental Website source | 每位家庭成員 |
| Website password | Experimental Website source | 每位家庭成員 |

## 新增第一位家庭成員

1. 新增 **HealthPlanet for Home Assistant**，輸入家庭成員名稱。
2. 選擇全 HA 共用的 Application Credential。
3. 開啟 HealthPlanet 授權連結；redirect 使用 `https://www.healthplanet.jp/success.html`，不使用 My Home Assistant callback。
4. 允許存取、複製一次性 code，並在取得後 10 分鐘內貼回 Home Assistant。
5. 輸入該成員自己的 HealthPlanet Website 帳密，接受 Experimental source 警告。

Authorization code 只在交換期間短暫存在記憶體，不會 log、寫檔、進 diagnostics 或存入 entry。Client Secret 留在 Home Assistant Application Credentials；家庭成員 entry 只保存自己的 access token。HealthPlanet 沒有 documented refresh-token grant，官方驗證失敗時會啟動 Reauth，要求重新取得一次性 code。

## 新增其他家庭成員

再次新增整合，輸入不同的家庭成員名稱，重用同一組 Application Credential，再授權另一個 HealthPlanet 帳號。不同 Website login 可建立多個 entries；同一 Website login 不可重複。Plaintext login ID 不會放進 unique ID、entity ID 或 log。

Device 名稱為 `HealthPlanet - {家庭成員}`；entity unique ID 維持 `{entry_id}_{kind}`。

## 歷史資料

- 官方指標：每次最多 90 天，使用 documented `date=1`、`from`、`to`。
- Website 補充指標：只保證已確認的 31 天。
- 首次設定會同步歷史；日常在記憶體做增量判斷，device 的「同步歷史」button 可重新抓取兩個來源。
- 最新 sensor 的 `measurement_time` 保留 provider 精確量測時間。
- Home Assistant 管理 state `last_updated`；本整合不修改它，也不直接寫 Recorder database。
- Recorder 支援的 external statistics 是每小時粒度；同一 UTC 小時多筆資料計算 arithmetic `mean`、`min`、`max`，不偽裝成分鐘級 native state history。
- Home Assistant 2026.8 將 native entity statistic import 保留給 Recorder；同步資料可依 `HealthPlanet …` 名稱直接用標準 **Statistics Graph** card 顯示，但不會偽造進以 state 為基礎的「歷史」panel。
- 重啟、reload、refresh 或手動同步以 source/kind/time stable identity 去重，並依賴 Recorder 的同小時更新語意保持 idempotent；不在 `.storage` 另存一份健康 history JSON。

History import 是獨立 failure domain；Recorder 或歷史來源失敗不會讓 current sensors unavailable。

## 舊 v0.1.x entries

既有 Website-only、Official-only、Hybrid 更新後繼續運作，不會自動強改，因為 OAuth 需要互動。使用「重新設定（Reconfigure）」可將 Website-only 或 Official-only 原地升級為 Hybrid，保留另一來源憑證與全部既有 entity unique IDs。

## 隱私

Diagnostics 只含來源結果、結構 row count、安全的同步 counters 與同步執行時間；不含家庭成員名稱、login ID、credentials、authorization code、token、健康數值、measurement timestamp、含 query 的 URL 或 raw response。詳見[隱私](docs/PRIVACY.md)與[安全](SECURITY.md)。

## 疑難排解

- 授權後沒有回到 HA：這是預期行為；從 HealthPlanet success page 複製 code，貼回尚未關閉的 HA form。
- Code 過期／無效：重新產生，並在 10 分鐘內送出。
- Missing Application Credentials：每台 HA 只需完成一次 [API Application 教學](docs/HEALTHPLANET_API_SETUP.zh-TW.md)。
- Official source unavailable：執行 Reauth；Website 補充 sensors 仍獨立運作。
- Website source unavailable：檢查 Website credentials；官方 sensors 仍獨立運作。
- Historical sync failed：current sensors 不受影響；按 device 的「同步歷史」重試。
- HACS 顯示 latest 但 disk 仍是舊版：比對 HACS installed/latest 與 `manifest.json`，使用 HACS「Redownload」或 validated release ZIP，重新檢查 disk version，一致後才 restart。
- HA 整合 icon 遺失：確認完整安裝 v0.2.2（包含 `brand/`）並重啟。
- HACS repository list 仍是 placeholder：HA local integration branding 與 HACS repository-list brand proxy 是不同路徑，可能是 HACS frontend 已知限制。

更多內容見[疑難排解](docs/TROUBLESHOOTING.md)與[架構](docs/ARCHITECTURE.md)。

## 維護者 Release 流程

1. 更新 manifest、`VERSION`、`USER_AGENT`、CHANGELOG 與文件。
2. 執行完整本機驗證，push `main`，並等待 Tests、HACS、Hassfest 全部成功。
3. 建立並 push annotated stable semantic-version tag，例如 `v0.2.2`。
4. GitHub Actions 重新驗證版本一致性、測試、coverage、privacy、HACS 與 Hassfest，通過後自動發布 stable GitHub Release。
5. HACS 透過正常 background refresh 偵測新 Release。

不需要 Personal Access Token。Release automation 只使用 GitHub Actions 執行期間由 repository 提供的 `GITHUB_TOKEN`。

## 商標與非官方專案聲明

TANITA 與 HealthPlanet 為其各自權利人的商標、服務名稱或品牌。

本專案僅為說明與相關服務的相容性而使用上述名稱。

本專案為獨立開發的非官方開源 Home Assistant 整合，與 TANITA Corporation 或 TANITA Health Link 無隸屬、無贊助、無背書或官方合作關係。
