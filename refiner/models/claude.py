"""Anthropic (Claude) client implementing the Model protocol."""
from __future__ import annotations

import json
import os
from typing import Any, TypeVar

import anthropic
import pydantic
from pydantic import BaseModel

from refiner.data import Spotreba as TokenUsage
from refiner.configuration import ModelSettings
from refiner.models.errors import ModelError, parsing_error, convert_exception

T = TypeVar("T", bound=BaseModel)

_SERVICE = "Anthropic"
_BETA_FALLBACK = "server-side-fallback-2026-07-01"


class ClaudeModel:
    def __init__(self, settings: ModelSettings, client: Any | None = None):
        self._n = settings
        self.name = settings.claude.model
        self._usage: list[TokenUsage] = []
        if client is None:
            # Anthropic() delays missing-key failures until the first request.
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise ModelError('authentication', _SERVICE)
            try:
                client = anthropic.Anthropic(max_retries=settings.max_retries,
                                             timeout=settings.timeout_s)
            except Exception as exc:
                raise convert_exception(exc, _SERVICE) from exc
        self._client = client

    def _common(self, instructions: str, task: str, effort: str | None) -> dict[str, Any]:
        n = self._n.claude
        kw: dict[str, Any] = {
            "model": n.model,
            "system": [{"type": "text", "text": instructions,
                        "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": task}],
            "output_config": {"effort": effort or n.effort},
        }
        # Verified in anthropic 1.15.0: beta.messages.parse and stream accept `betas`,
        # `fallbacks`, `output_config`, and `output_format` directly; no extra_body is needed.
        # `thinking` is omitted (Opus 5.5 uses adaptive thinking).
        if n.fallback:
            kw["betas"] = [_BETA_FALLBACK]
            kw["fallbacks"] = "default"
        return kw

    @staticmethod
    def _message_text(msg: Any) -> str:
        return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")

    def _process(self, msg: Any, step: str) -> None:
        """Record usage (tokens are billed on errors too) and convert stop_reason to an error."""
        u = msg.usage
        self._usage.append(TokenUsage(
            krok=step, model=self.name, vstup=u.input_tokens, vystup=u.output_tokens,
            cache_cteni=u.cache_read_input_tokens or 0,
            cache_zapis=getattr(u, "cache_creation_input_tokens", None) or 0))
        if msg.stop_reason == "refusal":
            category = getattr(getattr(msg, "stop_details", None), "category", None)
            raise ModelError('refused', _SERVICE, detail=str(category or "nespecifikováno"))
        if msg.stop_reason == "max_tokens":
            raise ModelError('truncated', _SERVICE)

    def json(self, instructions: str, task: str, schema: type[T], *, step: str,
             effort: str | None = None) -> T:
        kw = self._common(instructions, task, effort)
        try:
            # Stream JSON too: thinking tokens count toward max_tokens, requiring a high limit.
            # The SDK rejects non-streaming calls with high max_tokens because they can take too long.
            # Verified in anthropic 1.15.0: BetaMessageStream accepts output_format and fills
            # parsed_output at content_block_stop; parsing errors occur while reading the stream.
            with self._client.beta.messages.stream(
                    **kw, max_tokens=self._n.claude.max_tokens_json, output_format=schema) as stream:
                msg = stream.get_final_message()
            self._process(msg, step)
            if msg.parsed_output is None:
                raise ModelError('invalid_output', _SERVICE, detail="chybí parsed_output",
                                  raw_response=self._message_text(msg))
            return msg.parsed_output
        except ModelError:
            raise
        except (pydantic.ValidationError, json.JSONDecodeError) as exc:
            raise parsing_error(exc, _SERVICE) from exc
        except Exception as exc:
            raise convert_exception(exc, _SERVICE) from exc

    def text(self, instructions: str, task: str, *, step: str) -> str:
        kw = self._common(instructions, task, None)
        try:
            with self._client.beta.messages.stream(
                    **kw, max_tokens=self._n.claude.max_tokens_text) as stream:
                msg = stream.get_final_message()
            self._process(msg, step)
            return self._message_text(msg)
        except ModelError:
            raise
        except Exception as exc:
            raise convert_exception(exc, _SERVICE) from exc

    def take_usage(self) -> list[TokenUsage]:
        usage, self._usage = self._usage, []
        return usage
