"""
A2A-style server for the correlation agent (same plain-FastAPI contract as the other agents).
Run with: uvicorn server:app --port 9004   (from correlation_agent/)
"""
from fastapi import FastAPI
from pydantic import BaseModel

from agent import run_correlation

app = FastAPI(title="Correlation Agent")


class CorrRequest(BaseModel):
    eeg_file: str
    ecg_file: str
    output_dir: str = "./outputs"
    out_prefix: str | None = None
    win_s: float = 30
    step_s: float = 30
    events_file: str | None = None
    eeg_quality: float | None = None
    ecg_quality: float | None = None
    min_quality: float = 0.0


@app.post("/message")
def handle_message(req: CorrRequest):
    try:
        return {"status": "ok", "result": run_correlation(**req.model_dump())}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}


@app.get("/health")
def health():
    return {"status": "ok", "agent": "correlation"}
