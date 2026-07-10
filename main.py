"""
Town Watch — the trust & lint layer for the NANDA Town skills registry.

Agents call Town Watch BEFORE relying on any registered skill:
  - POST /lint     -> score a SkillMD for agent-readability (dead links, missing
                      defaults, auth walls, ambiguity) and get concrete fixes
  - GET  /probe    -> live-check a service: is it up, how fast, does it serve
                      /health and /skill.md
  - GET  /verdict  -> one composable answer: "rely" | "caution" | "avoid"

No auth. No API keys. JSON in, JSON out. Built for NandaHack 2026.
"""

import asyncio
import re
import time
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

app = FastAPI(
    title="Town Watch",
    description="Trust & lint layer for the NANDA Town registry. "
    "Agents: fetch /skill.md for usage instructions.",
    version="1.0.0",
)

HTTP_TIMEOUT = 8.0
USER_AGENT = "TownWatch/1.0 (+skill.md at /skill.md)"

# In-memory check history: {url: [(unix_ts, ok, latency_ms), ...]}
HISTORY: dict[str, list[tuple[float, bool, float]]] = {}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

URL_RE = re.compile(r"https?://[^\s\)\]\>\"'`,]+")
ENDPOINT_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_\-./{}]*)")
AMBIGUITY_PATTERNS = [
    (r"\bsomehow\b", "'somehow' — an agent cannot improvise; spell out the step"),
    (r"\bcontact (us|me|support)\b", "'contact us' — agents cannot contact humans"),
    (r"\bsign ?up\b", "'sign up' — agents cannot register accounts"),
    (r"\bapi[ _-]?key\b", "mentions an API key — a vanilla agent has no keys"),
    (r"\byou may need to\b", "'you may need to' — be definite, not conditional"),
    (r"\bask (the|your) (user|human)\b", "requires human input — breaks autonomy"),
]


def _norm_url(u: str) -> str:
    return u.rstrip("/.,;:")


async def _check_url(client: httpx.AsyncClient, url: str) -> tuple[bool, float, int]:
    """Return (alive, latency_ms, status_code). alive = responded with < 500."""
    start = time.monotonic()
    try:
        r = await client.get(url, timeout=HTTP_TIMEOUT, follow_redirects=True)
        latency = (time.monotonic() - start) * 1000
        return r.status_code < 500, round(latency, 1), r.status_code
    except Exception:
        latency = (time.monotonic() - start) * 1000
        return False, round(latency, 1), 0


def _record(url: str, ok: bool, latency_ms: float) -> None:
    HISTORY.setdefault(url, []).append((time.time(), ok, latency_ms))
    HISTORY[url] = HISTORY[url][-200:]  # cap memory


# --------------------------------------------------------------------------
# lint engine
# --------------------------------------------------------------------------

class LintRequest(BaseModel):
    skillmd: Optional[str] = None   # raw SkillMD text
    url: Optional[str] = None       # ...or a URL to fetch it from
    live_check: bool = True         # also probe the endpoints found inside


async def run_lint(text: str, live_check: bool) -> dict:
    issues: list[dict] = []
    score = 100

    def add(severity: str, points: int, message: str, fix: str):
        nonlocal score
        score -= points
        issues.append({"severity": severity, "message": message, "fix": fix})

    stripped = text.strip()

    # 1. size sanity
    if len(stripped) < 200:
        add("error", 25, "SkillMD is under 200 characters — too thin for an agent to act on.",
            "Describe what the service does, list every endpoint, and give one worked example.")
    elif len(stripped) > 12000:
        add("warning", 5, "SkillMD is over 12k characters — agents lose the thread in long docs.",
            "Cut to: purpose, base URL, endpoints, one example each, error notes.")

    # 2. purpose up top
    head = stripped[:400].lower()
    if not any(w in head for w in ("what", "does", "use this", "this service", "this skill", "this tool", "purpose")):
        add("warning", 8, "No clear purpose statement in the first few lines.",
            "Open with one sentence: 'This service does X. Use it when Y.'")

    # 3. base URL present
    urls = [_norm_url(u) for u in URL_RE.findall(text)]
    if not urls:
        add("error", 30, "No https:// URL anywhere — an agent has no way to reach the service.",
            "State the base URL explicitly, e.g. 'Base URL: https://myservice.onrender.com'.")

    # 4. endpoints documented
    endpoints = ENDPOINT_RE.findall(text)
    if not endpoints and not urls:
        add("error", 20, "No endpoints documented (no 'METHOD /path' patterns found).",
            "List each endpoint like 'GET /route?x=...' with its parameters.")
    elif not endpoints:
        add("warning", 8, "URLs found but no 'METHOD /path' style endpoint docs.",
            "Document endpoints as 'GET /path' / 'POST /path' so agents know the verb.")

    # 5. worked example
    if "```" not in text and "curl" not in text.lower():
        add("warning", 10, "No code block or curl example — agents copy examples far more reliably than prose.",
            "Add one fenced code block showing a full request and its response.")

    # 6. defaults for parameters
    if ("param" in text.lower() or "field" in text.lower() or "{" in text) and "default" not in text.lower():
        add("info", 4, "Parameters mentioned but no defaults stated — agents stall on unstated choices.",
            "For every optional parameter say 'default: <value>'.")

    # 7. ambiguity / human-dependency phrases
    for pattern, why in AMBIGUITY_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            add("warning", 6, f"Autonomy hazard: {why}.",
                "Rewrite so a vanilla agent can complete the task with zero human help.")

    # 8. health endpoint mentioned
    if "/health" not in text:
        add("info", 3, "No /health endpoint mentioned.",
            "Expose and document GET /health so agents can verify liveness before use.")

    # 9. live-check every URL found
    dead, alive = [], []
    if live_check and urls:
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
            results = await asyncio.gather(*(_check_url(client, u) for u in set(urls)))
            for u, (ok, latency, code) in zip(set(urls), results):
                _record(u, ok, latency)
                (alive if ok else dead).append(
                    {"url": u, "status_code": code, "latency_ms": latency})
        for d in dead:
            add("error", 15, f"Dead link: {d['url']} (status {d['status_code']}). "
                "A SkillMD with dead links does nothing.",
                "Fix or remove the link; keep the service awake or note the cold-start delay.")

    score = max(score, 0)
    grade = ("A" if score >= 90 else "B" if score >= 75 else
             "C" if score >= 60 else "D" if score >= 40 else "F")
    return {
        "score": score,
        "grade": grade,
        "agent_ready": score >= 75 and not any(i["severity"] == "error" for i in issues),
        "issues": issues,
        "endpoints_documented": [f"{m} {p}" for m, p in endpoints],
        "urls_alive": alive,
        "urls_dead": dead,
        "summary": f"Score {score}/100 (grade {grade}). "
        + ("Ready for a vanilla agent." if score >= 75 else
           "An agent would likely fail or stall on this SkillMD — apply the fixes."),
    }


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": "townwatch", "time": time.time()}


def _is_probe(request: Request) -> bool:
    """True when the caller is another Town Watch probe — skip live checks to
    prevent infinite recursion when a SkillMD references Town Watch URLs."""
    return "townwatch" in request.headers.get("user-agent", "").lower()


@app.post("/lint")
async def lint(req: LintRequest, request: Request):
    """Lint a SkillMD (raw text or by URL) for agent-readability."""
    if _is_probe(request):
        req.live_check = False
    text = req.skillmd
    if not text and req.url:
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
            try:
                r = await client.get(req.url, timeout=HTTP_TIMEOUT, follow_redirects=True)
                text = r.text
            except Exception as e:
                return {"error": f"Could not fetch {req.url}: {e}"}
    if not text:
        return {"error": "Provide 'skillmd' (raw text) or 'url' (link to a skill.md)."}
    return await run_lint(text, req.live_check)


@app.get("/probe")
async def probe(base_url: str = Query(..., description="Base URL of the service to check")):
    """Live-check a service: liveness, latency, /health and /skill.md presence."""
    base = _norm_url(base_url)
    if not urlparse(base).scheme:
        base = "https://" + base
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        root, health_ep, skill_ep = await asyncio.gather(
            _check_url(client, base),
            _check_url(client, base + "/health"),
            _check_url(client, base + "/skill.md"),
        )
    _record(base, root[0], root[1])
    checks = {
        "root": {"alive": root[0], "latency_ms": root[1], "status_code": root[2]},
        "health_endpoint": {"alive": health_ep[0], "latency_ms": health_ep[1], "status_code": health_ep[2]},
        "skillmd_served": {"alive": skill_ep[0], "latency_ms": skill_ep[1], "status_code": skill_ep[2]},
    }
    up = root[0] or health_ep[0]
    return {
        "base_url": base,
        "up": up,
        "checks": checks,
        "note": None if up else "Service unreachable — may be a cold start on a free host; retry once after 60s.",
    }


@app.get("/verdict")
async def verdict(request: Request,
                  skill_url: str = Query(..., description="URL of the skill.md to judge")):
    """The composable primitive: should an agent rely on this skill right now?"""
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        try:
            r = await client.get(skill_url, timeout=HTTP_TIMEOUT, follow_redirects=True)
            text = r.text
        except Exception as e:
            return {"verdict": "avoid", "reason": f"skill.md unreachable: {e}", "score": 0}
    result = await run_lint(text, live_check=not _is_probe(request))
    v = ("rely" if result["agent_ready"]
         else "caution" if result["score"] >= 50
         else "avoid")
    return {
        "verdict": v,
        "score": result["score"],
        "grade": result["grade"],
        "reason": result["summary"],
        "dead_links": [d["url"] for d in result["urls_dead"]],
    }


@app.get("/history")
async def history(url: str = Query(..., description="URL previously checked")):
    """Uptime history Town Watch has observed for a URL."""
    u = _norm_url(url)
    rows = HISTORY.get(u, [])
    if not rows:
        return {"url": u, "checks": 0, "note": "No history yet — run /probe or /lint on it first."}
    ok = sum(1 for _, o, _ in rows if o)
    return {
        "url": u,
        "checks": len(rows),
        "uptime_pct": round(100 * ok / len(rows), 1),
        "avg_latency_ms": round(sum(l for _, _, l in rows) / len(rows), 1),
        "last_check": {"ts": rows[-1][0], "ok": rows[-1][1], "latency_ms": rows[-1][2]},
    }


@app.get("/skill.md", response_class=PlainTextResponse)
async def skillmd(request: Request):
    """Serve the SkillMD with the live base URL filled in."""
    base = str(request.base_url).rstrip("/")
    with open("skill.md", "r") as f:
        return f.read().replace("{{BASE_URL}}", base)


HOME_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Town Watch — trust layer for NANDA Town</title>
<style>
  :root { --bg:#0e1116; --card:#161b23; --line:#242c38; --txt:#e6edf3;
          --dim:#8b98a9; --acc:#4ea1ff; --ok:#3fb950; --warn:#d29922; --bad:#f85149; }
  * { box-sizing:border-box; margin:0; }
  body { background:var(--bg); color:var(--txt); font:16px/1.6 -apple-system,
         BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; padding:40px 20px; }
  main { max-width:860px; margin:0 auto; }
  h1 { font-size:34px; } h1 span { color:var(--acc); }
  .sub { color:var(--dim); margin:6px 0 28px; font-size:18px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:22px; margin-bottom:18px; }
  .card h2 { font-size:19px; margin-bottom:6px; }
  .card p { color:var(--dim); font-size:15px; margin-bottom:14px; }
  button { background:var(--acc); color:#fff; border:0; border-radius:8px;
           padding:10px 18px; font-size:15px; font-weight:600; cursor:pointer; }
  button:hover { filter:brightness(1.15); }
  pre { background:#0a0d12; border:1px solid var(--line); border-radius:8px;
        padding:14px; margin-top:14px; font-size:13px; overflow-x:auto;
        white-space:pre-wrap; word-break:break-word; display:none; }
  .badge { display:none; margin-top:14px; padding:10px 14px; border-radius:8px;
           font-weight:700; font-size:15px; }
  .rely { background:rgba(63,185,80,.15); color:var(--ok); }
  .caution { background:rgba(210,153,34,.15); color:var(--warn); }
  .avoid { background:rgba(248,81,73,.15); color:var(--bad); }
  input, textarea { width:100%; background:#0a0d12; border:1px solid var(--line);
        border-radius:8px; color:var(--txt); padding:10px 12px; font-size:14px;
        margin-bottom:10px; font-family:inherit; resize:vertical; }
  .card button + textarea { margin-top:14px; }
  .links { color:var(--dim); font-size:14px; margin-top:26px; }
  .links a { color:var(--acc); text-decoration:none; }
</style></head><body><main>
  <h1>Town <span>Watch</span></h1>
  <p class="sub">The trust layer for NANDA Town. Agents ask one question:
  <em>&ldquo;Can I rely on this skill right now?&rdquo;</em> &mdash; and get a live-checked answer.</p>

  <div class="card">
    <h2>1 &middot; The verdict &mdash; it judges its own SkillMD</h2>
    <p>Fetches this service's own skill.md, lints it for agent-readability, and
       live-checks every link inside. The exact call a judge's agent would make.</p>
    <button onclick="run(this,'verdict')">Run self-verdict</button>
    <div class="badge"></div><pre></pre>
  </div>

  <div class="card">
    <h2>2 &middot; The linter &mdash; catches a broken SkillMD</h2>
    <p>Scores a deliberately bad SkillMD (no URL, needs human help). Watch it
       fail with concrete fixes an author could apply.</p>
    <button onclick="run(this,'lint')">Lint a broken SkillMD</button>
    <div class="badge"></div><pre></pre>
  </div>

  <div class="card">
    <h2>3 &middot; The probe &mdash; is a service alive right now?</h2>
    <p>Live latency and liveness for this service: root, /health, and /skill.md.</p>
    <button onclick="run(this,'probe')">Probe this service</button>
    <div class="badge"></div><pre></pre>
  </div>

  <div class="card">
    <h2>4 &middot; Try your own &mdash; judge any skill</h2>
    <p>Paste the URL of any skill.md to get a live verdict, or paste raw
       SkillMD text below to lint it.</p>
    <input id="skillUrl" type="url" placeholder="https://some-service.onrender.com/skill.md">
    <button onclick="run(this,'customVerdict')">Get verdict</button>
    <textarea id="skillText" rows="5" placeholder="...or paste raw SkillMD text here"></textarea>
    <button onclick="run(this,'customLint')">Lint text</button>
    <div class="badge"></div><pre></pre>
  </div>

  <p class="links">Agents start at <a href="/skill.md">/skill.md</a> &middot;
     interactive API reference at <a href="/docs">/docs</a> &middot;
     liveness at <a href="/health">/health</a></p>
</main>
<script>
const B = window.location.origin;
const BAD = "# My Skill\\nIt does stuff. Contact us to get access.";
async function run(btn, kind) {
  const card = btn.closest('.card'), pre = card.querySelector('pre'),
        badge = card.querySelector('.badge');
  btn.disabled = true; btn.textContent = 'Running…';
  try {
    let r, label = '', cls = 'rely';
    if (kind === 'verdict') {
      r = await (await fetch(B + '/verdict?skill_url=' + encodeURIComponent(B + '/skill.md'))).json();
      label = 'Verdict: ' + r.verdict.toUpperCase() + ' — score ' + r.score + '/100, grade ' + r.grade;
      cls = r.verdict;
    } else if (kind === 'lint') {
      r = await (await fetch(B + '/lint', { method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({ skillmd: BAD, live_check: false }) })).json();
      label = 'Score ' + r.score + '/100 (grade ' + r.grade + ') — ' +
              r.issues.length + ' issues found, agent_ready: ' + r.agent_ready;
      cls = r.agent_ready ? 'rely' : 'avoid';
    } else if (kind === 'customVerdict') {
      const u = document.getElementById('skillUrl').value.trim();
      if (!u) throw 'enter a skill.md URL first';
      r = await (await fetch(B + '/verdict?skill_url=' + encodeURIComponent(u))).json();
      label = r.verdict ? 'Verdict: ' + r.verdict.toUpperCase() + ' — score ' +
              r.score + '/100' + (r.grade ? ', grade ' + r.grade : '') : JSON.stringify(r);
      cls = r.verdict || 'avoid';
    } else if (kind === 'customLint') {
      const t = document.getElementById('skillText').value;
      if (!t.trim()) throw 'paste some SkillMD text first';
      r = await (await fetch(B + '/lint', { method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({ skillmd: t, live_check: true }) })).json();
      label = 'Score ' + r.score + '/100 (grade ' + r.grade + ') — ' +
              r.issues.length + ' issues, agent_ready: ' + r.agent_ready;
      cls = r.agent_ready ? 'rely' : (r.score >= 50 ? 'caution' : 'avoid');
    } else {
      r = await (await fetch(B + '/probe?base_url=' + encodeURIComponent(B))).json();
      label = r.up ? 'UP — root ' + r.checks.root.latency_ms + 'ms, health ' +
              r.checks.health_endpoint.latency_ms + 'ms' : 'DOWN';
      cls = r.up ? 'rely' : 'avoid';
    }
    badge.textContent = label; badge.className = 'badge ' + cls;
    badge.style.display = 'block';
    pre.textContent = JSON.stringify(r, null, 2); pre.style.display = 'block';
  } catch (e) {
    badge.textContent = 'Request failed: ' + e; badge.className = 'badge avoid';
    badge.style.display = 'block';
  }
  btn.disabled = false; btn.textContent = 'Run again';
}
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
async def root():
    return HOME_HTML


@app.get("/info")
async def info():
    return {
        "service": "Town Watch",
        "what": "Trust & lint layer for the NANDA Town registry.",
        "agents_start_here": "/skill.md",
        "endpoints": ["GET /health", "POST /lint", "GET /probe", "GET /verdict", "GET /history", "GET /skill.md"],
    }
