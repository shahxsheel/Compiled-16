"""Compact DOM snapshots: interactive elements + tables, each with a canonical selector and fingerprint."""
import hashlib

# Runs in the page. Returns [{tag, type, role, label, selector, ...}] in document order.
SNAPSHOT_JS = r"""
() => {
  const visible = el => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const uniq = sel => { try { return document.querySelectorAll(sel).length === 1; } catch { return false; } };
  const q = v => '"' + String(v).replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
  const canonical = el => {
    const tag = el.tagName.toLowerCase();
    if (el.id && uniq('#' + CSS.escape(el.id))) return '#' + CSS.escape(el.id);
    const name = el.getAttribute('name');
    if (name && uniq(`${tag}[name=${q(name)}]`)) return `${tag}[name=${q(name)}]`;
    for (const a of el.attributes) {
      if (a.name.startsWith('data-') && uniq(`${tag}[${a.name}=${q(a.value)}]`)) return `${tag}[${a.name}=${q(a.value)}]`;
    }
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && cur !== document.documentElement) {
      const t = cur.tagName.toLowerCase();
      const cls = [...cur.classList].map(c => '.' + CSS.escape(c)).join('');
      const sibs = cur.parentElement ? [...cur.parentElement.children].filter(c => c.tagName === cur.tagName) : [cur];
      parts.unshift(`${t}${cls}:nth-of-type(${sibs.indexOf(cur) + 1})`);
      const sel = parts.join(' > ');
      if (uniq(sel)) return sel;
      cur = cur.parentElement;
    }
    return parts.join(' > ');
  };
  const implicitRole = el => {
    const tag = el.tagName.toLowerCase(), type = (el.getAttribute('type') || '').toLowerCase();
    if (el.getAttribute('role')) return el.getAttribute('role');
    if (tag === 'a') return 'link';
    if (tag === 'button' || (tag === 'input' && ['submit', 'button'].includes(type))) return 'button';
    if (tag === 'input' && type === 'search') return 'searchbox';
    if (tag === 'input' || tag === 'textarea') return 'textbox';
    if (tag === 'select') return 'combobox';
    if (tag === 'table') return 'table';
    return '';
  };
  const label = el => {
    const t = el.tagName.toLowerCase();
    const l = el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
      (['input', 'select', 'textarea', 'table'].includes(t) ? (el.getAttribute('name') || '') : el.innerText);
    return (l || '').trim().replace(/\s+/g, ' ').slice(0, 60);
  };
  const out = [];
  const els = document.querySelectorAll('a[href], button, input, select, textarea, [role=button], table');
  for (const el of els) {
    if (!visible(el)) continue;
    const tag = el.tagName.toLowerCase();
    const item = { tag, role: implicitRole(el), label: label(el), selector: canonical(el) };
    if (tag === 'input') { item.type = el.type; item.value = el.value; }
    if (tag === 'select') { item.value = el.value; item.options = [...el.options].map(o => o.text); }
    if (tag === 'table') {
      item.columns = [...el.querySelectorAll('thead th')].map(th => th.innerText.trim());
      item.rows = el.querySelectorAll('tbody tr').length;
    }
    out.push(item);
  }
  return out;
}
"""

# Runs in the page. Hash of URL-independent state: DOM + form values + focus.
STATE_JS = r"""
() => {
  const vals = [...document.querySelectorAll('input, select, textarea')].map(e => e.value).join('\u0001');
  const f = document.activeElement;
  const focus = f && f !== document.body ? (f.id || f.getAttribute('name') || f.tagName) : '';
  return { dom: document.body.innerHTML + '\u0002' + vals, focus };
}
"""

# Runs in the page with a selector. Returns {columns, rows} with rows keyed by normalized header.
EXTRACT_JS = r"""
(sel) => {
  const t = document.querySelector(sel);
  if (!t) return null;
  const cols = [...t.querySelectorAll('thead th')].map(th => th.innerText.trim().toLowerCase());
  const rows = [...t.querySelectorAll('tbody tr')].map(tr => [...tr.querySelectorAll('td')].map(td => td.innerText.trim()))
    .filter(cells => cells.length === cols.length)
    .map(cells => Object.fromEntries(cols.map((c, i) => [c, cells[i]])));
  return { columns: cols, rows };
}
"""


def snapshot(page) -> list[dict]:
    return page.evaluate(SNAPSHOT_JS)


def fingerprint(el: dict) -> dict:
    return {"tag": el["tag"], "role": el["role"], "label": el["label"]}


def page_state(page) -> tuple[str, str, str]:
    s = page.evaluate(STATE_JS)
    return page.url, hashlib.sha1(s["dom"].encode()).hexdigest(), s["focus"]


def extract(page, selector: str) -> dict | None:
    return page.evaluate(EXTRACT_JS, selector)


def render(elements: list[dict]) -> str:
    """Compact text form sent to the LLM. Never raw HTML, never selectors."""
    lines = []
    for i, el in enumerate(elements):
        s = f'[{i}] {el["tag"]}'
        if el.get("type") and el["tag"] == "input":
            s += f' type={el["type"]}'
        s += f' "{el["label"]}"'
        if el["tag"] == "select":
            s += f' value="{el.get("value", "")}" options={el.get("options")}'
        elif el["tag"] == "input":
            s += f' value="{el.get("value", "")}"'
        if el["tag"] == "table":
            s += f' columns={el["columns"]} rows={el["rows"]}'
        lines.append(s)
    return "\n".join(lines)
