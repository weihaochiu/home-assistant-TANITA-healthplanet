# HealthPlanet API Application setup

HealthPlanet for Home Assistant is unofficial and independent. Each Home Assistant installation needs one HealthPlanet API application. All family members can share its Client ID and Client Secret, while each member separately authorizes their own account.

## 1. Register an application in HealthPlanet

Sign in to HealthPlanet, then navigate through **登録情報 → サービス連携 → アプリケーション開発者の方はこちら → 新規登録**.

For the v0.2.0 manual-code flow, choose **クライアントアプリケーション (Client Application)**. HealthPlanet permits Client Applications to use `https://www.healthplanet.jp/success.html` as the redirect URI, and this type needs fewer settings. Existing Web Application credentials do not have to be rebuilt if HealthPlanet accepts that same redirect URI.

Example fields:

| HealthPlanet field | Example |
| --- | --- |
| サービス名 | Home Assistant HealthPlanet (you may choose another name) |
| メールアドレス | Your own email address |
| 説明 | Home Assistant integration for accessing the user's own HealthPlanet measurements. |
| アプリケーションタイプ | クライアントアプリケーション |

HealthPlanet then provides a `client_id` and `client_secret`. Keep both private.

## 2. Add Home Assistant Application Credentials

In Home Assistant, open **Settings → Devices & services → Application Credentials → HealthPlanet for Home Assistant**.

Suggested name: `HealthPlanet API`

| Home Assistant field | Value |
| --- | --- |
| OAuth Client ID | HealthPlanet `client_id` |
| OAuth Client Secret | HealthPlanet `client_secret` |

These are not the HealthPlanet Website login ID and password. Configure the Application Credential once; do not create another API application for every family member.

## 3. Authorize each family member

Add HealthPlanet for Home Assistant, enter the family member name, and select the shared credential. The integration opens:

`https://www.healthplanet.jp/oauth/auth`

with `response_type=code`, scope `innerscan,sphygmomanometer`, and redirect URI `https://www.healthplanet.jp/success.html`. After approval, copy the code shown by HealthPlanet and paste it back into Home Assistant within 10 minutes.

The one-time code is exchanged at `https://www.healthplanet.jp/oauth/token`. The code is never persisted. Only the family member's access token is stored in the config entry; the Client Secret remains managed by Application Credentials. HealthPlanet documents no refresh-token grant, so an API authentication failure requires Reauth with a new code.
