"""Privacy-safe integration errors."""


class HealthPlanetError(Exception):
    """Base exception with fixed, non-sensitive messages."""


class HealthPlanetAuthError(HealthPlanetError):
    pass


class HealthPlanetConnectionError(HealthPlanetError):
    pass


class HealthPlanetRateLimitError(HealthPlanetError):
    pass


class HealthPlanetSchemaError(HealthPlanetError):
    def __init__(self, message: str, unknown_fields: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.unknown_fields = unknown_fields


class HealthPlanetBackendCodeError(HealthPlanetError):
    pass


class HealthPlanetManualInteractionRequired(HealthPlanetError):
    pass
