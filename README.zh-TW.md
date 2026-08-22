# TANITA HealthPlanet Home Assistant 整合

這是 HACS 相容 custom integration 的 v0.1.0 開發分支，支援多個彼此獨立的 config entry，預設並建議使用 HealthPlanet 官方 OAuth API。

## Provider

| Provider | 狀態 | 認證 | Sensor |
| --- | --- | --- | --- |
| Official API | 建議、預設 | OAuth `client_id`、`client_secret`、authorization code | 體重、體脂率 |
| Experimental Website | 預設不啟用，需明確 opt-in | HealthPlanet 網站帳密 | 研究確認的 10 項資料 |

Website provider 使用需登入但未公開的網站 endpoint；它**不是官方 API**，可能隨時改版、失效或被封鎖，TANITA 也不保證支援。每個 config entry 只使用一種 provider，不混合來源。

Website provider 提供體重、體脂率、體脂肪量、內臟脂肪等級、基礎代謝（顯示為 `kcal/day`）、肌肉量、推定骨量、體內年齡、體水分率與全身筋質點數。Official provider 只提供官方文件中的體重與體脂率。缺值維持 unavailable，絕不補 0；kind 23 全身筋質點數在真實 non-null 值尚未獨立驗證前標示為 experimental／medium confidence。

## 開發版安裝與設定

目前沒有 release 或 tag。分支測試可把本 repository 加入 HACS custom Integration repository，或將 `custom_components/tanita_healthplanet` 複製到 Home Assistant 的 `custom_components`。重新啟動後，到「設定 → 裝置與服務 → 新增整合」加入 TANITA HealthPlanet。

正式提交 HACS 前，repository owner 仍須選定 license、設定 GitHub description 與有效 topics，並提供 brand assets（或登錄至 Home Assistant Brands）。CI 只排除這四項由 owner 決定的發布條件，其餘 integration/package 規則仍全部驗證。

Official flow 需要在 HealthPlanet API 申請的資料。Experimental flow 必須確認 endpoint 非官方，也必須確認 Home Assistant `.storage` 並非專門的加密密碼庫。

預設每 60 分鐘更新，Options 可設 30–1440 分鐘。認證失敗會啟動 reauthentication。移除 config entry 時會卸載 entities、清除記憶體 Cookie/session，並由 Home Assistant 移除該 entry 的保存資料；接著可從 HACS 移除程式碼。

請勿在 issue 貼上 credentials、未遮罩 diagnostics、Cookie、token 或真實健康數值。健康資料不可用於醫療診斷。詳見[隱私](docs/PRIVACY.md)、[安全](SECURITY.md)、[架構](docs/ARCHITECTURE.md)及[疑難排解](docs/TROUBLESHOOTING.md)。
