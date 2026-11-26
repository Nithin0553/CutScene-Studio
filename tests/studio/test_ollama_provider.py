"""Provider unit tests; no Ollama server or engine is required."""
import json

import pytest

from packages.studio import ollama_provider as op

SCHEMA = {
    "type": "object",
    "properties": {"mapping_id": {"enum": ["skeletal_animation", "unsupported"]}},
    "required": ["mapping_id"],
    "additionalProperties": False,
}


@pytest.fixture
def transport(monkeypatch):
    requests = []
    replies = []
    closed = []

    class Response:
        def __init__(self, status, payload):
            self.status = status
            self.payload = payload

        def read(self, limit):
            return self.payload[:limit]

    class Connection:
        def __init__(self, host, port, timeout):
            self.host, self.port, self.timeout = host, port, timeout

        def request(self, method, path, body, headers):
            requests.append((self.host, self.port, self.timeout, method, path, body, headers))

        def getresponse(self):
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return Response(*reply)

        def close(self):
            closed.append(True)

    monkeypatch.setattr(op.http.client, "HTTPConnection", Connection)
    return requests, replies, closed


def reply(data, status=200):
    return status, json.dumps(data).encode()


def generation(data, **extra):
    return reply({
        "done": True,
        "done_reason": "stop",
        "response": json.dumps(data),
        "load_duration": 95_210_000_000,
        "total_duration": 102_370_000_000,
        "eval_count": 44,
        **extra,
    })


def test_model_list_and_structured_generation(transport):
    requests, replies, closed = transport
    replies.extend([
        reply({"models": [{"name": "qwen2.5:7b-instruct"}]}),
        generation({"mapping_id": "skeletal_animation"}),
    ])
    provider = op.OllamaProvider()
    assert provider.models() == ("qwen2.5:7b-instruct",)
    result = provider.generate("Select a known mapping", SCHEMA)
    assert result.data == {"mapping_id": "skeletal_animation"}
    assert result.load_seconds == 95.21
    assert result.total_seconds == 102.37
    assert result.generated_tokens == 44
    assert requests[0][3:5] == ("GET", "/api/tags")
    assert requests[1][3:5] == ("POST", "/api/generate")
    body = json.loads(requests[1][5])
    assert body["format"] == SCHEMA
    assert body["keep_alive"] == "2m"
    assert body["stream"] is False
    assert body["options"]["num_ctx"] == 2048
    assert len(closed) == 2


@pytest.mark.parametrize("data", [
    {"mapping_id": "invented"},
    {},
    {"mapping_id": "unsupported", "extra": True},
    ["skeletal_animation"],
])
def test_rejects_schema_invalid_output(transport, data):
    transport[1].append(generation(data))
    with pytest.raises(op.OllamaError, match="schema validation"):
        op.OllamaProvider().generate("Select a mapping", SCHEMA)


@pytest.mark.parametrize("response", [
    generation({"mapping_id": "unsupported"}, done_reason="length"),
    reply({"done": True, "done_reason": "stop", "response": "not JSON"}),
    reply({"error": "missing model"}, 404),
    (200, b"not JSON"),
    TimeoutError("timeout"),
])
def test_inference_failures(transport, response):
    transport[1].append(response)
    with pytest.raises(op.OllamaError):
        op.OllamaProvider().generate("Select a mapping", SCHEMA)
    assert transport[2] == [True]


@pytest.mark.parametrize("url", [
    "https://127.0.0.1:11434",
    "http://example.com:11434",
    "http://127.0.0.1:11434/path",
    "http://user@localhost:11434",
])
def test_rejects_nonlocal_endpoint(url):
    with pytest.raises(ValueError):
        op.OllamaProvider(base_url=url)


def test_unload(transport):
    transport[1].append(reply({"done": True}))
    op.OllamaProvider().unload()
    assert json.loads(transport[0][0][5])["keep_alive"] == 0


def test_invalid_schema_does_not_send_request(transport):
    with pytest.raises(ValueError, match="Invalid response schema"):
        op.OllamaProvider().generate("Select a mapping", {"type": "not-a-type"})
    assert not transport[0]


@pytest.mark.parametrize("error", [TimeoutError("timeout"), ConnectionRefusedError("refused")])
def test_transport_failure_preserves_exception_category(transport, error):
    transport[1].append(error)
    with pytest.raises(op.OllamaError, match=type(error).__name__):
        op.OllamaProvider().generate("Select a mapping", SCHEMA)
    assert transport[2] == [True]
