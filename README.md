# Town Watch

Trust & lint layer for the NANDA Town skills registry. Agents call Town Watch
before relying on any registered skill: it lints the skill's SkillMD for
agent-readability, live-checks every link inside it, and returns a single
composable verdict — `rely`, `caution`, or `avoid`.

## The problem

A SkillMD with dead links does nothing, and an ambiguous one silently wastes an
agent's time. Nothing in the registry tells an agent which skills are actually
alive and readable *right now*. Town Watch is that missing layer — and because
every other submission benefits from it, it composes with the whole registry.

## Endpoints

| Endpoint | What it does |
|---|---|
| `GET /health` | liveness |
| `GET /verdict?skill_url=<url>` | fetch + lint + live-check a skill.md → rely / caution / avoid |
| `POST /lint` | score raw SkillMD text (or by URL): 0–100, graded issues with concrete fixes |
| `GET /probe?base_url=<url>` | live-check any service: latency, /health, /skill.md |
| `GET /history?url=<url>` | uptime % and avg latency observed across past checks |
| `GET /skill.md` | the SkillMD for this service, base URL auto-filled |

No auth, no keys, JSON everywhere.

## Run locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload          # http://127.0.0.1:8000
python judge_test.py               # 5 agent-style tasks, skill.md-only knowledge
```

## Deploy (Render free tier)

1. Push this folder to a GitHub repo.
2. render.com → New → Web Service → connect the repo. `render.yaml` does the rest.
3. Verify: `curl https://<your-app>.onrender.com/health`
4. Fun part: point it at itself —
   `curl "https://<your-app>.onrender.com/verdict?skill_url=https://<your-app>.onrender.com/skill.md"`

## Register on NANDA Town

Form at nandatown.projectnanda.org/skills, or:

```bash
curl -X POST https://nandatown.projectnanda.org/api/skills \
  -H "Content-Type: application/json" \
  -d '{"name": "Town Watch", "skill_url": "https://<your-app>.onrender.com/skill.md"}'
```

## Limits (honest)

- History is in-memory; it resets when the free host restarts.
- Lint checks are heuristic (regex-based), not an LLM judgment — deterministic
  and fast, but they can miss subtle ambiguity.
- Free-tier cold starts: first call after idle can take ~60s; skill.md tells
  agents to retry once.
