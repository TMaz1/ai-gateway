import json

from app.ai.capabilities import CapabilityRegistry
from app.ai.provider import GenerationProvider, GenerationRequest


class InvalidModelOutputError(ValueError):
    """The model output is not valid for the selected capability."""


class UnknownCapabilityForRequest(ValueError):
    """The request selected an unregistered capability."""


class ClassificationService:
    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        provider: GenerationProvider,
        max_message_chars: int,
        max_estimated_input_tokens: int,
    ) -> None:
        self._registry = registry
        self._provider = provider
        self._max_message_chars = max_message_chars
        self._max_estimated_input_tokens = max_estimated_input_tokens

    async def classify(
        self,
        *,
        capability_id: str,
        message: str,
    ) -> dict[str, str]:
        definition = self._registry.get(capability_id)
        if definition is None:
            raise UnknownCapabilityForRequest(capability_id)

        validated_message = definition.validate_input({"message": message})

        if len(validated_message) > self._max_message_chars:
            raise ValueError("message exceeds the gateway character limit")

        estimated_tokens = (len(validated_message) + 3) // 4
        if estimated_tokens > self._max_estimated_input_tokens:
            raise ValueError("message exceeds the gateway token estimate limit")

        generated = await self._provider.generate(
            GenerationRequest(
                capability=definition,
                user_input={"message": validated_message},
            )
        )

        try:
            decoded = json.loads(generated.content)
        except (json.JSONDecodeError, TypeError) as exc:
            raise InvalidModelOutputError("Model output was not valid JSON.") from exc

        try:
            result = definition.validate_output(decoded)
        except (TypeError, ValueError) as exc:
            raise InvalidModelOutputError(
                "Model output did not match the capability schema."
            ) from exc

        return {
            "capability": definition.capability_id,
            **result,
        }
