"""Deterministic trace -> Python compiler. No LLM involved."""
import json
import types
from pathlib import Path

from hotpath import store, tasks

HEADER = '''"""Hotpath compiled trace: {template} v{version}.

Generated deterministically from a recorded trace (signature {sig}). Do not edit.
"""
from hotpath.guards import GuardFailure, find_by_label, guard_element, guard_table, select_option
from hotpath.tasks import FINALIZERS

TEMPLATE = {template!r}
VERSION = {version}
SIGNATURE = {sig!r}
STEPS = {n}


def run(page, params):
    tables = []
'''


def _value(step: dict) -> str:
    args = step["args"]
    return f"params[{args['slot']!r}]" if "slot" in args else repr(args["text"])


def generate(template_id: str, steps: list[dict], version: int, sig: str, invariants: dict | None = None) -> str:
    lines = [HEADER.format(template=template_id, version=version, sig=sig, n=len(steps))]
    for s in steps:
        k, sel, fp = s["step"], s["selector"], s["fingerprint"]
        desc = f'{s["action"]} {fp["tag"]} "{fp["label"]}"'
        if "slot" in s["args"]:
            desc += f" <- {{{s['args']['slot']}}}"
        if "target_slot" in s["args"]:
            slot = s["args"]["target_slot"]
            lines.append(f'    # step {k}: click {fp["tag"]} labelled {{{slot}}}')
            lines.append(f"    sel = find_by_label(page, {k}, {fp['tag']!r}, {fp['role']!r}, params[{slot!r}])")
            lines.append("    page.click(sel, timeout=3000)")
            lines.append("    page.wait_for_load_state('load')")
            continue
        lines.append(f"    # step {k}: {desc}")
        lines.append(f"    guard_element(page, {k}, {sel!r}, {json.dumps(fp, sort_keys=True)})")
        if s["action"] == "click":
            lines.append(f"    page.click({sel!r}, timeout=3000)")
            lines.append("    page.wait_for_load_state('load')")
        elif s["action"] == "fill" and fp["tag"] == "select":
            lines.append(f"    select_option(page, {sel!r}, {_value(s)})")
        elif s["action"] == "fill":
            lines.append(f"    page.fill({sel!r}, {_value(s)}, timeout=3000)")
        elif s["action"] == "extract_table":
            spec = tasks.table_spec(template_id)
            extra = "" if spec == tasks.table_spec("price_of") else \
                f", columns={spec['columns']!r}, price_field={spec['price_field']!r}, price_re={spec['price_re']!r}"
            if invariants:
                extra += f", invariants={json.dumps(invariants, sort_keys=True)}"
            lines.append(f"    tables.append(guard_table(page, {k}, {sel!r}{extra}))")
        else:
            raise ValueError(f"cannot compile action {s['action']!r}")
    n = len(steps)
    lines.append(f"    # step {n}: finalize")
    lines.append("    try:")
    lines.append(f"        return FINALIZERS[{template_id!r}](tables, params)")
    lines.append("    except GuardFailure as e:")
    lines.append(f"        raise GuardFailure({n}, e.reason, e.kind)")
    return "\n".join(lines) + "\n"


def path_for(template_id: str, version: int) -> Path:
    return store.compiled_dir() / f"{template_id}_v{version}.py"


def compile_trace(template_id: str, steps: list[dict], version: int, sig: str, invariants: dict | None = None) -> Path:
    p = path_for(template_id, version)
    p.write_text(generate(template_id, steps, version, sig, invariants))
    return p


def load(path: str):
    """Exec the generated file fresh every time (no bytecode cache, so a rewrite is never stale)."""
    mod = types.ModuleType(f"hotpath_compiled_{Path(path).stem}")
    mod.__file__ = str(path)
    exec(compile(Path(path).read_text(), str(path), "exec"), mod.__dict__)
    return mod
