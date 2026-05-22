"""AlphaSignal FastAPI entry point."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import load_config

app = FastAPI(title="AlphaSignal", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    cfg = load_config()
    return {
        "status": "ok",
        "app": "AlphaSignal",
        "version": "0.1.0",
        "weights_valid": cfg.weights_valid,
    }
