"""Optional model providers used only by stochastic benchmark commands."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _env_aliases(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _load_local_env() -> None:
    env_path = Path(__file__).resolve().with_name(".env")
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        if key and key not in os.environ:
            os.environ[key] = value.strip("\"'")


_load_local_env()


class ModelProvider(Protocol):
    name: str
    model: str | None

    def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        seed: int | None = None,
        max_tokens: int | None = None,
    ) -> str: ...


class ResponseCache:
    """A deterministic on-disk cache keyed by provider request metadata."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._entries: dict[str, dict[str, Any]] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self._entries[row["key"]] = row

    @staticmethod
    def key(payload: dict[str, Any]) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

    def get(self, payload: dict[str, Any]) -> str | None:
        row = self._entries.get(self.key(payload))
        return None if row is None else str(row["response"])

    def put(self, payload: dict[str, Any], response: str) -> None:
        key = self.key(payload)
        row = {"key": key, "request": payload, "response": response}
        self._entries[key] = row
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _coerce_text(value: Any) -> str:
    if value is None:
        raise ValueError("Fastino decision value is missing")
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _normalize_branch_value(value: Any, *, field: str) -> str:
    text = _coerce_text(value).lower()
    if text in {"good", "bad"}:
        return text
    raise ValueError(
        "Fastino response does not contain a valid good/bad "
        f"'{field}' value or left/right branch pair; "
        f"got {value!r}"
    )


def _branch_value_for_record(value: Any, *, field: str) -> str:
    if isinstance(value, dict):
        if field in value:
            return _normalize_branch_value(value[field], field=field)
        if set(value) == {"label"}:
            return _normalize_branch_value(value["label"], field=field)
        raise ValueError(f"Fastino response has no valid '{field}' branch value: {value!r}")
    return _normalize_branch_value(value, field=field)


def _extract_left_right(response: Any) -> dict[str, str]:
    if isinstance(response, str):
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Fastino response is not valid JSON: {response!r}") from exc
        return _extract_left_right(parsed)
    if not isinstance(response, dict):
        raise ValueError(f"Fastino response is not a dict-like structured decision: {response!r}")
    if {"left", "right"}.issubset(response):
        return {
            "left": _branch_value_for_record(response["left"], field="left"),
            "right": _branch_value_for_record(response["right"], field="right"),
        }
    if "intent" in response and "label" in response["intent"]:
        raise ValueError(
            "Fastino returned a single structured classification instead "
            "of independent left/right decisions; "
            "ask the model for two independent branch questions and map them to left/right."
        )
    if "left" in response or "right" in response:
        left = response.get("left")
        right = response.get("right")
        if left is None or right is None:
            raise ValueError(
                "Fastino response is missing one branch value; expected left/right pair: "
                f"{response!r}"
            )
        return {
            "left": _branch_value_for_record(left, field="left"),
            "right": _branch_value_for_record(right, field="right"),
        }
    raise ValueError(
        "Fastino response does not contain independent left/right labels; "
        "expected a valid good/bad decision or a left/right branch pair."
    )


class FastinoProvider:
    """Pioneer/Fastino OpenAI-compatible chat-completions provider.

    It is intentionally not used by pytest or the default benchmark mode.
    """

    name = "fastino"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = api_key or _env_aliases("FASTINO_API_KEY", "FASTINO_LABS_API_KEY")
        self.base_url = (
            base_url
            or _env_aliases("FASTINO_BASE_URL", "FASTINO_LABS_BASE_URL")
            or "https://api.fastino.ai/v1"
        ).rstrip("/")
        self.model = model or _env_aliases("FASTINO_MODEL", "FASTINO_LABS_MODEL")

    def request_payload(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        seed: int | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        if not self.model:
            raise RuntimeError(
                "FASTINO_MODEL is not set; pass --model or export FASTINO_MODEL/FASTINO_LABS_MODEL."
            )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if seed is not None:
            payload["seed"] = seed
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload

    def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        seed: int | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if not self.api_key:
            raise RuntimeError(
                "FASTINO_API_KEY/FASTINO_LABS_API_KEY is not set; "
                "export it before using --provider fastino."
            )
        payload = self.request_payload(
            messages, temperature=temperature, seed=seed, max_tokens=max_tokens
        )
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=60) as response:  # noqa: S310 - explicit opt-in endpoint
                data = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"Fastino request failed: {exc}") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Fastino response has no chat completion: {data!r}") from exc
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            return json.dumps(content, sort_keys=True)
        return str(content)

    @staticmethod
    def parse_decision_response(response: Any, *, field: str = "decision") -> str:
        try:
            payload = json.loads(response) if isinstance(response, str) else response
        except (TypeError, ValueError):
            payload = response
        if isinstance(payload, dict) and {"left", "right"}.issubset(payload):
            left_right = _extract_left_right(payload)
            if field in {"left", "right"}:
                return left_right[field]
            return left_right["left"] if "left" in left_right else left_right["right"]
        if isinstance(payload, dict) and ("left" in payload or "right" in payload):
            raise ValueError(
                "Fastino response is missing one branch value; expected left/right pair: "
                f"{payload!r}"
            )
        if isinstance(payload, dict):
            if field in payload:
                return _normalize_branch_value(payload[field], field=field)
            if set(payload) == {"label"}:
                return _normalize_branch_value(payload["label"], field=field)
        if isinstance(payload, str):
            text = payload.strip().lower()
            if text in {"good", "bad"}:
                return text
        raise ValueError(
            "Fastino decision response has no valid good/bad label; "
            f"got {response!r}"
        )

    def generate_decision(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        seed: int | None = None,
        max_tokens: int | None = None,
    ) -> str:
        raw = self.generate(messages, temperature=temperature, seed=seed, max_tokens=max_tokens)
        return self.parse_decision_response(raw, field="decision")

    def generate_pair(
        self,
        left_messages: list[dict[str, Any]],
        right_messages: list[dict[str, Any]],
        *,
        temperature: float,
        seed: int | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, str]:
        left_value = self.generate_decision(
            left_messages,
            temperature=temperature,
            seed=seed,
            max_tokens=max_tokens,
        )
        right_value = self.generate_decision(
            right_messages,
            temperature=temperature,
            seed=(seed + 1) if seed is not None else None,
            max_tokens=max_tokens,
        )
        if left_value == right_value and left_value in {"good", "bad"}:
            # This is a valid result only when the model intentionally returned the same
            # decision on both branches; the benchmark still needs independent values.
            return {"left": left_value, "right": right_value}
        return {"left": left_value, "right": right_value}
