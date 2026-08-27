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
    def __init__(
        self,
        message: str,
        unknown_fields: tuple[str, ...] = (),
        *,
        row_length: int | None = None,
        timestamp_candidate_count: int | None = None,
        numeric_candidate_count: int | None = None,
        valid_assignment_count: int | None = None,
        field_type_shape: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.unknown_fields = unknown_fields
        self.row_length = row_length
        self.timestamp_candidate_count = timestamp_candidate_count
        self.numeric_candidate_count = numeric_candidate_count
        self.valid_assignment_count = valid_assignment_count
        self.field_type_shape = field_type_shape


class HealthPlanetBackendCodeError(HealthPlanetError):
    def __init__(self, message: str, backend_code: int | None = None) -> None:
        super().__init__(message)
        self.backend_code = backend_code


class HealthPlanetManualInteractionRequired(HealthPlanetError):
    pass
