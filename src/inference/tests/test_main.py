from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from inference.config import load_config
from inference.main import create_app
from inference.schema import OutputSchema
from inference.server import LlamaServerError, ModelNotReadyError, ModelStatus


class FakeLlamaServerManager:
    def __init__(self, config, *, state: str = "ready", error=None):
        self.config = config
        self._status = ModelStatus(
            state=state,
            model_id="gemma" if state == "ready" else None,
            error=error,
        )
        self.started = False
        self.stopped = False
        self.messages = None
        self.completion_error = None

    @property
    def status(self):
        return self._status

    def start(self):
        self.started = True
        return self._status

    def stop(self):
        self.stopped = True
        return ModelStatus(state="stopped", model_id=None)

    @contextmanager
    def inference(self):
        if self._status.state != "ready":
            raise ModelNotReadyError("The model is not ready for inference")
        yield self._status.model_id

    def chat_completion(self, messages):
        self.messages = messages
        if self.completion_error is not None:
            raise self.completion_error
        return {"text": "Hello!"}


def create_config(tmp_path: Path):
    executable = tmp_path / "llama-server.exe"
    model_path = tmp_path / "gemma.gguf"
    executable.touch()
    model_path.touch()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "server": {"host": "127.0.0.1", "port": 8001},
                "llama_server": {
                    "executable": str(executable),
                    "host": "127.0.0.1",
                    "port": 8080,
                    "startup_timeout": 10,
                    "shutdown_timeout": 5,
                },
                "models": {
                    "default": "gemma",
                    "available": {
                        "gemma": {
                            "name": "Gemma",
                            "path": str(model_path),
                            "context_size": 1024,
                            "gpu_layers": 0,
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return load_config(config_path)


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = create_config(tmp_path)
    manager = FakeLlamaServerManager(config)
    monkeypatch.setattr(
        "inference.main.LlamaServerManager", lambda _: manager
    )
    with TestClient(create_app(config)) as client:
        yield client, manager


def test_health_and_current_model_and_lifecycle(api) -> None:
    client, manager = api

    health = client.get("/health")
    current = client.get("/models/current")

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "model_status": "ready"}
    assert current.json() == {
        "model_id": "gemma",
        "name": "Gemma",
        "status": "ready",
    }
    assert manager.started


def test_lifespan_stops_manager_on_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = create_config(tmp_path)
    manager = FakeLlamaServerManager(config)
    monkeypatch.setattr(
        "inference.main.LlamaServerManager", lambda _: manager
    )

    with TestClient(create_app(config)):
        assert manager.started

    assert manager.stopped


def test_generate_builds_prompt_and_returns_text(api) -> None:
    client, manager = api

    response = client.post(
        "/generate",
        json={
            "system_prompt": "Be helpful.",
            "history": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
            ],
            "user_input": "How are you?",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"text": "Hello!"}
    assert manager.messages == [
        {
            "role": "user",
            "content": (
                "Be helpful.\n\n"
                "あなたは以下の会話履歴を参考にして、\n"
                "文脈を維持した回答をしてください。\n\n"
                "## 会話履歴\n\n"
                "[User]\nHi\n\n"
                "[Assistant]\nHello\n\n"
                "## ユーザーの入力\n\n"
                "How are you?"
            ),
        }
    ]


def test_generate_rejects_missing_fields(api) -> None:
    client, _ = api

    response = client.post("/generate", json={"system_prompt": "Be helpful."})

    assert response.status_code == 422


def test_generate_rejects_when_model_is_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = create_config(tmp_path)
    manager = FakeLlamaServerManager(config, state="stopped")
    monkeypatch.setattr(
        "inference.main.LlamaServerManager", lambda _: manager
    )

    with TestClient(create_app(config)) as client:
        response = client.post(
            "/generate",
            json={
                "system_prompt": "Be helpful.",
                "history": [],
                "user_input": "Hi",
            },
        )

    assert response.status_code == 503


def test_generate_maps_llama_server_error_to_bad_gateway(api) -> None:
    client, manager = api
    manager.completion_error = LlamaServerError("llama-server request failed")

    response = client.post(
        "/generate",
        json={"system_prompt": "Be helpful.", "history": [], "user_input": "Hi"},
    )

    assert response.status_code == 502


def test_generate_maps_invalid_output_to_bad_gateway(api) -> None:
    client, manager = api
    manager.completion_error = ValidationError.from_exception_data(
        "OutputSchema",
        [
            {
                "type": "string_type",
                "loc": ("text",),
                "input": 1,
            }
        ],
    )

    response = client.post(
        "/generate",
        json={"system_prompt": "Be helpful.", "history": [], "user_input": "Hi"},
    )

    assert response.status_code == 502
