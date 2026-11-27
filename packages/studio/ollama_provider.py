"""Local Ollama transport for the single transfer agent.

This module performs inference only. It never executes a model's output or
modifies an engine. Callers must validate mapping semantics separately.
"""
from __future__ import annotations

import http.client
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, SchemaError, ValidationError


class OllamaError(RuntimeError):
    """The local model service could not complete a valid request."""


@dataclass(frozen=True)
class InferenceResult:
    data: dict[str, Any]
    total_seconds: float | None
    load_seconds: float | None
    prompt_seconds: float | None
    generation_seconds: float | None
    generated_tokens: int | None


def _seconds(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    return value / 1e9 if type(value) is int and value >= 0 else None


class OllamaProvider:
    """Bounded, non-streaming JSON requests to a local Ollama instance."""

    def __init__(
        self,
        model: str = "qwen2.5:7b-instruct",
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 240,
        num_ctx: int = 2048,
        num_predict: int = 256,
        keep_alive: str = "2m",
    ) -> None:
        url = urlsplit(base_url)
        if (
            url.scheme != "http"
            or url.hostname not in ("localhost", "127.0.0.1", "::1")
            or url.username is not None
            or url.password is not None
            or url.path not in ("", "/")
            or url.query
            or url.fragment
        ):
            raise ValueError("Ollama endpoint must be a local HTTP origin")
        if not model.strip() or not 0 < timeout <= 600:
            raise ValueError("Invalid model or timeout")
        if not 512 <= num_ctx <= 8192 or not 1 <= num_predict <= 2048:
            raise ValueError("Inference limits out of range")
        self.host = "127.0.0.1" if url.hostname == "localhost" else url.hostname
        self.port = url.port or 11434
        self.model = model
        self.timeout = timeout
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.keep_alive = keep_alive

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        # Direct HTTP avoids environment proxies and redirecting project data.
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            encoded = None if body is None else json.dumps(body, allow_nan=False)
            conn.request(method, path, body=encoded, headers={"Content-Type": "application/json"})
            response = conn.getresponse()
            if response.status != 200:
                raise OllamaError(f"Ollama HTTP {response.status} at {path}")
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise OllamaError("Ollama response exceeded size limit")
            result = json.loads(raw)
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise OllamaError(
                f"Local Ollama request failed at {path} ({type(exc).__name__})"
            ) from exc
        finally:
            conn.close()
        if not isinstance(result, dict) or "error" in result:
            raise OllamaError("Invalid Ollama response")
        return result

    def models(self) -> tuple[str, ...]:
        payload = self._request("GET", "/api/tags")
        models = payload.get("models")
        if not isinstance(models, list):
            raise OllamaError("Invalid model listing")
        return tuple(
            item["name"]
            for item in models
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        )

    def running_models(self) -> tuple[str, ...]:
        """Inspect resident models without generating, loading or unloading."""
        payload = self._request("GET", "/api/ps")
        models = payload.get("models")
        if not isinstance(models, list):
            raise OllamaError("Invalid running model listing")
        names = []
        for item in models:
            if not isinstance(item, dict):
                raise OllamaError("Invalid running model entry")
            name = item.get("name") or item.get("model")
            if not isinstance(name, str) or not name.strip():
                raise OllamaError("Invalid running model identity")
            names.append(name)
        return tuple(sorted(set(names)))

    def memory_status(self) -> dict[str, Any]:
        """Fail closed on ambiguous responses, never unload shared models.

        A refused connection means this endpoint is not listening, not proof
        that all system/GPU memory is free. Evidence replay needs no server.
        """
        try:
            running = self.running_models()
        except OllamaError as exc:
            if isinstance(exc.__cause__, ConnectionRefusedError):
                return {"status": "SERVICE_OFFLINE", "ready": True, "running_models": [],
                        "reason": "Local Ollama is not listening; model memory was not measured."}
            return {"status": "MEMORY_STATUS_UNKNOWN", "ready": False, "running_models": [],
                    "reason": "Cannot inspect local Ollama model residency. Retry or close Ollama safely."}
        if running:
            return {"status": "MODELS_RESIDENT", "ready": False, "running_models": list(running),
                    "reason": "Ollama models remain loaded. Wait for idle expiry or close Ollama when safe."}
        return {"status": "NO_RESIDENT_MODELS", "ready": True, "running_models": [],
                "reason": "Ollama reports no resident models."}

    def generate(self, prompt: str, schema: dict[str, Any]) -> InferenceResult:
        if not prompt.strip() or len(prompt) > 64000:
            raise ValueError("Prompt is empty or exceeds the character limit")
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise ValueError("Invalid response schema") from exc
        payload = self._request(
            "POST",
            "/api/generate",
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": schema,
                "keep_alive": self.keep_alive,
                "options": {
                    "temperature": 0,
                    "num_ctx": self.num_ctx,
                    "num_predict": self.num_predict,
                },
            },
        )
        if payload.get("done") is not True or payload.get("done_reason") != "stop":
            raise OllamaError("Inference did not complete normally")
        try:
            data = json.loads(payload["response"])
            if not isinstance(data, dict):
                raise TypeError("Expected object")
            Draft202012Validator(schema).validate(data)
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise OllamaError("Model output failed JSON schema validation") from exc
        count = payload.get("eval_count")
        return InferenceResult(
            data=data,
            total_seconds=_seconds(payload, "total_duration"),
            load_seconds=_seconds(payload, "load_duration"),
            prompt_seconds=_seconds(payload, "prompt_eval_duration"),
            generation_seconds=_seconds(payload, "eval_duration"),
            generated_tokens=count if type(count) is int and count >= 0 else None,
        )

    def unload(self) -> None:
        """Explicit unload for a caller that owns the model session exclusively."""
        payload = self._request(
            "POST", "/api/generate",
            {"model": self.model, "stream": False, "keep_alive": 0},
        )
        if payload.get("done") is not True:
            raise OllamaError("Model unload did not complete")
