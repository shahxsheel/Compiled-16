"""`python -m hotpath ci`: run as a subprocess, fake LLM, bundled demo site."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "examples" / "shop-checks.json"


def ci(tmp_path, spec=SPEC, *extra):
    env = {**os.environ, "HOTPATH_HOME": str(tmp_path / "home")}
    env.pop("HOTPATH_BASE_URL", None)
    out = subprocess.run([sys.executable, "-m", "hotpath", "ci", str(spec), "--fake", "--serve-demo",
                          "--junit", str(tmp_path / "junit.xml"), *extra],
                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    return out.returncode, out.stdout + out.stderr, (tmp_path / "junit.xml").read_text()


def test_ci_cold_then_cached_run_is_fully_compiled(tmp_path):
    code, out, xml = ci(tmp_path)
    assert code == 0, out
    assert "9/9 passed" in out and xml.count("<testcase") == 9 and 'failures="0"' in xml
    code, out, xml = ci(tmp_path)  # same HOTPATH_HOME = a cached pipeline run
    assert code == 0, out
    assert "9 ran compiled ($0)" in out and "total LLM cost $0.0000" in out
    assert xml.count('name="tier" value="compiled"') == 9


def test_ci_wrong_expectation_fails_the_pipeline(tmp_path):
    spec = json.loads(SPEC.read_text())
    spec["checks"] = spec["checks"][:1]
    spec["checks"][0]["expect"] = {"price": "$1.00"}
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(spec))
    code, out, xml = ci(tmp_path, p)
    assert code == 1 and 'failures="1"' in xml and "expected" in xml
