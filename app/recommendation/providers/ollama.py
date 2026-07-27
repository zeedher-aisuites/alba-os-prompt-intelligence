"""Ollama `/api/chat` adapter with bounded structured-output repair."""

from __future__ import annotations

import json
from typing import cast

import httpx
from pydantic import ValidationError

from app.recommendation.exceptions import (
    RecommendationError,
    RecommendationModelMismatchError,
    RecommendationProviderUnavailableError,
    RecommendationResponseValidationError,
)
from app.recommendation.protocol import RecommendationDraftValidator
from app.recommendation.schemas import RecommendationContext, RecommendationDraft

_OLLAMA_UNSUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {
        "default",
        "description",
        "format",
        "maxItems",
        "maxLength",
        "maxProperties",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "title",
    }
)


def ollama_recommendation_schema(
    context: RecommendationContext | None = None,
) -> dict[str, object]:
    """Project required fields and allowed IDs onto Ollama's grammar subset."""
    projected = cast(
        dict[str, object],
        _without_unsupported_schema_keywords(RecommendationDraft.model_json_schema()),
    )
    public_required = cast(list[str], projected["required"])
    public_properties = cast(dict[str, object], projected["properties"])
    required = [
        name
        for name in public_required
        if name not in {"covered_constraint_ids", "unmet_constraint_ids"}
    ]
    required.insert(required.index("provider_confidence"), "constraint_accounting")
    projected["required"] = required
    properties = {
        name: public_properties[name]
        for name in public_required
        if name not in {"covered_constraint_ids", "unmet_constraint_ids"}
    }
    properties["constraint_accounting"] = {
        "type": "object",
        "additionalProperties": {
            "type": "string",
            "enum": ["covered", "unmet"],
        },
    }
    projected["properties"] = properties
    properties["recommended_prompt"] = {
        **cast(dict[str, object], properties["recommended_prompt"]),
        "pattern": "^.+$",
    }
    properties["rationale"] = {"type": "string", "pattern": "^.+$"}
    if context is not None:
        has_evidence = bool(context.positive_evidence or context.failure_evidence)
        maximum_confidence_step = 20 if has_evidence else 6
        properties["provider_confidence"] = {
            "type": "number",
            "enum": [step / 20 for step in range(maximum_confidence_step + 1)],
        }
        _restrict_array_ids(
            properties,
            "used_positive_evidence_ids",
            [str(item.example_id) for item in context.positive_evidence],
        )
        constraint_ids = [item.constraint_id for item in context.constraints]
        if constraint_ids:
            properties["constraint_accounting"] = {
                "type": "object",
                "properties": {
                    identifier: {
                        "type": "string",
                        "enum": ["covered", "unmet"],
                    }
                    for identifier in constraint_ids
                },
                "required": constraint_ids,
                "additionalProperties": False,
            }
        else:
            properties["constraint_accounting"] = {"const": {}}
        rejected_ids = [str(item.example_id) for item in context.failure_evidence]
        if rejected_ids:
            definitions = cast(dict[str, object], projected["$defs"])
            warning = cast(dict[str, object], definitions["FailureWarning"])
            warning_properties = cast(dict[str, object], warning["properties"])
            warning_properties["evidence_id"] = {
                "type": "string",
                "enum": rejected_ids,
            }
            warning_properties["warning"] = {
                "type": "string",
                "pattern": "^.+$",
            }
        else:
            properties["failure_warnings"] = {"const": []}
    return projected


def _restrict_array_ids(
    properties: dict[str, object],
    field_name: str,
    allowed_ids: list[str],
) -> None:
    if not allowed_ids:
        properties[field_name] = {"const": []}
        return
    field_schema = cast(dict[str, object], properties[field_name])
    field_schema["items"] = {"type": "string", "enum": allowed_ids}


def _without_unsupported_schema_keywords(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _without_unsupported_schema_keywords(item)
            for key, item in cast(dict[str, object], value).items()
            if key not in _OLLAMA_UNSUPPORTED_SCHEMA_KEYWORDS
        }
    if isinstance(value, list):
        return [_without_unsupported_schema_keywords(item) for item in cast(list[object], value)]
    return value


class OllamaRecommendationProvider:
    """Generate a Pydantic-validated JSON recommendation using a local chat model."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model_name: str = "qwen2.5:3b",
        timeout_seconds: float = 60.0,
        maximum_output_tokens: int = 1_200,
        maximum_repair_attempts: int = 1,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if maximum_repair_attempts not in {0, 1}:
            raise ValueError("At most one structured-output repair attempt is allowed.")
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._timeout = httpx.Timeout(timeout_seconds)
        self._maximum_output_tokens = maximum_output_tokens
        self._maximum_repair_attempts = maximum_repair_attempts
        self._client = client
        self._repair_attempts_used = 0

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def repair_attempts_used(self) -> int:
        return self._repair_attempts_used

    async def generate_recommendation(
        self,
        context: RecommendationContext,
        *,
        validate: RecommendationDraftValidator | None = None,
    ) -> RecommendationDraft:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": context.system_prompt},
            {"role": "user", "content": context.user_prompt},
        ]
        for attempt in range(self._maximum_repair_attempts + 1):
            response_body = await self._request(messages, context)
            returned_model = response_body.get("model")
            if returned_model is not None and returned_model != self.model_name:
                raise RecommendationModelMismatchError(
                    "Ollama returned a different recommendation model."
                )
            content: str | None = None
            draft: RecommendationDraft | None = None
            try:
                content = self._content(response_body)
                draft = self._parse_draft(content)
                if validate is not None:
                    validate(draft)
                return draft
            except (
                RecommendationError,
                RecommendationResponseValidationError,
                ValidationError,
            ) as exc:
                if attempt >= self._maximum_repair_attempts:
                    if isinstance(exc, RecommendationError):
                        raise
                    raise RecommendationResponseValidationError(
                        "Ollama did not return a valid structured recommendation."
                    ) from exc
                self._repair_attempts_used += 1
                if content is not None:
                    messages = [*messages, {"role": "assistant", "content": content}]
                messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": self._repair_message(exc, context),
                    },
                ]
        raise AssertionError("Unreachable recommendation repair state.")

    @staticmethod
    def _parse_draft(content: str) -> RecommendationDraft:
        """Map the simpler Ollama wire rationale into the public list contract."""
        try:
            payload: object = json.loads(content)
        except ValueError as exc:
            raise RecommendationResponseValidationError(
                "The Ollama recommendation content is not valid JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise RecommendationResponseValidationError(
                "The Ollama recommendation content is not an object."
            )
        draft_payload = cast(dict[str, object], payload)
        rationale = draft_payload.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise RecommendationResponseValidationError(
                "The Ollama recommendation rationale is empty."
            )
        accounting = draft_payload.get("constraint_accounting")
        if not isinstance(accounting, dict):
            raise RecommendationResponseValidationError(
                "The Ollama constraint accounting is not an object."
            )
        covered: list[str] = []
        unmet: list[str] = []
        for identifier, status in cast(dict[str, object], accounting).items():
            if status == "covered":
                covered.append(identifier)
            elif status == "unmet":
                unmet.append(identifier)
            else:
                raise RecommendationResponseValidationError(
                    "The Ollama constraint accounting status is invalid."
                )
        normalized = {
            key: value for key, value in draft_payload.items() if key != "constraint_accounting"
        }
        return RecommendationDraft.model_validate(
            {
                **normalized,
                "rationale": [rationale],
                "covered_constraint_ids": covered,
                "unmet_constraint_ids": unmet,
            }
        )

    @staticmethod
    def _repair_message(
        error: RecommendationError | RecommendationResponseValidationError | ValidationError,
        context: RecommendationContext,
    ) -> str:
        if isinstance(error, ValidationError):
            details = [
                f"- {'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
                for item in error.errors(include_url=False, include_input=False)[:8]
            ]
        else:
            details = [f"- response: {error}"]
        constraint_ids = [item.constraint_id for item in context.constraints]
        approved_ids = [str(item.example_id) for item in context.positive_evidence]
        rejected_ids = [str(item.example_id) for item in context.failure_evidence]
        return (
            "The previous JSON failed validation:\n"
            + "\n".join(details)
            + f"\nValid constraint IDs: {constraint_ids}. "
            + f"Valid approved evidence IDs: {approved_ids}. "
            + f"Valid rejected evidence IDs: {rejected_ids}. "
            + "If an evidence ID list is empty, its corresponding output list "
            "must be exactly []. "
            + "\nReturn one complete corrected JSON object matching the schema. "
            "recommended_prompt must always be a useful non-empty prompt derived from "
            "the brief, even when no evidence exists. When no rejected evidence IDs "
            "exist, failure_warnings must be exactly []. Account for every supplied "
            "constraint ID exactly once in constraint_accounting as covered or unmet; "
            "when none exist, constraint_accounting must be exactly {}. Cite only "
            "supplied evidence IDs. "
            "Do not add markdown or commentary."
        )

    async def _request(
        self,
        messages: list[dict[str, str]],
        context: RecommendationContext,
    ) -> dict[str, object]:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "format": ollama_recommendation_schema(context),
            "options": {
                "temperature": 0,
                "num_predict": self._maximum_output_tokens,
            },
        }
        try:
            if self._client is None:
                async with httpx.AsyncClient(
                    base_url=self._base_url,
                    timeout=self._timeout,
                ) as client:
                    response = await client.post("/api/chat", json=payload)
            else:
                response = await self._client.post("/api/chat", json=payload)
            response.raise_for_status()
        except (httpx.HTTPError, OSError) as exc:
            raise RecommendationProviderUnavailableError(
                "The Ollama recommendation provider is unavailable."
            ) from exc
        try:
            body: object = response.json()
        except ValueError as exc:
            raise RecommendationResponseValidationError(
                "The Ollama recommendation response is not valid JSON."
            ) from exc
        if not isinstance(body, dict):
            raise RecommendationResponseValidationError(
                "The Ollama recommendation response is not an object."
            )
        return cast(dict[str, object], body)

    @staticmethod
    def _content(body: dict[str, object]) -> str:
        message = body.get("message")
        if not isinstance(message, dict):
            raise RecommendationResponseValidationError(
                "The Ollama recommendation response has no message object."
            )
        content = cast(dict[str, object], message).get("content")
        if not isinstance(content, str) or not content.strip():
            raise RecommendationResponseValidationError(
                "The Ollama recommendation response content is empty."
            )
        return content
