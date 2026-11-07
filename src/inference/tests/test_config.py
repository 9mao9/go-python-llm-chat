from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from inference.config import ConfigError, load_config
from inference.main import create_app


def _configuration(tmp_path: Path) -> dict:
    executable = tmp_path / "bin" / "llama-server.exe"
    executable.parent.mkdir()
    executable.touch()
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "gemma.gguf").touch()
    (tmp_path / "models" / "qwen.gguf").touch()
    return {
        "server": {"host": "127.0.0.1", "port": 8001},
        "llama_server": {
            "executable": str(executable),
            "host": "127.0.0.1",
            "port": 8080,
            "startup_timeout": 120,
            "shutdown_timeout": 10,
        },
        "models": {
            "default": "gemma",
            "available": {
                "gemma": {
                    "name": "Gemma",
                    "path": "models/gemma.gguf",
                    "context_size": 8192,
                    "gpu_layers": 99,
                },
                "qwen": {
                    "name": "Qwen",
                    "path": "models/qwen.gguf",
                    "context_size": 4096,
                    "gpu_layers": -1,
                },
            },
        },
    }


def _write_config(tmp_path: Path, data: dict) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return config_path


def test_loads_valid_configuration_and_all_models(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path, _configuration(tmp_path))

    config = load_config(config_path)

    assert config.server.host == "127.0.0.1"
    assert config.server.port == 8001
    assert config.llama_server.port == 8080
    assert config.models.default == "gemma"
    assert set(config.models.available) == {"gemma", "qwen"}
    assert config.models.available["qwen"].gpu_layers == -1


def test_missing_required_setting_is_reported(tmp_path: Path) -> None:
    data = _configuration(tmp_path)
    del data["server"]["port"]
    config_path = _write_config(tmp_path, data)

    with pytest.raises(ConfigError, match="server.port"):
        load_config(config_path)


@pytest.mark.parametrize("port", [0, 65536])
def test_rejects_invalid_port(tmp_path: Path, port: int) -> None:
    data = _configuration(tmp_path)
    data["server"]["port"] = port
    config_path = _write_config(tmp_path, data)

    with pytest.raises(ConfigError, match="server.port"):
        load_config(config_path)


@pytest.mark.parametrize("timeout", [0, -1])
def test_rejects_invalid_timeout(tmp_path: Path, timeout: int) -> None:
    data = _configuration(tmp_path)
    data["llama_server"]["startup_timeout"] = timeout
    config_path = _write_config(tmp_path, data)

    with pytest.raises(ConfigError, match="llama_server.startup_timeout"):
        load_config(config_path)


def test_rejects_missing_llama_server_executable(tmp_path: Path) -> None:
    data = _configuration(tmp_path)
    data["llama_server"]["executable"] = "missing.exe"
    config_path = _write_config(tmp_path, data)

    with pytest.raises(ConfigError, match="llama_server.executable"):
        load_config(config_path)


def test_rejects_missing_model_file(tmp_path: Path) -> None:
    data = _configuration(tmp_path)
    data["models"]["available"]["qwen"]["path"] = "models/missing.gguf"
    config_path = _write_config(tmp_path, data)

    with pytest.raises(ConfigError, match="models.available.qwen.path"):
        load_config(config_path)


def test_rejects_default_model_not_in_available(tmp_path: Path) -> None:
    data = _configuration(tmp_path)
    data["models"]["default"] = "unknown"
    config_path = _write_config(tmp_path, data)

    with pytest.raises(ConfigError, match="models.default"):
        load_config(config_path)


def test_resolves_relative_paths_from_application_root(tmp_path: Path) -> None:
    data = _configuration(tmp_path)
    data["llama_server"]["executable"] = "bin/llama-server.exe"
    config_path = _write_config(tmp_path, data)

    config = load_config(config_path, app_root=tmp_path)

    assert config.llama_server.executable == (tmp_path / "bin" / "llama-server.exe").resolve()
    assert config.models.available["gemma"].path == (
        tmp_path / "models" / "gemma.gguf"
    ).resolve()


def test_preserves_absolute_paths(tmp_path: Path) -> None:
    data = _configuration(tmp_path)
    data["models"]["available"] = {"gemma": data["models"]["available"]["gemma"]}
    absolute_executable = tmp_path / "bin" / "llama-server.exe"
    absolute_model = tmp_path / "models" / "gemma.gguf"
    data["llama_server"]["executable"] = str(absolute_executable)
    data["models"]["available"]["gemma"]["path"] = str(absolute_model)
    config_path = _write_config(tmp_path, data)

    config = load_config(config_path, app_root=tmp_path / "different-root")

    assert config.llama_server.executable == absolute_executable
    assert config.models.available["gemma"].path == absolute_model


def test_app_lifespan_uses_validated_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _write_config(tmp_path, _configuration(tmp_path))
    config = load_config(config_path)
    manager = type(
        "FakeManager",
        (),
        {
            "config": config,
            "start": lambda self: None,
            "stop": lambda self: None,
        },
    )()
    monkeypatch.setattr("inference.main.LlamaServerManager", lambda _: manager)
    app = create_app(config)

    async def verify_lifespan() -> None:
        async with app.router.lifespan_context(app):
            assert app.state.config is config
            assert app.state.llama_server is manager

    asyncio.run(verify_lifespan())
