class GatewayError(Exception):
    """Base class for expected gateway-domain failures."""


class ApiKeyNotFoundError(GatewayError):
    """Raised when an API key ID does not exist."""


class ApiKeyAlreadyRevokedError(GatewayError):
    """Raised when a terminally revoked key is modified."""


class InvalidCapabilityError(GatewayError):
    """Raised when a capability value is invalid."""