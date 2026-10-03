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
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Fastino response has no chat completion: {data!r}") from exc
