"""Constants for the TANITA HealthPlanet integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

DOMAIN = "tanita_healthplanet"
PLATFORMS = ["sensor"]
VERSION = "0.1.0"

PROVIDER_OFFICIAL = "official"
PROVIDER_WEBSITE = "website"
PROVIDERS = (PROVIDER_OFFICIAL, PROVIDER_WEBSITE)

CONF_PROVIDER = "provider"
CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_ACCESS_TOKEN = "access_token"
CONF_ACCOUNT_LABEL = "account_label"
CONF_LOGIN_ID = "login_id"
CONF_PASSWORD = "password"
CONF_EXPERIMENTAL_CONFIRMED = "experimental_confirmed"
CONF_STORAGE_WARNING_CONFIRMED = "storage_warning_confirmed"
CONF_UPDATE_INTERVAL = "update_interval"

DEFAULT_UPDATE_INTERVAL_MINUTES = 60
MIN_UPDATE_INTERVAL_MINUTES = 30
MAX_UPDATE_INTERVAL_MINUTES = 1440
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=DEFAULT_UPDATE_INTERVAL_MINUTES)

OFFICIAL_AUTH_URL = "https://www.healthplanet.jp/oauth/auth"
OFFICIAL_TOKEN_URL = "https://www.healthplanet.jp/oauth/token"
OFFICIAL_DATA_URL = "https://www.healthplanet.jp/status/innerscan.json"
OFFICIAL_REDIRECT_URI = "https://www.healthplanet.jp/success.html"
OFFICIAL_SCOPE = "innerscan"
OFFICIAL_TAG_WEIGHT = "6021"
OFFICIAL_TAG_BODY_FAT = "6022"

WEBSITE_BASE_URL = "https://www.healthplanet.jp"
WEBSITE_LOGIN_URL = f"{WEBSITE_BASE_URL}/login.do"
WEBSITE_GRAPH_URL = f"{WEBSITE_BASE_URL}/graph/graph.json"
WEBSITE_KINDS = (1, 2, 3, 4, 5, 6, 7, 14, 22, 23)
WEBSITE_PRIMARY_KINDS = tuple(kind for kind in WEBSITE_KINDS if kind != 23)
WEBSITE_REQUEST_INTERVAL_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 20
USER_AGENT = (
    "home-assistant-TANITA-healthplanet/0.1.0 (+experimental authenticated website provider)"
)

JST_TIMEZONE = "Asia/Tokyo"


@dataclass(frozen=True)
class MetricDescription:
    kind: int
    key: str
    translation_key: str
    unit: str | None
    official_tag: str | None = None
    medium_confidence: bool = False


METRICS: dict[int, MetricDescription] = {
    1: MetricDescription(1, "weight", "weight", "kg", OFFICIAL_TAG_WEIGHT),
    2: MetricDescription(
        2, "body_fat_percentage", "body_fat_percentage", "%", OFFICIAL_TAG_BODY_FAT
    ),
    3: MetricDescription(3, "body_fat_mass", "body_fat_mass", "kg"),
    4: MetricDescription(4, "visceral_fat_level", "visceral_fat_level", None),
    5: MetricDescription(5, "basal_metabolic_rate", "basal_metabolic_rate", "kcal/day"),
    6: MetricDescription(6, "muscle_mass", "muscle_mass", "kg"),
    7: MetricDescription(7, "estimated_bone_mass", "estimated_bone_mass", "kg"),
    14: MetricDescription(14, "metabolic_age", "metabolic_age", "y"),
    22: MetricDescription(22, "body_water_percentage", "body_water_percentage", "%"),
    23: MetricDescription(
        23,
        "muscle_quality_score",
        "muscle_quality_score",
        None,
        medium_confidence=True,
    ),
}

OFFICIAL_KINDS = tuple(
    kind for kind, description in METRICS.items() if description.official_tag is not None
)
SENSITIVE_CONFIG_KEYS = {
    CONF_ACCESS_TOKEN,
    CONF_CLIENT_SECRET,
    CONF_LOGIN_ID,
    CONF_PASSWORD,
    "authorization",
    "cookie",
    "csrf",
    "refresh_token",
    "token",
}
