"""
A2A-style server for the EEG QC agent.

NOTE ON TRANSPORT: this uses a plain FastAPI HTTP endpoint rather than the
official `a2a-sdk` server classes, because that package's exact server-side
API depends on the version you have installed and I can't verify it without
your environment. The *message contract* here (POST a file path, receive a
JSON result) mirrors the same client/server interaction pattern your
orchestrator already uses — if you have a2a-sdk's server classes working,
swapping this transport layer for theirs is a small change; the `run_qc`
logic in agent.py doesn't need to change at all.

Run with: uvicorn server:app --port 9001
"""

from fastapi import FastAPI
from pydantic import BaseModel

from agent import run_qc

app = FastAPI(title="EEG QC Agent")


class QCRequest(BaseModel):
    file_path: str
    pass_label: str = "raw"  # "raw" or "cleaned" — set by the caller


@app.post("/message")
def handle_message(req: QCRequest):
    try:
        result = run_qc(req.file_path, pass_label=req.pass_label)
        return {"status": "ok", "result": result}
    except Exception as e:
        return {"status": "error", "error": f"{type(e).__name__}: {e}"}


@app.get("/health")
def health():
    return {"status": "ok", "agent": "eeg-qc"}
