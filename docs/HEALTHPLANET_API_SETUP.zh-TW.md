# HealthPlanet API Application 設定

HealthPlanet for Home Assistant 是獨立開發的非官方整合。每一套 Home Assistant 只需申請一次 HealthPlanet API Application；所有家庭成員可共用 Client ID / Client Secret，但每位成員仍需各自授權自己的帳號。

## 第一步：登入 HealthPlanet

登入 HealthPlanet，依序開啟：

**登録情報 → サービス連携 → アプリケーション開発者の方はこちら → 新規登録**

v0.2.0 manual-code OAuth 建議選擇 **クライアントアプリケーション（Client Application）**。HealthPlanet 官方允許 Client Application 使用 `https://www.healthplanet.jp/success.html` 作為 redirect URI，而且設定項目較少。

現有 Web Application credentials 不必強制重建；只要 HealthPlanet 接受 `https://www.healthplanet.jp/success.html`，即可繼續使用。

## 第二步：填寫 Application 欄位

| HealthPlanet 欄位 | 範例 |
| --- | --- |
| サービス名 | Home Assistant HealthPlanet（可自行命名，不必寫死） |
| メールアドレス | 使用者自己的 Email |
| 説明 | Home Assistant integration for accessing the user's own HealthPlanet measurements. |
| アプリケーションタイプ | クライアントアプリケーション |

完成後 HealthPlanet 會產生 `client_id` 與 `client_secret`，請妥善保管。

## 第三步：加入 Home Assistant Application Credentials

在 Home Assistant 開啟：

**設定 → 裝置與服務 → Application Credentials／應用程式憑證 → HealthPlanet for Home Assistant**

建議名稱：`HealthPlanet API`

| Home Assistant 欄位 | 填入內容 |
| --- | --- |
| OAuth Client ID | HealthPlanet `client_id` |
| OAuth Client Secret | HealthPlanet `client_secret` |

**這不是 HealthPlanet 網站登入帳號密碼。**每台 HA 只設定一次，不要為每位家庭成員重新申請 API application。

## 第四步：逐一授權家庭成員

新增 HealthPlanet for Home Assistant、輸入家庭成員名稱，並選擇共用的 Application Credential。整合會開啟 `https://www.healthplanet.jp/oauth/auth`，參數為：

- `response_type=code`
- `scope=innerscan,sphygmomanometer`
- `redirect_uri=https://www.healthplanet.jp/success.html`

允許存取後，複製 HealthPlanet 顯示的 code，並在 10 分鐘內貼回 Home Assistant。整合會向 `https://www.healthplanet.jp/oauth/token` 交換 access token。

一次性 code 永不持久化；家庭成員 entry 只保存自己的 access token，Client Secret 持續由 Application Credentials 管理。HealthPlanet 沒有 documented refresh-token grant，因此 API 驗證失敗時需透過 Reauth 重新取得 code。
