"""OpenAI (GPT, Responses API) client implementing the Model protocol."""
from __future__ import annotations

import json
import os
from typing import Any, TypeVar

import openai
import pydantic
from pydantic import BaseModel

from refiner.data import TokenUsage
from refiner.configuration import ModelSettings
from refiner.models.errors import ModelError, parsing_error, convert_exception

T = TypeVar("T", bound=BaseModel)

_SERVICE = "OpenAI"


class GptModel:
    def __init__(self, settings: ModelSettings, client: Any | None = None):
        self._n = settings
        self.name = settings.gpt.model
        self._usage: list[TokenUsage] = []
        if client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                raise ModelError('authentication', _SERVICE)
            try:
                client = openai.OpenAI(max_retries=settings.max_retries,
                                       timeout=settings.timeout_s)
            except Exception as exc:
                raise convert_exception(exc, _SERVICE) from exc
        self._client = client

    def _common(self, instructions: str, task: str) -> dict[str, Any]:
        n = self._n.gpt
        # Verified in openai 3.33.0: responses.parse and create accept all these
        # parameters directly. The protocol effort override is ignored; n.effort applies.
        return {"model": n.model, "instructions": instructions, "input": task,
                "reasoning": {"effort": n.effort}, "max_output_tokens": n.max_output_tokens}

    def _process(self, response: Any, step: str) -> None:
        u = response.usage
        details = getattr(u, "input_tokens_details", None)
        self._usage.append(TokenUsage(
            step=step, model=self.name, input_tokens=u.input_tokens, output_tokens=u.output_tokens,
            cache_read_tokens=(getattr(details, "cached_tokens", 0) or 0)))
        if response.status == "incomplete":
            reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
            raise ModelError('truncated', _SERVICE, detail=str(reason or ""))
        for item in response.output:
            for content in getattr(item, "content", None) or []:
                if getattr(content, "type", None) == "refusal":
                    raise ModelError('refused', _SERVICE, detail=str(content.refusal))

    def json(self, instructions: str, task: str, schema: type[T], *, step: str,
             effort: str | None = None) -> T:
        try:
            response = self._client.responses.parse(**self._common(instructions, task),
                                               text_format=schema)
            self._process(response, step)
            if response.output_parsed is None:
                raise ModelError('invalid_output', _SERVICE, detail="chybí output_parsed",
                                  raw_response=response.output_text)
            return response.output_parsed
        except ModelError:
            raise
        except (pydantic.ValidationError, json.JSONDecodeError) as exc:
            raise parsing_error(exc, _SERVICE) from exc
        except Exception as exc:
            raise convert_exception(exc, _SERVICE) from exc

    def text(self, instructions: str, task: str, *, step: str) -> str:
        try:
            response = self._client.responses.create(**self._common(instructions, task))
            self._process(response, step)
            return response.output_text
        except ModelError:
            raise
        except Exception as exc:
            raise convert_exception(exc, _SERVICE) from exc

    def take_usage(self) -> list[TokenUsage]:
        usage, self._usage = self._usage, []
        return usage
