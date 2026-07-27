"""Fake and Ollama structured recommendation provider tests."""

from __future__ import annotations

import json
from typing import cast
from uuid import uuid4

import httpx
import pytest
from app.domain.enums import GenerationStatus, QueryType
from app.recommendation.context import RecommendationContextBuilder
from app.recommendation.exceptions import (
    ConstraintAccountingError,
    MissingPositiveEvidenceCitationError,
    RecommendationModelMismatchError,
    RecommendationResponseValidationError,
)
from app.recommendation.providers import (
    FakeRecommendationProvider,
    OllamaRecommendationProvider,
)
from app.recommendation.providers.ollama import ollama_recommendation_schema
from app.recommendation.schemas import (
    EvidenceReference,
    FailureWarning,
    RecommendationContext,
    RecommendationDraft,
    RecommendationRequest,
)


def context() -> RecommendationContext:
    request = RecommendationRequest(
        project_id=uuid4(),
        brief="Create the next portrait.",
        query_type=QueryType.AI_INFLUENCER,
        constraints=["Keep the same face"],
        target_platform="instagram",
    )
    return RecommendationContextBuilder().build(
        request,
        positive_evidence=[
            EvidenceReference(
                example_id=uuid4(),
                status=GenerationStatus.APPROVED,
                query_type=QueryType.AI_INFLUENCER,
                similarity=0.9,
                summary="Approved stable face.",
            )
        ],
        failure_evidence=[
            EvidenceReference(
                example_id=uuid4(),
                status=GenerationStatus.REJECTED,
                query_type=QueryType.AI_INFLUENCER,
                similarity=0.8,
                summary="Rejected changed face.",
                rejection_reason="The face changed.",
            )
        ],
    )


def valid_draft_json(
    recommendation_context: RecommendationContext | None = None,
) -> str:
    resolved = recommendation_context or context()
    return ollama_wire_json(
        RecommendationDraft(
            recommended_prompt="Create a stable portrait. Keep the same face",
            rationale=["Approved evidence supports identity consistency."],
            used_positive_evidence_ids=[resolved.positive_evidence[0].example_id],
            failure_warnings=[
                FailureWarning(
                    evidence_id=resolved.failure_evidence[0].example_id,
                    warning="Do not change the face.",
                )
            ],
            covered_constraint_ids=["C1"],
            unmet_constraint_ids=[],
            provider_confidence=0.8,
            needs_human_review=False,
        )
    )


def ollama_wire_json(draft: RecommendationDraft) -> str:
    payload = draft.model_dump(mode="json")
    payload["rationale"] = draft.rationale[0]
    payload["constraint_accounting"] = {
        **{identifier: "covered" for identifier in draft.covered_constraint_ids},
        **{identifier: "unmet" for identifier in draft.unmet_constraint_ids},
    }
    del payload["covered_constraint_ids"]
    del payload["unmet_constraint_ids"]
    return json.dumps(payload)


def test_ollama_output_schema_omits_unsupported_grammar_keywords() -> None:
    schema = ollama_recommendation_schema()
    schema_text = json.dumps(schema)
    required = cast(list[str], schema["required"])
    properties = cast(dict[str, object], schema["properties"])

    assert "minLength" not in schema_text
    assert "maxItems" not in schema_text
    assert "minimum" not in schema_text
    assert isinstance(required, list)
    assert required == [
        "recommended_prompt",
        "rationale",
        "used_positive_evidence_ids",
        "failure_warnings",
        "constraint_accounting",
        "provider_confidence",
        "needs_human_review",
    ]
    assert set(properties) == set(required)


def test_ollama_output_schema_restricts_references_to_context_ids() -> None:
    recommendation_context = context()
    schema = ollama_recommendation_schema(recommendation_context)
    properties = cast(dict[str, dict[str, object]], schema["properties"])
    definitions = cast(dict[str, dict[str, object]], schema["$defs"])
    positive_items = cast(dict[str, object], properties["used_positive_evidence_ids"]["items"])
    accounting = cast(dict[str, dict[str, object]], properties["constraint_accounting"])
    accounting_properties = cast(dict[str, dict[str, object]], accounting["properties"])
    confidence_values = cast(list[float], properties["provider_confidence"]["enum"])
    warning_properties = cast(
        dict[str, dict[str, object]],
        definitions["FailureWarning"]["properties"],
    )
    warning_ids = cast(list[str], warning_properties["evidence_id"]["enum"])

    assert properties["recommended_prompt"]["pattern"] == "^.+$"
    assert properties["rationale"] == {"type": "string", "pattern": "^.+$"}
    assert positive_items["enum"] == [str(recommendation_context.positive_evidence[0].example_id)]
    assert accounting["required"] == ["C1"]
    assert accounting["additionalProperties"] is False
    assert accounting_properties["C1"]["enum"] == ["covered", "unmet"]
    assert confidence_values[0] == 0
    assert confidence_values[-1] == 1
    assert warning_ids == [str(recommendation_context.failure_evidence[0].example_id)]


def test_ollama_output_schema_requires_empty_reference_lists_without_ids() -> None:
    empty_context = RecommendationContextBuilder().build(
        RecommendationRequest(
            project_id=uuid4(),
            brief="Create a general image.",
            query_type=QueryType.OTHER,
        ),
        positive_evidence=[],
        failure_evidence=[],
    )
    properties = cast(
        dict[str, dict[str, object]],
        ollama_recommendation_schema(empty_context)["properties"],
    )
    confidence_values = cast(list[float], properties["provider_confidence"]["enum"])

    assert properties["used_positive_evidence_ids"] == {"const": []}
    assert properties["failure_warnings"] == {"const": []}
    assert properties["constraint_accounting"] == {"const": {}}
    assert confidence_values[-1] == 0.3


async def test_fake_provider_is_deterministic_and_preserves_constraints() -> None:
    provider = FakeRecommendationProvider()
    recommendation_context = context()

    first = await provider.generate_recommendation(recommendation_context)
    second = await provider.generate_recommendation(recommendation_context)

    assert first == second
    assert "Keep the same face" in first.recommended_prompt
    assert first.used_positive_evidence_ids == [
        recommendation_context.positive_evidence[0].example_id
    ]
    assert first.failure_warnings == [
        FailureWarning(
            evidence_id=recommendation_context.failure_evidence[0].example_id,
            warning="The face changed.",
        )
    ]
    assert first.covered_constraint_ids == ["C1"]
    assert first.unmet_constraint_ids == []


async def test_ollama_provider_requests_json_schema_without_streaming() -> None:
    recommendation_context = context()
    expected = RecommendationDraft(
        recommended_prompt="Create a stable portrait.",
        rationale=["Use approved evidence."],
        used_positive_evidence_ids=[recommendation_context.positive_evidence[0].example_id],
        failure_warnings=[
            FailureWarning(
                evidence_id=recommendation_context.failure_evidence[0].example_id,
                warning="Avoid changing the face.",
            )
        ],
        covered_constraint_ids=["C1"],
        unmet_constraint_ids=[],
        provider_confidence=0.8,
        needs_human_review=False,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/api/chat"
        assert payload["model"] == "qwen2.5:3b"
        assert payload["stream"] is False
        assert payload["format"] == ollama_recommendation_schema(recommendation_context)
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:3b",
                "message": {"role": "assistant", "content": ollama_wire_json(expected)},
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://ollama.test",
    ) as client:
        provider = OllamaRecommendationProvider(client=client)
        actual = await provider.generate_recommendation(recommendation_context)

    assert actual == expected
    assert provider.repair_attempts_used == 0


async def test_ollama_provider_repairs_once_after_invalid_json() -> None:
    calls = 0
    expected = RecommendationDraft(
        recommended_prompt="Corrected prompt.",
        rationale=["Corrected schema."],
        used_positive_evidence_ids=[],
        failure_warnings=[],
        covered_constraint_ids=["C1"],
        unmet_constraint_ids=[],
        provider_confidence=0.7,
        needs_human_review=False,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = json.loads(request.content)
        if calls == 2:
            assert len(payload["messages"]) == 4
            assert payload["messages"][-2]["role"] == "assistant"
            assert "failed validation" in payload["messages"][-1]["content"]
            assert "recommended_prompt" in payload["messages"][-1]["content"]
        content = "not-json" if calls == 1 else ollama_wire_json(expected)
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:3b",
                "message": {"role": "assistant", "content": content},
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://ollama.test",
    ) as client:
        provider = OllamaRecommendationProvider(client=client)
        actual = await provider.generate_recommendation(context())

    assert actual == expected
    assert calls == 2
    assert provider.repair_attempts_used == 1


async def test_ollama_provider_shares_repair_with_dynamic_validation() -> None:
    calls = 0
    invalid = RecommendationDraft(
        recommended_prompt="Missing accounting.",
        rationale=["Constraint was omitted."],
        used_positive_evidence_ids=[],
        failure_warnings=[],
        covered_constraint_ids=[],
        unmet_constraint_ids=[],
        provider_confidence=0.7,
        needs_human_review=False,
    )
    corrected = invalid.model_copy(update={"covered_constraint_ids": ["C1"]})

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        response = invalid if calls == 1 else corrected
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:3b",
                "message": {
                    "role": "assistant",
                    "content": ollama_wire_json(response),
                },
            },
        )

    def validate(candidate: RecommendationDraft) -> None:
        if candidate.covered_constraint_ids != ["C1"]:
            raise ConstraintAccountingError("C1 must be accounted for.")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://ollama.test",
    ) as client:
        provider = OllamaRecommendationProvider(client=client)
        actual = await provider.generate_recommendation(
            context(),
            validate=validate,
        )

    assert actual == corrected
    assert calls == 2
    assert provider.repair_attempts_used == 1


async def test_ollama_provider_rejects_missing_citation_after_bounded_repair() -> None:
    calls = 0
    recommendation_context = context()
    ungrounded = RecommendationDraft(
        recommended_prompt="Create a stable portrait.",
        rationale=["The request constraints shaped the prompt."],
        used_positive_evidence_ids=[],
        failure_warnings=[],
        covered_constraint_ids=["C1"],
        unmet_constraint_ids=[],
        provider_confidence=0.7,
        needs_human_review=False,
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:3b",
                "message": {
                    "role": "assistant",
                    "content": ollama_wire_json(ungrounded),
                },
            },
        )

    def require_citation(candidate: RecommendationDraft) -> None:
        if not candidate.used_positive_evidence_ids:
            raise MissingPositiveEvidenceCitationError(
                "Approved evidence was retrieved but the provider cited none."
            )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://ollama.test",
    ) as client:
        provider = OllamaRecommendationProvider(client=client)
        with pytest.raises(MissingPositiveEvidenceCitationError):
            await provider.generate_recommendation(
                recommendation_context,
                validate=require_citation,
            )

    assert calls == 2
    assert provider.repair_attempts_used == 1


@pytest.mark.parametrize("content", ["", "not-json"])
async def test_ollama_provider_rejects_empty_or_invalid_response(content: str) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:3b",
                "message": {"role": "assistant", "content": content},
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://ollama.test",
    ) as client:
        provider = OllamaRecommendationProvider(
            client=client,
            maximum_repair_attempts=0,
        )
        with pytest.raises(RecommendationResponseValidationError):
            await provider.generate_recommendation(context())


async def test_ollama_provider_stops_after_one_failed_repair() -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:3b",
                "message": {"role": "assistant", "content": "{}"},
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://ollama.test",
    ) as client:
        provider = OllamaRecommendationProvider(client=client)
        with pytest.raises(RecommendationResponseValidationError):
            await provider.generate_recommendation(context())

    assert calls == 2
    assert provider.repair_attempts_used == 1


async def test_ollama_provider_rejects_reported_model_mismatch() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "different-model",
                "message": {
                    "role": "assistant",
                    "content": valid_draft_json(),
                },
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://ollama.test",
    ) as client:
        with pytest.raises(RecommendationModelMismatchError):
            await OllamaRecommendationProvider(client=client).generate_recommendation(context())
