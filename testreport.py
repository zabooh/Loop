#!/usr/bin/env python3
"""
testreport.py
-------------
Tiny result model + self-contained HTML report writer shared by the test tools
(regression.py, smoketest.py, run_ci.py). No external dependencies.

A run is a list of Suites; each Suite has Results; each Result may carry
individual Checks and/or a small table. write_html() renders one standalone
HTML file with an overall PASS/FAIL banner, per-suite tables and (optionally)
embedded plot images.
"""
from dataclasses import dataclass, field
from html import escape
from typing import List, Optional


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Result:
    name: str
    passed: bool
    summary: str = ""
    checks: List[Check] = field(default_factory=list)
    table_headers: Optional[List[str]] = None
    table_rows: Optional[List[List[str]]] = None


@dataclass
class Suite:
    name: str
    description: str = ""
    results: List[Result] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""

    @property
    def passed(self) -> bool:
        return (not self.skipped) and all(r.passed for r in self.results)

    def add(self, result: Result) -> Result:
        self.results.append(result)
        return result


_CSS = """
:root{--ok:#1a7f37;--bad:#cf222e;--skip:#9a6700;--bg:#f6f8fa;--line:#d0d7de;}
*{box-sizing:border-box}
body{font-family:Segoe UI,Arial,sans-serif;margin:0;color:#1f2328;background:#fff}
header{padding:20px 28px;color:#fff}
header.ok{background:#1a7f37}header.bad{background:#cf222e}
header h1{margin:0 0 4px;font-size:22px}
header .meta{font-size:13px;opacity:.95}
main{padding:18px 28px;max-width:1100px}
.badge{display:inline-block;padding:1px 9px;border-radius:11px;font-size:12px;
  font-weight:600;color:#fff}
.b-ok{background:var(--ok)}.b-bad{background:var(--bad)}.b-skip{background:var(--skip)}
h2{margin:26px 0 6px;font-size:18px;border-bottom:1px solid var(--line);padding-bottom:4px}
h2 .badge{vertical-align:middle;margin-left:8px}
.desc{color:#57606a;font-size:13px;margin:0 0 10px}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:13px}
th,td{border:1px solid var(--line);padding:5px 9px;text-align:left;vertical-align:top}
th{background:var(--bg)}
tr.res td:first-child{font-weight:600;width:34%}
.checks{margin:4px 0 0;padding-left:18px;font-size:12.5px;color:#444}
.checks li.ok::marker{color:var(--ok)}.checks li.bad::marker{color:var(--bad)}
.sub{border:1px solid var(--line);border-radius:6px;margin:6px 0;padding:6px 10px;background:#fbfdff}
.sub th,.sub td{font-size:12px;padding:3px 7px}
.mono{font-family:Consolas,monospace}
img{max-width:100%;border:1px solid var(--line);border-radius:6px;margin:8px 0}
footer{padding:14px 28px;color:#57606a;font-size:12px;border-top:1px solid var(--line)}
"""


def _badge(passed, skipped=False):
    if skipped:
        return '<span class="badge b-skip">SKIP</span>'
    return ('<span class="badge b-ok">PASS</span>' if passed
            else '<span class="badge b-bad">FAIL</span>')


def _result_block(r: Result) -> str:
    parts = [f'<tr class="res"><td>{escape(r.name)} {_badge(r.passed)}</td>'
             f'<td>{escape(r.summary)}']
    if r.checks:
        parts.append('<ul class="checks">')
        for c in r.checks:
            cls = "ok" if c.passed else "bad"
            mark = "PASS" if c.passed else "FAIL"
            d = f" — {escape(c.detail)}" if c.detail else ""
            parts.append(f'<li class="{cls}">[{mark}] {escape(c.name)}{d}</li>')
        parts.append('</ul>')
    if r.table_headers and r.table_rows:
        parts.append('<table class="sub"><tr>'
                     + "".join(f"<th>{escape(h)}</th>" for h in r.table_headers)
                     + "</tr>")
        for row in r.table_rows:
            parts.append("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>")
        parts.append("</table>")
    parts.append("</td></tr>")
    return "".join(parts)


def write_html(path, title, meta: dict, suites: List[Suite], images=None):
    """meta: dict of label->value shown in the header. images: list of (caption, path)."""
    overall = all(s.passed for s in suites if not s.skipped)
    out = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
           f"<title>{escape(title)}</title><style>{_CSS}</style></head><body>"]
    out.append(f'<header class="{"ok" if overall else "bad"}">'
               f'<h1>{escape(title)} {_badge(overall)}</h1>'
               f'<div class="meta">'
               + " &nbsp;|&nbsp; ".join(f"{escape(k)}: <b>{escape(str(v))}</b>"
                                        for k, v in meta.items())
               + "</div></header><main>")

    # summary table
    out.append("<h2>Summary</h2><table><tr><th>Suite</th><th>Result</th>"
               "<th>Cases</th></tr>")
    for s in suites:
        n = len(s.results)
        npass = sum(1 for r in s.results if r.passed)
        cell = (f"{npass}/{n} passed" if not s.skipped else escape(s.skip_reason))
        out.append(f"<tr><td>{escape(s.name)}</td>"
                   f"<td>{_badge(s.passed, s.skipped)}</td><td>{cell}</td></tr>")
    out.append("</table>")

    # per-suite detail
    for s in suites:
        out.append(f"<h2>{escape(s.name)} {_badge(s.passed, s.skipped)}</h2>")
        if s.description:
            out.append(f'<p class="desc">{escape(s.description)}</p>')
        if s.skipped:
            out.append(f'<p class="desc">Skipped: {escape(s.skip_reason)}</p>')
            continue
        out.append("<table><tr><th>Test</th><th>Details</th></tr>")
        for r in s.results:
            out.append(_result_block(r))
        out.append("</table>")

    if images:
        out.append("<h2>Plots</h2>")
        for caption, img in images:
            out.append(f'<div><b>{escape(caption)}</b><br><img src="{escape(img)}"></div>')

    out.append("</main><footer>Generated by testreport.py</footer></body></html>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(out))
    return overall
