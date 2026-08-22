# home-assistant-TANITA-healthplanet

本 repository 用於研究 TANITA HealthPlanet 與 Home Assistant 整合的可行性。

正式 production provider 應優先採用 HealthPlanet 官方 API；官方 API 正式提供體重與
體脂資料。2026-08-22 經使用者授權，以低頻方式研究使用者自己的帳號後，也確認登入
網站目前可透過 internal graph endpoint 取得更多體組成資料。此 endpoint 不是官方
API，可能隨時改版或失效。

## 已確認研究結果

持有登入網站 session 時，`GET /graph/graph.json` 可取得體重、體脂率、體脂肪量、
內臟脂肪等級、基礎代謝、肌肉量、推定骨量、體內年齡、體水分率及全身筋質點數的
schema。Git 中不含任何真實健康數值、帳密、Cookie、token、account identifier 或
raw response。

`research/healthplanet_web/` 是 experimental parser，不是已發布的 Home Assistant
provider。離線測試全部使用 synthetic fixtures。詳見
[授權研究](docs/AUTHENTICATED_RESEARCH.md)、
[experimental provider](docs/EXPERIMENTAL_PROVIDER.md) 與
[安全說明](docs/SECURITY.md)。

## 目前狀態

- 研究決策：**RESULT A：完整資料可取得**。
- Production 建議：先完成官方 OAuth provider。
- 選配下一步：把登入網站 provider 做成使用者明確 opt-in 的 experimental 功能。
- 本研究分支不包含 release、正式 HACS package、merge 或 production 穩定性承諾。

HealthPlanet 資料不可用於醫療診斷或治療判斷。啟用 experimental website provider
前，使用者應自行評估服務條款與隱私風險。
