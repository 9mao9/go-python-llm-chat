from __future__ import annotations

import atexit
import logging
import requests
import subprocess
import threading
import time
import yaml
from contextlib import contextmanager
from dataclasses import dataclass
from requests.exceptions import JSONDecodeError
from typing import Iterator, Literal

from inference.config import AppConfig, load_config
from inference.schema import OutputSchema

ModelState = Literal["stopped", "starting", "ready", "stopping", "error"]
logger = logging.getLogger(__name__)


class LlamaServerError(RuntimeError):
    pass


class ModelNotReadyError(LlamaServerError):
    pass


@dataclass(frozen=True)
class ModelStatus:
    state: ModelState
    model_id: str | None
    error: str | None = None


class LlamaServerManager:
    """Start, stop, and send requests to the configured llama-server."""

    def __init__(self, config_path: str | AppConfig | None = None):
        self.config = (
            config_path if isinstance(config_path, AppConfig) else load_config(config_path)
        )
        self.process: subprocess.Popen[str] | None = None
        self.current_model_id: str | None = None
        self._state: ModelState = "stopped"
        self._error: str | None = None
        self._condition = threading.Condition()
        self._active_inferences = 0
        atexit.register(self._shutdown_at_exit)

    @property
    def status(self) -> ModelStatus:
        with self._condition:
            self._refresh_process_state()
            return ModelStatus(self._state, self.current_model_id, self._error)

    def build_command(self) -> list[str]:
        model = self.config.models.available[self.config.models.default]
        server = self.config.llama_server
        return [
            str(server.executable),
            "-m",
            str(model.path),
            "--host",
            server.host,
            "--port",
            str(server.port),
            "--ctx-size",
            str(model.context_size),
            "--gpu-layers",
            str(model.gpu_layers),
            *server.extra_args,
        ]

    def start(self) -> ModelStatus:
        with self._condition:
            self._refresh_process_state()
            if self._state == "ready":
                return ModelStatus(self._state, self.current_model_id, self._error)
            if self._state in ("starting", "stopping"):
                raise LlamaServerError(f"Cannot start while server is {self._state}")
            if self.process is not None and self.process.poll() is None:
                raise LlamaServerError("A managed llama-server process is already running")
            self._state = "starting"
            self.current_model_id = None
            self._error = None

        try:
            self._start_process()
        except LlamaServerError as exc:
            with self._condition:
                self._state = "error"
                self._error = str(exc)
            raise
        return self.status

    def stop(self) -> ModelStatus:
        with self._condition:
            self._refresh_process_state()
            if self._state == "starting":
                raise LlamaServerError("Cannot stop while server is starting")
            if self._state == "stopping":
                raise LlamaServerError("Server is already stopping")
            if self.process is None:
                self.current_model_id = None
                self._state = "stopped"
                self._error = None
                return ModelStatus(self._state, None)
            self._state = "stopping"

        with self._condition:
            while self._active_inferences:
                self._condition.wait()

        self._stop_process()
        return self.status

    @contextmanager
    def inference(self) -> Iterator[str]:
        with self._condition:
            self._refresh_process_state()
            if self._state != "ready" or self.current_model_id is None:
                raise ModelNotReadyError("The model is not ready for inference")
            self._active_inferences += 1
            model_id = self.current_model_id

        try:
            yield model_id
        finally:
            with self._condition:
                self._active_inferences -= 1
                self._condition.notify_all()

    def _start_process(self) -> None:
        model_id = self.config.models.default
        try:
            process = subprocess.Popen(
                self.build_command(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
        except OSError as exc:
            raise LlamaServerError(f"Unable to start llama-server: {exc}") from exc

        with self._condition:
            self.process = process

        try:
            self._wait_until_ready(process)
        except LlamaServerError as exc:
            try:
                self._terminate_process(process)
            except LlamaServerError as stop_error:
                exc = LlamaServerError(f"{exc}; cleanup failed: {stop_error}")
            if process.poll() is not None:
                with self._condition:
                    self.process = None
            raise exc

        with self._condition:
            self.current_model_id = model_id
            self._state = "ready"
            self._error = None

    def _wait_until_ready(self, process: subprocess.Popen[str]) -> None:
        server = self.config.llama_server
        url = f"http://{server.host}:{server.port}/health"
        deadline = time.monotonic() + server.startup_timeout

        while True:
            return_code = process.poll()
            if return_code is not None:
                raise LlamaServerError(
                    f"llama-server exited before becoming ready (code {return_code})"
                )

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LlamaServerError(
                    f"llama-server did not become ready within "
                    f"{server.startup_timeout} seconds"
                )
            try:
                response = requests.get(url, timeout=min(1.0, remaining))
                if response.status_code == 200:
                    return
            except requests.RequestException:
                pass
            time.sleep(min(0.25, remaining))

    def _stop_process(self) -> None:
        process = self.process
        if process is None:
            return
        try:
            self._terminate_process(process)
        except LlamaServerError as exc:
            with self._condition:
                self._state = "error"
                self._error = str(exc)
            raise

        with self._condition:
            self.process = None
            self.current_model_id = None
            self._state = "stopped"
            self._error = None

    def _terminate_process(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=self.config.llama_server.shutdown_timeout)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=self.config.llama_server.shutdown_timeout)
            except (OSError, subprocess.SubprocessError) as exc:
                raise LlamaServerError(
                    f"Unable to force-stop llama-server: {exc}"
                ) from exc
        except OSError as exc:
            raise LlamaServerError(f"Unable to stop llama-server: {exc}") from exc

    def _refresh_process_state(self) -> None:
        if self._state != "ready" or self.process is None:
            return
        return_code = self.process.poll()
        if return_code is not None:
            self._state = "error"
            self._error = f"llama-server exited unexpectedly (code {return_code})"

    def _shutdown_at_exit(self) -> None:
        try:
            self.stop()
        except LlamaServerError:
            logger.exception("Failed to stop llama-server during Python shutdown")

    def get_api_url(self) -> str:
        server = self.config.llama_server
        return f"http://{server.host}:{server.port}/v1/chat/completions"
    
    def is_health(self) -> bool:
        """Return whether the configured llama-server health endpoint is ready."""
        server = self.config.llama_server
        try:
            response = requests.get(
                f"http://{server.host}:{server.port}/health",
                timeout=5,
            )
            return response.status_code == 200
        except requests.RequestException:
            return False
    
    def chat_completion(
        self,
        messages: list,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 64,
        stream: bool = False,
        stop: list = None
    ) -> dict:
        """
        チャット補完を実行
        
        Args:
            messages: メッセージリスト [{"role": "user/assistant/system", "content": "..."}]
            max_tokens: 最大トークン数
            temperature: サンプリング温度
            top_p: nucleus sampling パラメータ
            top_k: top-k sampling パラメータ
            stream: ストリーミングモードを有効化
            stop: 停止トークンのリスト
        
        Returns:
            OutputSchemaにより検証された応答
        """
        if not self.is_health():
            raise LlamaServerError("llama-server is not healthy")
        
        url = self.get_api_url()
        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "stream": stream,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "output",
                    "strict": True,
                    "schema": OutputSchema.model_json_schema(),
                },
            },
        }
        
        if stop:
            payload["stop"] = stop
        
        try:
            response = requests.post(url, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()
            content = result["choices"][0]["message"]["content"]
        except requests.Timeout as exc:
            raise LlamaServerError("llama-server request timed out") from exc
        except requests.HTTPError as exc:
            raise LlamaServerError(
                f"llama-server returned HTTP {exc.response.status_code}"
            ) from exc
        except JSONDecodeError as exc:
            raise LlamaServerError("llama-server returned invalid JSON") from exc
        except requests.RequestException as exc:
            raise LlamaServerError(f"llama-server request failed: {exc}") from exc
        except (KeyError, IndexError, TypeError) as exc:
            raise LlamaServerError("llama-server returned an invalid response") from exc

        if not isinstance(content, str):
            raise LlamaServerError("llama-server returned non-text content")

        output = OutputSchema.model_validate_json(content)
        return output.model_dump()
    
    def chat_completion_stream(
        self,
        messages: list,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 64,
        stop: list = None
    ):
        """
        ストリーミングチャット補完を実行
        
        Args:
            messages: メッセージリスト
            max_tokens: 最大トークン数
            temperature: サンプリング温度
            top_p: nucleus sampling パラメータ
            top_k: top-k sampling パラメータ
            stop: 停止トークンのリスト
        
        Yields:
            ストリーミングレスポンスのチャンク
        """
        if not self.is_health():
            raise LlamaServerError("llama-server is not healthy")
        
        url = self.get_api_url()
        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "stream": True
        }
        
        if stop:
            payload["stop"] = stop
        
        response = requests.post(url, json=payload, stream=True, timeout=60)
        response.raise_for_status()
        
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data = line[6:]  # Remove 'data: ' prefix
                    if data.strip() != '[DONE]':
                        yield data
    

class EmbeddingServerManager:
    """Establish and manage embedding-server"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self._load_config()
        self.process = None
        self.is_running = False
        
    def _load_config(self) -> dict:
        """load configuration from YAML file"""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def start_server(self):
        """start embedding-server"""
        if self.is_running:
            print("Server is already running.")
            return
        
        server_config = self.config['embedding-server']
        port = server_config['port']
        
        # Construct the subprocess command
        cmd = server_config['subprocess'].format(
            model_path=server_config['model_path'],
            port=port
        )
        
        print(f"Starting embedding-server... (Port: {port})")
        print(f"Command: {cmd}")
        
        # Start the server in the background using PowerShell
        self.process = subprocess.Popen(
            ["powershell", "-Command", cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Wait for the server to start
        self._wait_for_server(port)
        self.is_running = True
        print("embedding-server has started.")
        
        # Execute warm-up
        self._warmup()
        
        # Stop the server when the program exits
        atexit.register(self.stop_server)
    
    def _wait_for_server(self, port: int, timeout: int = 120):
        """wait for the server to start"""
        url = f"http://localhost:{port}/health"
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                response = requests.get(url, timeout=1)
                if response.status_code == 200:
                    return
            except requests.exceptions.RequestException:
                pass
            
            time.sleep(2)
            print(".", end="", flush=True)
        
        raise TimeoutError(f"embedding-server did not start within {timeout} seconds.")
    
    def _warmup(self):
        """Warm-up: Initialize CUDA kernels and KV cache with the first inference"""
        print("Warming up...", end="", flush=True)
        start_time = time.time()
        
        try:
            url = self.get_api_url()
            payload = {
                "input": "Hello, world!",
                "encoding_format": "float"
            }
            response = requests.post(url, json=payload, timeout=30)
            if response.status_code == 200:
                elapsed = time.time() - start_time
                print(f" Done ({elapsed:.2f} seconds)")
            else:
                print(" Skipped (Error)")
        except Exception as e:
            print(f" Skipped ({e})")
    
    def stop_server(self):
        """stop embedding-server"""
        if not self.is_running:
            return
        
        print("\nStopping embedding-server...")
        
        # Force terminate the process using the port
        port = self.config['embedding-server']['port']
        try:
            # Identify and terminate the process using the port via PowerShell
            kill_cmd = f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }}"
            subprocess.run(
                ["powershell", "-Command", kill_cmd],
                timeout=5,
                capture_output=True
            )
        except Exception as e:
            print(f"Failed to stop via port: {e}")
        
        # Search for the process by name and terminate it
        try:
            kill_cmd = "Get-Process -Name embedding-server -ErrorAction SilentlyContinue | Stop-Process -Force"
            subprocess.run(
                ["powershell", "-Command", kill_cmd],
                timeout=5,
                capture_output=True
            )
        except Exception as e:
            print(f"Failed to stop by process name: {e}")
        
        # 元のプロセスも終了
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            except Exception:
                pass
        
        self.is_running = False
        time.sleep(1)  # Wait for VRAM to be released
        print("embedding-server has stopped.")
    
    def get_api_url(self) -> str:
        """APIのURLを取得"""
        port = self.config['embedding-server']['port']
        return self.config['embedding-server']['url'].format(port=port)
    
    def is_healthy(self) -> bool:
        """サーバーのヘルスチェック"""
        if not self.is_running:
            return False
        
        try:
            port = self.config['embedding-server']['port']
            url = f"http://localhost:{port}/health"
            response = requests.get(url, timeout=5)
            return response.status_code == 200
        except Exception:
            return False
    
    def get_embedding(self, text: str) -> list:
        """
        テキストのエンベディングを取得
        
        Args:
            text: エンベディング化するテキスト
        
        Returns:
            エンベディングベクトル（floatのリスト）
        """
        if not self.is_running:
            raise RuntimeError("Server is not running. Call start_server() first.")
        
        url = self.get_api_url()
        payload = {
            "input": text,
            "encoding_format": "float"
        }
        
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        return result['data'][0]['embedding']
    
    def get_embeddings(self, texts: list) -> list:
        """
        複数のテキストのエンベディングを一括取得
        
        Args:
            texts: エンベディング化するテキストのリスト
        
        Returns:
            エンベディングベクトルのリスト
        """
        if not self.is_running:
            raise RuntimeError("Server is not running. Call start_server() first.")
        
        url = self.get_api_url()
        payload = {
            "input": texts,
            "encoding_format": "float"
        }
        
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        
        return [item['embedding'] for item in result['data']]