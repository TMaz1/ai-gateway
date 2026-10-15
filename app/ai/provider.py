from dataclasses import dataclass
from typing import Any, Protocol

from app.ai.capabilities import CapabilityDefinition


@dataclass(frozen=True)
class GenerationRequest:
    """Provider-neutral request for a single structured generation."""

    capability: CapabilityDefinition
    user_input: dict[str, Any]


@dataclass(frozen=True)
class GenerationResponse:
    """Provider-neutral response; output remains untrusted until validated."""

    content: str
    model: str


class GenerationProvider(Protocol):
    async def generate(
        self,
        request: GenerationRequest,
    ) -> GenerationResponse:
        """Generate content using trusted capability instructions."""
        ...
