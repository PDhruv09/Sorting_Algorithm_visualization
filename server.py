from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from runner import execute_java

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"

app = FastAPI(title="Java Sorting Visualizer Runner", version="2.0")

class ExecuteRequest(BaseModel):
    code: str = Field(min_length=1, max_length=50_000)
    inputArray: list[int] = Field(default_factory=lambda: [64,34,25,12,22,11,90,88,45,50,76,33,58,92,15,38,71,29,82,47], max_length=500)
    methodName: str | None = Field(default=None, max_length=100)

@app.get("/api/health")
def health():
    return {"ok": True}

@app.post("/api/execute")
def execute(req: ExecuteRequest):
    try:
        return execute_java(req.code, req.inputArray, req.methodName)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

app.mount("/static", StaticFiles(directory=STATIC), name="static")

@app.get("/")
def root():
    return FileResponse(STATIC / "index.html")

@app.get("/{path:path}")
def static_fallback(path: str):
    candidate = (STATIC / path).resolve()
    if STATIC.resolve() not in candidate.parents and candidate != STATIC.resolve():
        raise HTTPException(status_code=404)
    if candidate.exists() and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(STATIC / "index.html")
