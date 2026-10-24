"""On-disk state: runs.json, hot.json, compiled/. Rooted at $HOTPATH_HOME (default: project root)."""
import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_lock = threading.Lock()


def home() -> Path:
    return Path(os.environ.get("HOTPATH_HOME", ROOT))


def compiled_dir() -> Path:
    d = home() / "compiled"
    d.mkdir(parents=True, exist_ok=True)
    return d


def base_url() -> str:
    return os.environ.get("HOTPATH_BASE_URL", "http://127.0.0.1:8000")


def load(name: str, default):
    p = home() / name
    with _lock:
        if not p.exists():
            return default
        return json.loads(p.read_text())


def save(name: str, data) -> None:
    p = home() / name
    p.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(p)


def append_run(run: dict) -> None:
    runs = load("runs.json", [])
    runs.append(run)
    save("runs.json", runs)


def reset() -> None:
    for name in ("runs.json", "hot.json"):
        (home() / name).unlink(missing_ok=True)
    for f in compiled_dir().glob("*"):
        f.unlink()
