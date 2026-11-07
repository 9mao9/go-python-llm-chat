import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from inference.server import (
    LlamaServerError,
    LlamaServerManager,
    ModelNotReadyError,
)


class FakeProcess:
    def __init__(
        self,
        returncode: int | None = None,
        force_timeout: bool = False,
    ) -> None:
        self.returncode = returncode
        self.force_timeout = force_timeout
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        if not self.force_timeout:
            self.returncode = 0

    def wait(self, timeout: float) -> int:
        if self.force_timeout and not self.killed:
            raise subprocess.TimeoutExpired("llama-server", timeout)
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def create_config(tmp_path: Path, default_model: str = "gemma"):
    executable = tmp_path / "bin dir" / "llama server.exe"
    executable.parent.mkdir()
    executable.touch()
    gemma_path = tmp_path / "models" / "Gemma 4" / "model file.gguf"
    qwen_path = tmp_path / "models" / "qwen.gguf"
    gemma_path.parent.mkdir(parents=True)
    gemma_path.touch()
    qwen_path.touch()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "server": {"host": "127.0.0.1", "port": 8001},
                "llama_server": {
                    "executable": str(executable),
                    "host": "127.0.0.1",
                    "port": 8080,
                    "startup_timeout": 1,
                    "shutdown_timeout": 1,
                    "extra_args": ["--flash-attn", "on", "-n", "1024", "--jinja"],
                },
                "models": {
                    "default": default_model,
                    "available": {
                        "gemma": {
                            "name": "Gemma",
                            "path": str(gemma_path),
                            "context_size": 8192,
                            "gpu_layers": "all",
                        },
                        "qwen": {
                            "name": "Qwen",
                            "path": str(qwen_path),
                            "context_size": 4096,
                            "gpu_layers": 99,
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return config_path


def mock_processes(monkeypatch, force_timeout=False, returncode=None):
    processes = []

    def popen(args, **kwargs):
        process = FakeProcess(
            returncode=returncode,
            force_timeout=force_timeout,
        )
        processes.append(process)
        return process

    monkeypatch.setattr("inference.server.subprocess.Popen", popen)
    return processes


def use_healthy_server(monkeypatch) -> None:
    monkeypatch.setattr(
        "inference.server.requests.get",
        lambda *args, **kwargs: SimpleNamespace(status_code=200),
    )


def start_manager(tmp_path: Path, monkeypatch, **process_options):
    use_healthy_server(monkeypatch)
    processes = mock_processes(monkeypatch, **process_options)
    manager = LlamaServerManager(str(create_config(tmp_path)))
    manager.start()
    return manager, processes


def test_build_command_uses_default_model_arguments(tmp_path: Path) -> None:
    config_path = create_config(tmp_path)
    manager = LlamaServerManager(str(config_path))
    config = manager.config

    assert manager.build_command() == [
        str(config.llama_server.executable),
        "-m",
        str(config.models.available["gemma"].path),
        "--host",
        "127.0.0.1",
        "--port",
        "8080",
        "--ctx-size",
        "8192",
        "--gpu-layers",
        "all",
        "--flash-attn",
        "on",
        "-n",
        "1024",
        "--jinja",
    ]


def test_start_uses_configured_default_model(
    tmp_path: Path, monkeypatch
) -> None:
    config_path = create_config(tmp_path, default_model="qwen")
    manager = LlamaServerManager(str(config_path))
    config = manager.config
    use_healthy_server(monkeypatch)
    mock_processes(monkeypatch)

    status = manager.start()

    assert status.model_id == "qwen"
    assert manager.build_command()[2] == str(config.models.available["qwen"].path)


def test_paths_with_spaces_remain_single_arguments(tmp_path: Path) -> None:
    manager = LlamaServerManager(str(create_config(tmp_path)))

    command = manager.build_command()

    assert command[0] == str(manager.config.llama_server.executable)
    assert command[2] == str(manager.config.models.available["gemma"].path)
    assert command.count(command[0]) == 1
    assert command.count(command[2]) == 1


def test_start_keeps_process_and_sets_ready(tmp_path: Path, monkeypatch) -> None:
    manager, processes = start_manager(tmp_path, monkeypatch)

    assert manager.status.state == "ready"
    assert manager.status.model_id == "gemma"
    assert manager.process is processes[0]
    assert processes[0].terminated is False


def test_process_receives_argument_list_without_shell(
    tmp_path: Path, monkeypatch
) -> None:
    calls = []

    def popen(args, **kwargs):
        calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr("inference.server.subprocess.Popen", popen)
    use_healthy_server(monkeypatch)
    manager = LlamaServerManager(str(create_config(tmp_path)))

    manager.start()

    args, kwargs = calls[0]
    assert isinstance(args, list)
    assert kwargs["shell"] is False
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL


def test_startup_timeout_sets_error_and_stops_owned_process(
    tmp_path: Path, monkeypatch
) -> None:
    processes = mock_processes(monkeypatch)
    monkeypatch.setattr(
        "inference.server.requests.get",
        lambda *args, **kwargs: SimpleNamespace(status_code=503),
    )
    manager = LlamaServerManager(str(create_config(tmp_path)))

    with pytest.raises(LlamaServerError, match="did not become ready"):
        manager.start()

    assert manager.status.state == "error"
    assert manager.process is None
    assert processes[0].terminated


def test_executable_start_error_is_reported(tmp_path: Path, monkeypatch) -> None:
    popen = Mock(side_effect=OSError("not executable"))
    monkeypatch.setattr(
        "inference.server.subprocess.Popen",
        popen,
    )
    manager = LlamaServerManager(str(create_config(tmp_path)))

    with pytest.raises(LlamaServerError, match="Unable to start"):
        manager.start()

    assert manager.status.state == "error"
    assert "not executable" in manager.status.error


def test_process_exit_during_startup_sets_error(tmp_path: Path, monkeypatch) -> None:
    processes = mock_processes(monkeypatch, returncode=1)
    manager = LlamaServerManager(str(create_config(tmp_path)))

    with pytest.raises(LlamaServerError, match="exited before becoming ready"):
        manager.start()

    assert manager.status.state == "error"
    assert manager.status.model_id is None
    assert manager.process is None
    assert processes[0].terminated is False


def test_stop_waits_for_process_and_sets_stopped(tmp_path: Path, monkeypatch) -> None:
    manager, processes = start_manager(tmp_path, monkeypatch)

    status = manager.stop()

    assert processes[0].terminated
    assert manager.process is None
    assert status.state == "stopped"


def test_stop_kills_process_after_shutdown_timeout(tmp_path: Path, monkeypatch) -> None:
    manager, processes = start_manager(
        tmp_path, monkeypatch, force_timeout=True
    )

    manager.stop()

    assert processes[0].terminated
    assert processes[0].killed
    assert manager.status.state == "stopped"


def test_exit_handler_stops_managed_process(
    tmp_path: Path, monkeypatch
) -> None:
    callbacks = []
    monkeypatch.setattr(
        "inference.server.atexit.register",
        lambda callback: callbacks.append(callback),
    )
    manager, processes = start_manager(tmp_path, monkeypatch)

    assert len(callbacks) == 1
    callbacks[0]()

    assert processes[0].terminated
    assert manager.status.state == "stopped"


def test_unexpected_process_exit_updates_status(
    tmp_path: Path, monkeypatch
) -> None:
    manager, processes = start_manager(tmp_path, monkeypatch)
    processes[0].returncode = 2

    status = manager.status

    assert status.state == "error"
    assert "exited unexpectedly" in status.error


def test_start_uses_configured_default_model(tmp_path: Path, monkeypatch) -> None:
    manager, _ = start_manager(tmp_path, monkeypatch)

    assert manager.current_model_id == manager.config.models.default


def test_stop_waits_for_active_inference(tmp_path: Path, monkeypatch) -> None:
    manager, processes = start_manager(tmp_path, monkeypatch)
    inference_started = threading.Event()
    release_inference = threading.Event()
    stop_errors = []

    def run_inference() -> None:
        with manager.inference():
            inference_started.set()
            release_inference.wait(timeout=2)

    def stop_server() -> None:
        try:
            manager.stop()
        except Exception as exc:
            stop_errors.append(exc)

    inference_thread = threading.Thread(target=run_inference)
    inference_thread.start()
    assert inference_started.wait(timeout=2)
    stop_thread = threading.Thread(target=stop_server)
    stop_thread.start()

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if manager.status.state == "stopping":
            break
        time.sleep(0.01)
    else:
        pytest.fail("Stop did not wait for active inference")

    with pytest.raises(ModelNotReadyError):
        with manager.inference():
            pass

    assert not processes[0].terminated
    release_inference.set()
    inference_thread.join(timeout=2)
    stop_thread.join(timeout=2)

    assert not inference_thread.is_alive()
    assert not stop_thread.is_alive()
    assert not stop_errors
    assert manager.status.state == "stopped"


def test_concurrent_start_is_rejected(tmp_path: Path, monkeypatch) -> None:
    mock_processes(monkeypatch)
    manager = LlamaServerManager(str(create_config(tmp_path)))
    health_started = threading.Event()
    release_health = threading.Event()

    def get_health(*args, **kwargs):
        health_started.set()
        release_health.wait(timeout=2)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr("inference.server.requests.get", get_health)
    start_errors = []

    def start_server() -> None:
        try:
            manager.start()
        except Exception as exc:
            start_errors.append(exc)

    start_thread = threading.Thread(target=start_server)
    start_thread.start()
    assert health_started.wait(timeout=2)

    with pytest.raises(LlamaServerError, match="Cannot start"):
        manager.start()
    with pytest.raises(LlamaServerError, match="Cannot stop"):
        manager.stop()

    release_health.set()
    start_thread.join(timeout=2)

    assert not start_thread.is_alive()
    assert not start_errors
    assert manager.status.model_id == "gemma"


def test_restart_after_stop_uses_only_one_live_process(
    tmp_path: Path, monkeypatch
) -> None:
    manager, processes = start_manager(tmp_path, monkeypatch)
    manager.stop()
    manager.start()

    assert len(processes) == 2
    assert processes[0].terminated
    assert manager.status.model_id == "gemma"
    assert sum(process.poll() is None for process in processes) == 1
