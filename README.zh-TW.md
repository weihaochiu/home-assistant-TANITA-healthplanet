# TANITA HealthPlanet Home Assistant 整合

這是 HACS 相容 custom integration 的 v0.1.0 候選版，採用 **Official-first Hybrid（官方優先混合）**架構：官方 API 對其支援的資料具有唯一所有權；使用者明確啟用後，實驗性 Website source 只補齊官方 API 沒有的項目。

## 模式

| 模式 | 狀態 | 認證 | Sensor 數 |
| --- | --- | --- | --- |
| Official-first Hybrid | 建議／預設 | Home Assistant Application Credentials OAuth，再選擇是否啟用網站登入 | 13 |
| Official API only | 支援 | Home Assistant Application Credentials OAuth | 5 |
| Experimental Website only | 實驗性 | HealthPlanet 網站帳密 | 10 |

Hybrid 的體重與體脂率絕不取自 Website。Official source 提供體重、體脂率、收縮壓、舒張壓與脈搏；Website source 提供體脂肪量、內臟脂肪等級、基礎代謝（`kcal`）、肌肉量、推定骨量、體內年齡、體水分率及全身筋質點數。

血壓 sensors 需要 HealthPlanet 帳號內已有 sphygmomanometer 資料。只採用「同一時間同時具有收縮壓與舒張壓」的最新完整配對；脈搏也必須與該配對時間相同才會發布。較新但不完整的資料不會蓋掉上一組完整配對。缺值與 null 維持 unavailable，絕不補 0。

Website endpoint 需要登入但未公開，可能隨時改版、失效或被封鎖，TANITA 不保證支援。Website-only 主要保留給既有設定遷移及疑難排解；建議使用 Hybrid。

## 安裝與設定

目前沒有 release 或 tag。實機測試請下載此分支 ZIP，完整替換 Home Assistant 中的 `custom_components/tanita_healthplanet` 資料夾，不要混用舊候選版檔案。重新啟動後，到「設定 → 裝置與服務 → 新增整合 → TANITA HealthPlanet」。

Official 或 Hybrid 模式需先在「設定 → 裝置與服務 → Application Credentials」加入 HealthPlanet API application 的 client ID 與 client secret，並向 HealthPlanet 登記 redirect URI：

`https://my.home-assistant.io/redirect/oauth`

本版要求 OAuth scope `innerscan,sphygmomanometer`。在加入此 scope 前建立的 Official entry 必須重新認證。Hybrid 完成 OAuth 後才會詢問是否啟用 Website，並在收取網站帳密前顯示「endpoint 非官方」及「`.storage` 並非專用加密密碼庫」兩項明確確認。

既有 v1 Website entry 會原地遷移成 Website-only，不改 entity unique ID，也不會再次顯示或要求既有密碼。可用「重新設定（Reconfigure）」經標準外部 OAuth 安全升級為 Hybrid。Options 可分別設定 Official 與 Website 更新週期，預設 60 分鐘，可設定 30–1440 分鐘。

## 故障隔離、隱私與移除

Official Innerscan、Official Sphygmomanometer 與 Website 都有結構化 diagnostics；兩個 source coordinator 的更新、availability 與認證狀態彼此獨立。一個來源失敗不會清除另一來源的成功資料。來源認證失效會啟動該來源 reauthentication；一般重複錯誤在恢復前會節流 warning，避免每個週期洗版。

Home Assistant 會在 config-entry store 保存 OAuth 資料；啟用 Website 時也會保存網站登入資料。`.storage` 不是專用加密密碼庫。請勿在 GitHub issue 貼上 credentials、Cookie、token、raw response、未遮罩 diagnostics 或真實健康數值。

完整移除時，先刪除所有 TANITA HealthPlanet config entry，再從 HACS 移除 custom repository（或刪除 component 資料夾）並重啟 Home Assistant；如有需要，再撤銷 OAuth 授權或更改網站密碼。

正式提交 HACS 前，repository owner 仍須選定 license、設定 GitHub description／topics 並提供 brand assets。CI 只排除這些由 owner 決定的發布條件。

詳見[隱私](docs/PRIVACY.md)、[安全](SECURITY.md)、[架構](docs/ARCHITECTURE.md)及[疑難排解](docs/TROUBLESHOOTING.md)。

要安全檢查 diagnostics，請在「裝置與服務」中開啟本整合的三點選單，選擇「下載診斷資料」，只在本機檢查並在分享前再次遮罩；不要同時附上帳號畫面或 raw provider response。
