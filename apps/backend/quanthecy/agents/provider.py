"""Bounded model adapters without SDK retries, redirects, or tool execution."""

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

ERROR_CODES = frozenset(
    {
        "provider_failed",
        "provider_timeout",
        "provider_network",
        "provider_auth",
        "provider_not_found",
        "provider_bad_request",
        "provider_quota",
        "provider_rate_limit",
        "provider_unavailable",
        "provider_output_limit",
        "provider_invalid_response",
    }
)


class ProviderFailure(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        raise ProviderFailure("provider_failed")


@dataclass(frozen=True)
class Connection:
    provider: str
    base_url: str
    model: str
    api_key: str = field(repr=False)
    max_output_tokens: int = 2000

    @property
    def timeout_seconds(self) -> int:
        return 300 if self.max_output_tokens > 8000 else 40

    @property
    def deadline_seconds(self) -> int:
        return self.timeout_seconds + 20

    @property
    def lease_seconds(self) -> int:
        return max(180, self.deadline_seconds + 60)

    @property
    def max_response_bytes(self) -> int:
        # Includes provider reasoning and JSON-escaped Unicode, not just report text.
        return min(8 * 1024 * 1024, max(131072, self.max_output_tokens * 96 + 65536))


def complete(connection: Connection, system: str, prompt: str) -> tuple[str, dict[str, int]]:
    token_field = "max_completion_tokens" if connection.provider == "openai" else "max_tokens"
    body = {
        "model": connection.model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        token_field: connection.max_output_tokens,
        "stream": False,
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if connection.api_key:
        headers["Authorization"] = f"Bearer {connection.api_key}"
    route = "/chat/completions"
    if connection.provider == "anthropic":
        route = "/messages"
        headers["anthropic-version"] = "2023-06-01"
        headers.pop("Authorization", None)
        if connection.api_key:
            headers["x-api-key"] = connection.api_key
        body = {
            "model": connection.model,
            "system": system + "\nReturn only a JSON object, without Markdown fences.",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": connection.max_output_tokens,
            "stream": False,
        }
    request = Request(
        connection.base_url + route,
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with build_opener(NoRedirect()).open(
            request, timeout=connection.timeout_seconds
        ) as response:
            raw = response.read(connection.max_response_bytes + 1)
        if len(raw) > connection.max_response_bytes:
            raise ProviderFailure("provider_failed")
        result = json.loads(raw)
        usage = result.get("usage") or {}
        if connection.provider == "anthropic":
            blocks = result["content"]
            if result.get("stop_reason") == "max_tokens":
                raise ProviderFailure("provider_output_limit")
            if (
                result.get("stop_reason") != "end_turn"
                or not isinstance(blocks, list)
                or not blocks
            ):
                raise ProviderFailure("provider_invalid_response")
            if any(not isinstance(block, dict) or block.get("type") != "text" for block in blocks):
                raise ProviderFailure("provider_failed")
            text = "".join(block["text"] for block in blocks)
            usage = {
                "prompt_tokens": usage.get("input_tokens"),
                "completion_tokens": usage.get("output_tokens"),
            }
        else:
            choice = result["choices"][0]
            text = choice["message"]["content"]
            if choice.get("finish_reason") == "length":
                raise ProviderFailure("provider_output_limit")
            if choice.get("finish_reason") != "stop":
                raise ProviderFailure("provider_invalid_response")
        if not isinstance(text, str) or len(text) > 262144:
            raise ProviderFailure("provider_failed")
        counts = {
            key: value
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if type(value := usage.get(key)) is int and value >= 0
        }
        return text, counts
    except HTTPError as exc:
        code = {
            400: "provider_bad_request",
            401: "provider_auth",
            403: "provider_auth",
            402: "provider_quota",
            404: "provider_not_found",
            408: "provider_timeout",
            429: "provider_rate_limit",
        }.get(exc.code, "provider_unavailable" if exc.code >= 500 else "provider_failed")
        exc.close()
        raise ProviderFailure(code) from None
    except TimeoutError:
        raise ProviderFailure("provider_timeout") from None
    except URLError as exc:
        code = "provider_timeout" if isinstance(exc.reason, TimeoutError) else "provider_network"
        raise ProviderFailure(code) from None
    except OSError:
        raise ProviderFailure("provider_network") from None
    except (ValueError, KeyError, IndexError, TypeError):
        # Never expose provider bodies, URLs, credentials, or raw exception text.
        raise ProviderFailure("provider_invalid_response") from None


def child_complete(pipe: Any, connection: Connection, system: str, prompt: str) -> None:
    try:
        pipe.send(("ok", complete(connection, system, prompt)))
    except ProviderFailure as exc:
        code = str(exc)
        pipe.send(("error", code if code in ERROR_CODES else "provider_failed"))
    except Exception:
        pipe.send(("error", "provider_failed"))
    finally:
        pipe.close()
