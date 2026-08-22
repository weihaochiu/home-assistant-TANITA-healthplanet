"""Safe fixed-message errors for the experimental web parser."""


class HealthPlanetWebError(Exception):
    """Base error whose messages never include response data."""


class BackendCodeError(HealthPlanetWebError):
    pass


class ExpiredSessionError(HealthPlanetWebError):
    pass


class MalformedResponseError(HealthPlanetWebError):
    pass


class SchemaDriftError(HealthPlanetWebError):
    pass


class UnsupportedKindError(HealthPlanetWebError):
    pass
