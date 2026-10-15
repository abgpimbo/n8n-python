import hmac
import os
import subprocess
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI()

# Shared secret between n8n and the runner. Every container in the runner's Docker
# networks (app-net, mcp-internal) can reach port 8000, so /run must not be open.
# Fail closed: without RUNNER_TOKEN the protected endpoints refuse every request.
RUNNER_TOKEN = os.environ.get("RUNNER_TOKEN", "")


def require_token(x_runner_token: str | None = Header(default=None)) -> None:
    if not RUNNER_TOKEN:
        raise HTTPException(503, "RUNNER_TOKEN not configured")
    if not x_runner_token or not hmac.compare_digest(x_runner_token, RUNNER_TOKEN):
        raise HTTPException(401, "invalid or missing X-Runner-Token")


class Payload(BaseModel):
    text: str


@app.get("/health")
def health():
    return {"status": "ok", "auth": bool(RUNNER_TOKEN)}


@app.post("/echo", dependencies=[Depends(require_token)])
def echo(payload: Payload):
    return {"received": payload.text, "length": len(payload.text)}


class RunReq(BaseModel):
    script: str
    args: list[str] = []


SCRIPTS_DIR = Path("/files/scripts").resolve()


@app.post("/run", dependencies=[Depends(require_token)])
def run(req: RunReq):
    script_path = (SCRIPTS_DIR / req.script).resolve()

    if not script_path.is_relative_to(SCRIPTS_DIR):
        raise HTTPException(400, "invalid path")
    if not script_path.exists() or script_path.suffix != ".py":
        raise HTTPException(404, "script not found")

    res = subprocess.run(
        ["python", str(script_path), *req.args],
        capture_output=True,
        text=True,
        timeout=600,
    )

    return {
        "returncode": res.returncode,
        "stdout": res.stdout[-4000:],
        "stderr": res.stderr[-4000:],
    }
