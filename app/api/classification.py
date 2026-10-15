import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.application.classification_service import (
    ClassificationService,
    InvalidModelOutputError,
    UnknownCapabilityForRequest,
)
from app.infrastructure.providers.ollama import ProviderUnavailableError
from app.security.dependencies import _audit, require_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["AI capabilities"])


class ClassificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1)


class ClassificationResponse(BaseModel):
    capability: str
    category: str


@router.post("/classify", response_model=ClassificationResponse)
async def classify(
    payload: ClassificationRequest,
    request: Request,
    api_key=Depends(require_api_key),
) -> ClassificationResponse:
    registry = request.app.state.capability_registry
    if registry.get(payload.capability) is None:
        raise HTTPException(status_code=422, detail="Unsupported capability.")

    if payload.capability not in api_key.capabilities:
        _audit(
            request,
            event_type="capability_denied",
            key_id=api_key.key_id,
            metadata={"capability": payload.capability},
        )
        raise HTTPException(
            status_code=403,
            detail="The API key is not authorized for this capability.",
        )

    limiter = request.app.state.concurrency_limiter
    lease = await limiter.try_acquire(api_key.key_id)
    if lease is None:
        _audit(
            request,
            event_type="concurrency_limit_denied",
            key_id=api_key.key_id,
            metadata={"capability": payload.capability},
        )
        raise HTTPException(
            status_code=429,
            detail={"code": "CONCURRENCY_LIMITED"},
            headers={"Retry-After": "1"},
        )

    try:
        service: ClassificationService = request.app.state.classification_service
        try:
            result = await service.classify(
                capability_id=payload.capability,
                message=payload.message,
            )
        except UnknownCapabilityForRequest as exc:
            raise HTTPException(
                status_code=422,
                detail="Unsupported capability.",
            ) from exc
        except InvalidModelOutputError as exc:
            logger.warning(
                "invalid_model_output request_id=%s capability=%s",
                getattr(request.state, "request_id", None),
                payload.capability,
            )
            raise HTTPException(
                status_code=502,
                detail="The AI provider returned an invalid result.",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="Input failed capability validation.",
            ) from exc
        except ProviderUnavailableError as exc:
            logger.warning(
                "provider_unavailable request_id=%s capability=%s",
                getattr(request.state, "request_id", None),
                payload.capability,
            )
            raise HTTPException(
                status_code=503,
                detail="The configured AI provider is unavailable.",
            ) from exc

        return ClassificationResponse(**result)
    finally:
        await lease.release()
