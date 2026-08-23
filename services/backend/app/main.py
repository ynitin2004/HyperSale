from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.api.router import api_router
from app.errors import correlation_id_middleware, unhandled_error


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield


app = FastAPI(title="HyperSale API", version="0.0.1", lifespan=lifespan)
app.middleware("http")(correlation_id_middleware)
app.add_exception_handler(Exception, unhandled_error)
app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health(request: Request) -> dict[str, str]:
    return {"status": "ok", "request_id": request.state.request_id}

