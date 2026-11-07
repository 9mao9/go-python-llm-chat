from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError


class ConfigError(ValueError):
    """Raised when the application configuration is missing or invalid."""


class ServerConfig(BaseModel):
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)


class LlamaServerConfig(BaseModel):
    executable: Path
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    startup_timeout: int = Field(gt=0)
    shutdown_timeout: int = Field(gt=0)
    extra_args: list[str] = Field(default_factory=list)


GpuLayerCount = Annotated[int, Field(ge=-1)] | Literal["all"]


class ModelDefinition(BaseModel):
    name: str = Field(min_length=1)
    path: Path
    context_size: int = Field(gt=0)
    gpu_layers: GpuLayerCount


class ModelsConfig(BaseModel):
    default: str = Field(min_length=1)
    available: dict[str, ModelDefinition] = Field(min_length=1)


class AppConfig(BaseModel):
    server: ServerConfig
    llama_server: LlamaServerConfig
    models: ModelsConfig


def load_config(
    config_path: str | Path | None = None,
    *,
    app_root: str | Path | None = None,
) -> AppConfig:
    """Load, validate, and resolve paths in the application YAML configuration."""
    path = (
        Path(config_path)
        if config_path is not None
        else Path(__file__).resolve().parents[1] / "config.yaml"
    )
    try:
        raw_config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Unable to read config file '{path}': {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in config file '{path}': {exc}") from exc

    try:
        config = AppConfig.model_validate(raw_config)
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration in '{path}': {exc}") from exc

    if config.models.default not in config.models.available:
        raise ConfigError(
            f"models.default '{config.models.default}' is not in models.available"
        )

    root = Path(app_root) if app_root is not None else path.parent
    root = root.resolve()
    executable = config.llama_server.executable
    if not executable.is_absolute():
        executable = (root / executable).resolve()
    if not executable.is_file():
        raise ConfigError(
            f"llama_server.executable: file does not exist: '{executable}'"
        )
    config.llama_server.executable = executable

    for model_id, model in config.models.available.items():
        model_path = model.path
        if not model_path.is_absolute():
            model_path = (root / model_path).resolve()
        if not model_path.is_file():
            raise ConfigError(
                f"models.available.{model_id}.path: file does not exist: "
                f"'{model_path}'"
            )
        model.path = model_path

    return config
