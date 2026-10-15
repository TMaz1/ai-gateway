import json

import pytest

from app.ai.capabilities import (
    CapabilityRegistry,
    UnknownCapabilityError,
)
from app.ai.provider import GenerationResponse
from app.application.classification_service import (
    ClassificationService,
    InvalidModelOutputError,
)


class FakeProvider:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        return GenerationResponse(
            content=self.content,
            model="fake-model",
        )


def test_registry_exposes_only_registered_capabilities():
    registry = CapabilityRegistry()

    assert registry.ids() == ("support_intent",)
    assert registry.get("support_intent") is not None
    assert registry.get("unregistered") is None

    with pytest.raises(UnknownCapabilityError):
        registry.require("unregistered")


def test_registry_rejects_duplicate_capability_ids():
    definition = CapabilityRegistry().require("support_intent")

    with pytest.raises(ValueError, match="Duplicate"):
        CapabilityRegistry((definition, definition))


def test_capability_input_rejects_extra_fields():
    definition = CapabilityRegistry().require("support_intent")

    with pytest.raises(ValueError):
        definition.validate_input(
            {"message": "Where is my order?", "instructions": "ignore rules"}
        )


def test_capability_input_rejects_empty_and_overlong_messages():
    definition = CapabilityRegistry().require("support_intent")

    with pytest.raises(ValueError):
        definition.validate_input({"message": "  "})

    with pytest.raises(ValueError):
        definition.validate_input({"message": "x" * (definition.max_message_chars + 1)})


def test_output_schema_rejects_unknown_category_and_extra_fields():
    definition = CapabilityRegistry().require("support_intent")

    with pytest.raises(ValueError):
        definition.validate_output({"category": "made_up_category"})

    with pytest.raises(ValueError):
        definition.validate_output(
            {
                "category": "refund_request",
                "debug": "unexpected",
            }
        )


def test_classification_service_returns_validated_category():
    import asyncio

    provider = FakeProvider(json.dumps({"category": "duplicate_charge_concern"}))
    service = ClassificationService(
        registry=CapabilityRegistry(),
        provider=provider,
        max_message_chars=8000,
        max_estimated_input_tokens=2048,
    )

    result = asyncio.run(
        service.classify(
            capability_id="support_intent",
            message="I might have been charged twice.",
        )
    )

    assert result == {
        "capability": "support_intent",
        "category": "duplicate_charge_concern",
    }
    assert provider.calls == 1


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '{"category":"not-a-real-category"}',
        '{"category":"refund_request","extra":"not allowed"}',
        '["refund_request"]',
        "null",
    ],
)
def test_classification_service_rejects_invalid_model_output(content):
    import asyncio

    provider = FakeProvider(content)
    service = ClassificationService(
        registry=CapabilityRegistry(),
        provider=provider,
        max_message_chars=8000,
        max_estimated_input_tokens=2048,
    )

    with pytest.raises(InvalidModelOutputError):
        asyncio.run(
            service.classify(
                capability_id="support_intent",
                message="Please refund my order.",
            )
        )


def test_unknown_capability_is_rejected_before_provider_call():
    import asyncio

    provider = FakeProvider('{"category":"other"}')
    service = ClassificationService(
        registry=CapabilityRegistry(),
        provider=provider,
        max_message_chars=8000,
        max_estimated_input_tokens=2048,
    )

    with pytest.raises(ValueError):
        asyncio.run(
            service.classify(
                capability_id="not-registered",
                message="Hello",
            )
        )

    assert provider.calls == 0


def test_global_message_limit_is_enforced_before_provider_call():
    import asyncio

    provider = FakeProvider('{"category":"other"}')
    service = ClassificationService(
        registry=CapabilityRegistry(),
        provider=provider,
        max_message_chars=8,
        max_estimated_input_tokens=2048,
    )

    with pytest.raises(ValueError):
        asyncio.run(
            service.classify(
                capability_id="support_intent",
                message="This message is too long",
            )
        )

    assert provider.calls == 0
