"""Experimental authenticated website client kept separate from the parser."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from scripts.research_healthplanet_backend import (
    GRAPH_URL,
    KINDS,
    LoginResult,
    ResearchSession,
    login as authenticate,
)

from .errors import MalformedResponseError, UnsupportedKindError
from .models import ParseResult
from .parser import parse_graph_payload


class HealthPlanetWebClient:
    """Small experimental wrapper; callers retain responsibility for credentials."""

    def __init__(self, session: ResearchSession | None = None) -> None:
        self._session = session or ResearchSession()
        self._authenticated = False

    def login(self, login_id: str, password: str) -> dict[str, Any]:
        result: LoginResult = authenticate(self._session, login_id, password)
        self._authenticated = result.status == "success"
        return dict(result.metadata)

    def fetch_kind(self, kind: int) -> ParseResult:
        if kind not in KINDS:
            raise UnsupportedKindError("UNSUPPORTED_KIND")
        if not self._authenticated:
            raise MalformedResponseError("SESSION_NOT_AUTHENTICATED")
        query = urlencode({"day": 31, "page": 1, "kind": kind})
        response = self._session.request(
            f"{GRAPH_URL}?{query}", headers={"Accept": "application/json"}
        )
        try:
            payload = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise MalformedResponseError("MALFORMED_RESPONSE") from None
        finally:
            response = None
        return parse_graph_payload(payload, kind)

    def close(self) -> None:
        self._session.close()
        self._authenticated = False

    def __enter__(self) -> "HealthPlanetWebClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
