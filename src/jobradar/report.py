"""Static, self-contained HTML dashboard of ranked matches (published to GitHub Pages)."""

from __future__ import annotations

import html
import json
from datetime import UTC, datetime, timedelta
from typing import Any

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>jobradar · ranked matches</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--text:#1c1c1e;--muted:#6b6b70;--border:#e3e3e0;--accent:#3b5bdb;--good:#2b8a3e;--mid:#e67700;--low:#868e96}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--card:#1e1e21;--text:#ececef;--muted:#9a9aa2;--border:#2e2e33;--accent:#7c95ff;--good:#69db7c;--mid:#ffc078;--low:#adb5bd}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1000px;margin:0 auto;padding:28px 16px 48px}h1{margin:0;font-size:26px}
.muted{color:var(--muted)}.small{font-size:13px}
.stats{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}
.stat{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:10px 14px}
.stat b{display:block;font-size:20px}
.controls{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}
input,select{font:inherit;padding:7px 10px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text)}
input{flex:1;min-width:180px}
.job{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin-bottom:10px;display:grid;grid-template-columns:56px 1fr;gap:12px}
.score{font-size:20px;font-weight:700;text-align:center;align-self:start;border-radius:8px;padding:6px 0;border:2px solid currentColor}
.hi{color:var(--good)}.md{color:var(--mid)}.lo{color:var(--low)}
.job a{color:var(--accent);font-weight:600;text-decoration:none}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.tag{font-size:12px;border:1px solid var(--border);border-radius:999px;padding:1px 8px}
.miss{border-style:dashed;color:var(--muted)}
.bar{display:flex;height:6px;border-radius:3px;overflow:hidden;margin-top:8px;background:var(--border);max-width:320px}
.bar span{display:block}
footer{margin-top:28px;text-align:center}
.new{font-size:11px;font-weight:700;text-transform:uppercase;color:#fff;background:var(--good);border-radius:4px;padding:1px 6px;margin-left:6px;vertical-align:middle}
label{display:flex;align-items:center;gap:6px}
</style>
</head>
<body><main>
<h1>jobradar</h1>
<p class="muted">Open roles from public Greenhouse, Lever and Ashby job boards, ranked by an explainable fit score
against <a href="https://github.com/SnigdhaSrivastva/jobradar/blob/main/example/profile.yaml">an example profile</a>.
Updated __UPDATED__.</p>
<div class="stats">__STATS__</div>
<div class="controls">
<input id="q" placeholder="Filter by title, company, skill, location…" aria-label="Filter">
<select id="min" aria-label="Minimum score"><option value="0">All scores</option><option value="50">≥ 50</option><option value="65" selected>≥ 65</option><option value="80">≥ 80</option></select>
<select id="remote" aria-label="Remote"><option value="">Any location</option><option value="1">Remote only</option></select>
<select id="platform" aria-label="Platform"><option value="">All platforms</option><option value="greenhouse">Greenhouse</option><option value="lever">Lever</option><option value="ashby">Ashby</option></select>
<label class="small muted"><input type="checkbox" id="fresh"> New only</label>
</div>
<p id="count" class="muted small"></p>
<div id="list"></div>
<footer class="muted small">Read-only public APIs · nothing is submitted · <a href="https://github.com/SnigdhaSrivastva/jobradar">source</a></footer>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const jobs = JSON.parse(document.getElementById("data").textContent);
const COLORS = {title:"#4c6ef5", skills:"#40c057", seniority:"#fab005", location:"#be4bdb"};
const MAX = {title:30, skills:45, seniority:15, location:10};
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function render(){
  const q = document.getElementById("q").value.toLowerCase().trim();
  const min = +document.getElementById("min").value;
  const remote = document.getElementById("remote").value === "1";
  const platform = document.getElementById("platform").value;
  const fresh = document.getElementById("fresh").checked;
  const shown = jobs.filter(j => j.score >= min && (!remote || j.remote) && (!platform || j.platform === platform) && (!fresh || j.new) &&
    (!q || [j.title, j.company, j.location, ...j.fit.matched_skills].join(" ").toLowerCase().includes(q)));
  document.getElementById("count").textContent = `${shown.length} of ${jobs.length} roles`;
  document.getElementById("list").innerHTML = shown.map(j => {
    const cls = j.score >= 80 ? "hi" : j.score >= 65 ? "md" : "lo";
    const bar = Object.entries(j.fit.parts).map(([k,v]) => `<span title="${k}: ${v}/${MAX[k]}" style="width:${v}%;background:${COLORS[k]}"></span>`).join("");
    return `<article class="job"><div class="score ${cls}">${Math.round(j.score)}</div><div>
      <a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>${j.new ? ' <span class="new">new</span>' : ""}
      <div class="muted small">${esc(j.company)} · ${esc(j.location || "—")}${j.remote ? " · remote" : ""}${j.salary ? " · " + esc(j.salary) : ""}</div>
      <div class="bar" aria-hidden="true">${bar}</div>
      <div class="small muted">${esc(j.fit.reasons.join(" · "))}</div>
      <div class="tags">${j.fit.matched_skills.map(s => `<span class="tag">${esc(s)}</span>`).join("")}${j.fit.missing_core.map(s => `<span class="tag miss" title="core skill not mentioned">${esc(s)}</span>`).join("")}</div>
    </div></article>`;
  }).join("");
}
["q","min","remote","platform","fresh"].forEach(id => document.getElementById(id).addEventListener("input", render));
render();
</script>
</body></html>
"""


def _json_for_script(value: Any) -> str:
    # Prevent "</script>" in job text from closing the data block
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def render(rows: list[dict[str, Any]], counts: dict[str, int], errors: dict[str, str] | None = None,
           now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    new_since = (now - timedelta(hours=24)).isoformat(timespec="seconds")
    jobs = [
        {
            "title": r["title"], "company": r["company"], "location": r["location"], "remote": bool(r["remote"]),
            "url": r["url"], "salary": r["salary"], "score": r["score"], "fit": json.loads(r["score_json"]),
            "platform": r["platform"], "new": r["first_seen"] >= new_since,
        }
        for r in rows
    ]
    strong = sum(1 for j in jobs if j["score"] >= 80)
    fresh = sum(1 for j in jobs if j["new"])
    stats = [
        (counts.get("active", 0), "open roles tracked"),
        (counts.get("companies", 0), "companies"),
        (strong, "strong matches (80+)"),
        (fresh, "new in the last 24h"),
    ]
    if errors:
        stats.append((len(errors), "boards unavailable"))
    stats_html = "".join(f'<div class="stat"><b>{n}</b><span class="muted small">{html.escape(label)}</span></div>'
                         for n, label in stats)
    updated = now.strftime("%b %d, %Y %H:%M UTC")
    return (PAGE.replace("__UPDATED__", updated)
                .replace("__STATS__", stats_html)
                .replace("__DATA__", _json_for_script(jobs)))
