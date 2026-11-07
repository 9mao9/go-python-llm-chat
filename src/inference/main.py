from contextlib import asynccontextmanager
from typing import AsyncGenerator, Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ValidationError

from inference.config import AppConfig
from inference.config import load_config
from inference.prompt import build_prompt
from inference.server import (
    LlamaServerError,
    LlamaServerManager,
    ModelState,
    ModelNotReadyError,
)


class GenerateMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class GenerateRequest(BaseModel):
    system_prompt: str
    history: list[GenerateMessage]
    user_input: str


class GenerateResponse(BaseModel):
    text: str


class HealthResponse(BaseModel):
    status: Literal["ok"]
    model_status: ModelState


class CurrentModelResponse(BaseModel):
    model_id: str | None
    name: str | None
    status: ModelState
    error: str | None = None


def create_app(config: AppConfig | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
        manager = LlamaServerManager(config)
        application.state.config = manager.config
        application.state.llama_server = manager
        manager.start()
        try:
            yield
        finally:
            manager.stop()

    application = FastAPI(title="Local LLM Inference Manager", lifespan=lifespan)

    @application.get("/health")
    def health(request: Request) -> HealthResponse:
        manager: LlamaServerManager = request.app.state.llama_server
        return HealthResponse(status="ok", model_status=manager.status.state)

    @application.get(
        "/models/current",
        response_model=CurrentModelResponse,
        response_model_exclude_none=True,
    )
    def current_model(request: Request) -> CurrentModelResponse:
        manager: LlamaServerManager = request.app.state.llama_server
        status = manager.status
        model = (
            manager.config.models.available[status.model_id]
            if status.model_id is not None
            else None
        )
        return CurrentModelResponse(
            model_id=status.model_id,
            name=model.name if model is not None else None,
            status=status.state,
            error=status.error,
        )

    @application.post("/generate", response_model=GenerateResponse)
    def generate(payload: GenerateRequest, request: Request) -> GenerateResponse:
        manager: LlamaServerManager = request.app.state.llama_server
        prompt = build_prompt(
            payload.system_prompt,
            [message.model_dump() for message in payload.history],
            payload.user_input,
        )
        try:
            with manager.inference():
                result = manager.chat_completion(
                    [{"role": "user", "content": prompt}]
                )
            return GenerateResponse.model_validate(result)
        except ModelNotReadyError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except LlamaServerError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ValidationError as exc:
            raise HTTPException(
                status_code=502,
                detail="llama-server returned an invalid generated response",
            ) from exc

    return application


app = create_app()


def main() -> None:
    config = load_config()
    uvicorn.run(
        create_app(config),
        host=config.server.host,
        port=config.server.port,
    )


if __name__ == "__main__":
    main()
