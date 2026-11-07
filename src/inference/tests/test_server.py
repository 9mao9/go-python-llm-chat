import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
import requests
from pydantic import ValidationError

from inference.schema import OutputSchema
from inference.server import LlamaServerManager, LlamaServerError


@contextmanager
def local_server(
    health_status: int = 200,
    chat_status: int = 200,
    chat_content: str = '{"text":"Hello from llama-server"}',
    response_json: dict | None = None,
    response_body: bytes | None = None,
):
    events = []
    payloads = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            events.append(("GET", self.path))
            self.send_response(health_status)
            self.end_headers()

        def do_POST(self) -> None:
            events.append(("POST", self.path))
            body = self.rfile.read(int(self.headers["Content-Length"]))
            payloads.append(json.loads(body))
            body = response_body
            if body is None:
                body = json.dumps(
                    response_json
                    if response_json is not None
                    else {"choices": [{"message": {"content": chat_content}}]}
                ).encode()
            self.send_response(chat_status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, events, payloads
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def create_manager(tmp_path: Path, port: int) -> LlamaServerManager:
    config_path = tmp_path / "config.yaml"
    executable = tmp_path / "llama-server.exe"
    model_path = tmp_path / "model.gguf"
    executable.touch()
    model_path.touch()
    config_path.write_text(
        yaml.safe_dump(
            {
                "server": {"host": "127.0.0.1", "port": 8001},
                "llama_server": {
                    "executable": str(executable),
                    "host": "127.0.0.1",
                    "port": port,
                    "startup_timeout": 10,
                    "shutdown_timeout": 5,
                },
                "models": {
                    "default": "test",
                    "available": {
                        "test": {
                            "name": "Test",
                            "path": str(model_path),
                            "context_size": 1024,
                            "gpu_layers": 0,
                        }
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    manager = LlamaServerManager(str(config_path))
    return manager


def test_chat_completion_checks_health_and_sends_payload(
    tmp_path: Path,
) -> None:
    with local_server() as (port, events, payloads):
        manager = create_manager(tmp_path, port)
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]

        result = manager.chat_completion(
            messages,
            max_tokens=512,
            temperature=0.8,
            top_p=0.9,
            top_k=64,
        )

        assert result == {"text": "Hello from llama-server"}
        assert events == [
            ("GET", "/health"),
            ("POST", "/v1/chat/completions"),
        ]
        assert payloads == [
            {
                "messages": messages,
                "max_tokens": 512,
                "temperature": 0.8,
                "top_p": 0.9,
                "top_k": 64,
                "stream": False,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "output",
                        "strict": True,
                        "schema": OutputSchema.model_json_schema(),
                    },
                },
            }
        ]


def test_chat_completion_does_not_send_payload_when_unhealthy(
    tmp_path: Path,
) -> None:
    with local_server(health_status=503) as (port, events, payloads):
        manager = create_manager(tmp_path, port)

        with pytest.raises(RuntimeError, match="not healthy"):
            manager.chat_completion([{"role": "user", "content": "Hello"}])

        assert events == [("GET", "/health")]
        assert payloads == []


def test_chat_completion_raises_for_http_error(tmp_path: Path) -> None:
    with local_server(chat_status=500) as (port, events, _):
        manager = create_manager(tmp_path, port)

        with pytest.raises(LlamaServerError, match="HTTP 500"):
            manager.chat_completion([{"role": "user", "content": "Hello"}])

        assert events == [
            ("GET", "/health"),
            ("POST", "/v1/chat/completions"),
        ]


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (requests.ConnectionError("connection refused"), "request failed"),
        (requests.Timeout("request timed out"), "timed out"),
    ],
)
def test_chat_completion_reports_connection_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: requests.RequestException,
    message: str,
) -> None:
    manager = create_manager(tmp_path, 8080)
    monkeypatch.setattr(manager, "is_health", lambda: True)
    post = Mock(side_effect=failure)
    monkeypatch.setattr("inference.server.requests.post", post)

    with pytest.raises(LlamaServerError, match=message):
        manager.chat_completion([{"role": "user", "content": "Hello"}])
    assert post.call_args.kwargs["timeout"] == 60


def test_chat_completion_reports_invalid_response_json(tmp_path: Path) -> None:
    with local_server(response_body=b"not json") as (port, _, _):
        manager = create_manager(tmp_path, port)

        with pytest.raises(LlamaServerError, match="invalid JSON"):
            manager.chat_completion([{"role": "user", "content": "Hello"}])


def test_chat_completion_reports_invalid_response_shape(tmp_path: Path) -> None:
    with local_server(response_json={"choices": []}) as (port, _, _):
        manager = create_manager(tmp_path, port)

        with pytest.raises(LlamaServerError, match="invalid response"):
            manager.chat_completion([{"role": "user", "content": "Hello"}])


def test_chat_completion_validates_model_output(tmp_path: Path) -> None:
    with local_server(chat_content='{"text":1}') as (port, _, _):
        manager = create_manager(tmp_path, port)

        with pytest.raises(ValidationError):
            manager.chat_completion([{"role": "user", "content": "Hello"}])


def test_health_check_is_false_when_server_is_unavailable(tmp_path: Path) -> None:
    manager = create_manager(tmp_path, 1)
    manager.is_running = False

    assert manager.is_health() is False
