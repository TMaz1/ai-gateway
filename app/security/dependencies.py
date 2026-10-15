import logging
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.application.api_key_service import ApiKeyService
from app.domain.models import ApiKey, Capability, SecurityEvent
from app.security.concurrency import ConcurrencyLease, ConcurrencyLimiter
from app.security.rate_limiter import InMemoryRateLimiter

logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False, scheme_name="Gateway API key")


def get_api_key_service(request: Request) -> ApiKeyService:
    service = getattr(request.app.state, "api_key_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Service unavailable")
    return service


def _audit(
    request: Request,
    *,
    event_type: str,
    key_id: str | None,
    metadata: dict[str, str],
) -> None:
    events = getattr(request.app.state, "security_events", None)
    if events is None:
        return

    event = SecurityEvent(
        event_type=event_type,
        key_id=key_id,
        request_id=getattr(request.state, "request_id", None),
        metadata={str(key)[:64]: str(value)[:128] for key, value in metadata.items()},
        created_at=datetime.now(UTC),
    )

    try:
        events.record(event)
    except Exception:
        logger.exception(
            "security_audit_write_failed event_type=%s",
            event_type,
        )


async def require_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    service: ApiKeyService = Depends(get_api_key_service),
) -> ApiKey:
    if credentials is None or credentials.scheme.lower() != "bearer":
        _audit(
            request,
            event_type="authentication_denied",
            key_id=None,
            metadata={"reason": "missing_credentials"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid gateway API key is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    api_key = service.validate(credentials.credentials)
    if api_key is None:
        _audit(
            request,
            event_type="authentication_denied",
            key_id=None,
            metadata={"reason": "invalid_credentials"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid gateway API key is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    limiter: InMemoryRateLimiter = request.app.state.rate_limiter
    decision = limiter.check(api_key.key_id)

    if not decision.allowed:
        _audit(
            request,
            event_type="rate_limit_denied",
            key_id=api_key.key_id,
            metadata={"limit": str(decision.limit)},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Request rate limit exceeded.",
            headers={
                "Retry-After": str(decision.retry_after_seconds),
                "X-RateLimit-Limit": str(decision.limit),
                "X-RateLimit-Remaining": "0",
            },
        )

    request.state.api_key_id = api_key.key_id
    return api_key


async def _acquire_lease(
    request: Request,
    api_key: ApiKey,
) -> ConcurrencyLease:
    limiter: ConcurrencyLimiter = request.app.state.concurrency_limiter
    lease = await limiter.try_acquire(api_key.key_id)

    if lease is None:
        _audit(
            request,
            event_type="concurrency_limit_denied",
            key_id=api_key.key_id,
            metadata={"scope": "global_or_per_key"},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "CONCURRENCY_LIMITED"},
            headers={"Retry-After": "1"},
        )

    return lease


def require_capability(capability: Capability | str) -> Callable:
    required_value = (
        capability.value if isinstance(capability, Capability) else capability
    )

    async def dependency(
        request: Request,
        api_key: ApiKey = Depends(require_api_key),
    ):
        if required_value not in api_key.capabilities:
            _audit(
                request,
                event_type="capability_denied",
                key_id=api_key.key_id,
                metadata={"capability": required_value},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The API key is not authorized for this capability.",
            )

        lease = await _acquire_lease(request, api_key)
        try:
            yield api_key
        finally:
            await lease.release()

    return dependency


def require_concurrency_slot() -> Callable:
    async def dependency(
        request: Request,
        api_key: ApiKey = Depends(require_api_key),
    ):
        lease = await _acquire_lease(request, api_key)
        try:
            yield api_key
        finally:
            await lease.release()

    return dependency
