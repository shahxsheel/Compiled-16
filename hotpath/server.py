"""FastAPI app: the /shop target site plus the Hotpath dashboard and API."""
import asyncio
import difflib
import json
import os
import queue
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

from hotpath import hotness, shop, store, tasks

app = FastAPI(title="Hotpath")
SITE = {"redesign": False, "mode": None}
STATIC = Path(__file__).resolve().parent.parent / "static"


# ---------- event bus (worker thread -> SSE) ----------

class Bus:
    def __init__(self):
        self.events: list[dict] = []
        self.lock = threading.Lock()
        self.next_id = 1

    def emit(self, kind: str, msg: str, **data) -> None:
        with self.lock:
            ev = {"id": self.next_id, "ts": time.time(), "kind": kind, "msg": msg, **_jsonable(data)}
            self.next_id += 1
            self.events.append(ev)
            del self.events[:-500]

    def clear(self) -> None:
        with self.lock:
            self.events.clear()

    def since(self, last_id: int) -> list[dict]:
        with self.lock:
            return [e for e in self.events if e["id"] > last_id]


def _jsonable(data: dict) -> dict:
    return json.loads(json.dumps(data, default=str))


BUS = Bus()


# ---------- run worker: one thread owns the Playwright browser ----------

class Worker:
    def __init__(self):
        self.jobs: queue.Queue = queue.Queue()
        self.thread = None
        self.busy = False

    def submit(self, template_id: str, params: dict) -> None:
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()
        self.jobs.put((template_id, params))

    def _loop(self):
        from hotpath.runtime import Runtime

        rt = Runtime(headless=os.environ.get("HOTPATH_SHOW") != "1", emit=BUS.emit)
        while True:
            template_id, params = self.jobs.get()
            self.busy = True
            try:
                rt.run(template_id, params)
            except Exception as e:
                BUS.emit("error", f"run failed: {type(e).__name__}: {e}")
            finally:
                self.busy = self.jobs.qsize() > 0


WORKER = Worker()


# ---------- target site ----------

@app.get("/shop", response_class=HTMLResponse)
def shop_page(q: str = "", category: str = ""):
    return shop.render(q, category, SITE["redesign"], SITE.get("mode"))


@app.post("/toggle")
def toggle():
    SITE["mode"] = None
    SITE["redesign"] = not SITE["redesign"]
    BUS.emit("toggle", f"site redesign {'ON' if SITE['redesign'] else 'OFF'}", redesign=SITE["redesign"])
    return {"redesign": SITE["redesign"]}


@app.post("/mode/{name}")
def set_mode(name: str):
    """Stress-test modes (see shop.render). "original"/"redesign" behave like the toggle."""
    if name not in shop.MODES:
        return {"error": f"unknown mode {name!r}", "modes": shop.MODES}
    SITE["redesign"] = name != "original"
    SITE["mode"] = None if name in ("original", "redesign") else name
    BUS.emit("toggle", f"site mode {name}", redesign=SITE["redesign"])
    return {"mode": name}


# ---------- dashboard ----------

@app.get("/")
def dashboard():
    return FileResponse(STATIC / "dashboard.html")


class RunRequest(BaseModel):
    template: str
    param: str = ""


@app.post("/api/run")
def api_run(req: RunRequest):
    t = tasks.TEMPLATES[req.template]
    params = {t["param"]: req.param.strip() or t["default"]}
    WORKER.submit(req.template, params)
    return {"queued": True, "template": req.template, "params": params}


@app.post("/api/reset")
def api_reset():
    store.reset()
    SITE["redesign"] = False
    SITE["mode"] = None
    BUS.clear()
    BUS.emit("reset", "state cleared: runs, hot.json, compiled/; redesign OFF")
    return {"ok": True}


def _code_info(template_id: str) -> dict | None:
    entry = hotness.compiled(template_id)
    if not entry or not Path(entry["path"]).exists():
        return None
    code = Path(entry["path"]).read_text()
    info = {"version": entry["version"], "file": Path(entry["path"]).name, "code": code, "diff": None}
    prev = entry.get("prev_path")
    if prev and Path(prev).exists():
        info["diff"] = "".join(difflib.unified_diff(
            Path(prev).read_text().splitlines(True), code.splitlines(True),
            fromfile=Path(prev).name, tofile=Path(entry["path"]).name))
    return info


@app.get("/api/state")
def api_state():
    bench_path = store.home() / "bench.json"
    return {
        "redesign": SITE["redesign"],
        "busy": WORKER.busy,
        "runs": store.load("runs.json", []),
        "templates": {k: {"param": v["param"], "default": v["default"]} for k, v in tasks.TEMPLATES.items()},
        "compiled": {k: _code_info(k) for k in tasks.TEMPLATES},
        "bench": json.loads(bench_path.read_text()) if bench_path.exists() else None,
    }


@app.get("/api/events")
async def api_events(request: Request):
    last = int(request.headers.get("last-event-id") or 0)

    async def stream():
        nonlocal last
        yield "retry: 1000\n\n"
        while not await request.is_disconnected():
            for ev in BUS.since(last):
                last = ev["id"]
                yield f"id: {ev['id']}\ndata: {json.dumps(ev)}\n\n"
            await asyncio.sleep(0.1)

    return StreamingResponse(stream(), media_type="text/event-stream")
