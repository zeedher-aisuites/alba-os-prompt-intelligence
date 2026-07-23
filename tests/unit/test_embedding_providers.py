"""Provider adapter and vector-validation tests."""

from __future__ import annotations

import json
from math import nan

import httpx
import pytest
from app.embeddings.exceptions import (
    EmbeddingBatchSizeError,
    EmbeddingDimensionError,
    EmbeddingProviderUnavailableError,
    EmptyEmbeddingInputError,
    MalformedEmbeddingResponseError,
    NonFiniteEmbeddingError,
)
from app.embeddings.providers import FakeEmbeddingProvider, OllamaEmbeddingProvider


async def test_fake_provider_is_deterministic_and_preserves_batch_order() -> None:
    provider = FakeEmbeddingProvider(dimensions=8)

    first = await provider.embed_documents(["cobalt host", "amber product"])
    second = await provider.embed_documents(["cobalt host", "amber product"])
    query = await provider.embed_query("cobalt host")

    assert first == second
    assert query == first[0]
    assert len(first) == 2
    assert all(len(vector) == 8 for vector in first)


@pytest.mark.parametrize("texts", [[], [""], ["   "]])
async def test_fake_provider_rejects_empty_inputs(texts: list[str]) -> None:
    with pytest.raises(EmptyEmbeddingInputError):
        await FakeEmbeddingProvider().embed_documents(texts)


async def test_fake_provider_rejects_wrong_dimension_override() -> None:
    provider = FakeEmbeddingProvider(
        dimensions=3,
        vectors_by_text={"bad": [1.0, 2.0]},
    )

    with pytest.raises(EmbeddingDimensionError):
        await provider.embed_query("bad")


@pytest.mark.parametrize("value", [nan, float("inf"), float("-inf")])
async def test_fake_provider_rejects_non_finite_values(value: float) -> None:
    provider = FakeEmbeddingProvider(
        dimensions=2,
        vectors_by_text={"bad": [value, 0.0]},
    )

    with pytest.raises(NonFiniteEmbeddingError):
        await provider.embed_query("bad")


async def test_ollama_provider_uses_batch_endpoint_and_validates_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embed"
        request_body = json.loads(request.content)
        assert request_body["model"] == "embeddinggemma:300m"
        assert request_body["truncate"] is False
        return httpx.Response(
            200,
            json={
                "model": "embeddinggemma:300m",
                "embeddings": [[1.0, 0.0], [0.0, 1.0]],
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://ollama.test",
    ) as client:
        provider = OllamaEmbeddingProvider(
            dimensions=2,
            client=client,
        )
        vectors = await provider.embed_documents(["first", "second"])

    assert vectors == [[1.0, 0.0], [0.0, 1.0]]


@pytest.mark.parametrize(
    ("payload", "error_type"),
    [
        ({}, MalformedEmbeddingResponseError),
        (
            {"model": "different-model", "embeddings": [[1.0, 0.0], [0.0, 1.0]]},
            MalformedEmbeddingResponseError,
        ),
        (
            {"model": "embeddinggemma:300m", "embeddings": [[1.0, 0.0]]},
            EmbeddingBatchSizeError,
        ),
        (
            {"model": "embeddinggemma:300m", "embeddings": [[1.0], [0.0]]},
            EmbeddingDimensionError,
        ),
        (
            {
                "model": "embeddinggemma:300m",
                "embeddings": [[1.0, float("inf")], [0.0, 1.0]],
            },
            NonFiniteEmbeddingError,
        ),
    ],
)
async def test_ollama_provider_rejects_malformed_output(
    payload: dict[str, object],
    error_type: type[Exception],
) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        if error_type is NonFiniteEmbeddingError:
            return httpx.Response(
                200,
                content=(b'{"model":"embeddinggemma:300m","embeddings":[[1.0,1e309],[0.0,1.0]]}'),
                headers={"content-type": "application/json"},
            )
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://ollama.test",
    ) as client:
        provider = OllamaEmbeddingProvider(dimensions=2, client=client)
        with pytest.raises(error_type):
            await provider.embed_documents(["first", "second"])


async def test_ollama_provider_wraps_http_failure_without_response_details() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="internal model details")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://ollama.test",
    ) as client:
        provider = OllamaEmbeddingProvider(dimensions=2, client=client)
        with pytest.raises(EmbeddingProviderUnavailableError) as captured:
            await provider.embed_query("query")

    assert "internal model details" not in str(captured.value)
