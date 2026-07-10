"""
Judge-style test: can an agent drive Town Watch from skill.md alone?

Mirrors the four-task pattern from the official demo (judge-demo/run_agent.py):
each task uses ONLY information available in skill.md. Run against a local or
deployed instance:

    python judge_test.py                       # tests http://127.0.0.1:8000
    python judge_test.py https://your.onrender.com
"""

import json
import sys
import urllib.parse
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
results = []


def call(method: str, path: str, body: dict | None = None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def check(name: str, cond: bool, detail: str = ""):
    results.append(cond)
    print(f"[{PASS if cond else FAIL}] {name}" + (f" — {detail}" if detail else ""))


# Task 1: "Is the service alive?" -> skill.md says GET /health
r = call("GET", "/health")
check("Task 1: health check", r.get("status") == "ok")

# Task 2: "Should I rely on this skill?" -> GET /verdict on its own skill.md
q = urllib.parse.quote(BASE + "/skill.md", safe="")
r = call("GET", f"/verdict?skill_url={q}")
check("Task 2: verdict on own skill.md", r.get("verdict") in ("rely", "caution"),
      f"verdict={r.get('verdict')} score={r.get('score')}")

# Task 3: "Lint this bad SkillMD" -> POST /lint must flag missing URL + brevity
bad = "# My Skill\nIt does stuff. Contact us to sign up for an API key."
r = call("POST", "/lint", {"skillmd": bad, "live_check": False})
check("Task 3: lint catches a bad SkillMD",
      r.get("score", 100) < 60 and not r.get("agent_ready", True),
      f"score={r.get('score')} issues={len(r.get('issues', []))}")

# Task 4: "Probe a live service" -> GET /probe against Town Watch itself
r = call("GET", f"/probe?base_url={urllib.parse.quote(BASE, safe='')}")
check("Task 4: probe reports liveness + skill.md served",
      r.get("up") is True and r["checks"]["skillmd_served"]["alive"] is True)

# Task 5 (bonus): history now exists for the probed URL
r = call("GET", f"/history?url={urllib.parse.quote(BASE, safe='')}")
check("Task 5: history recorded", r.get("checks", 0) >= 1,
      f"uptime={r.get('uptime_pct')}%")

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
