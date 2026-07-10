# Town Watch

**The trust layer for the NANDA Town registry.** Agents ask one question —
*"Can I rely on this skill right now?"* — and get a live-checked answer.

🔗 **Live:** https://townwatch.onrender.com · **Agents start at:** [/skill.md](https://townwatch.onrender.com/skill.md) · **API reference:** [/docs](https://townwatch.onrender.com/docs)

Built for NandaHack 2026.

## The problem

NANDA Town is a shared registry of skills that AI agents can discover and use.
But a SkillMD with dead links does nothing, and an ambiguous one silently
wastes an agent's time. Nothing in the registry tells an agent which skills
are actually *alive and readable right now*. Town Watch is that missing layer
— and because every skill in the registry is something it can vet, it composes
with every other submission by design.

## What it does

**Lints SkillMDs for agent-readability.** ~10 deterministic checks: missing
base URLs, undocumented endpoints, absent examples, unstated parameter
defaults, and autonomy hazards — phrases like "contact us" or "sign up" that a
vanilla agent cannot act on. Every issue comes with a concrete fix.

**Live-probes services.** Fires real HTTP requests at every link found in a
SkillMD, measures latency, and checks that `/health` and `/skill.md` are served.

**Returns one composable verdict.** `rely`, `caution`, or `avoid` — a single
word any agent can branch on before trusting an unfamiliar tool.

**Remembers.** Uptime percentage and average latency accumulate across every
check it has ever run against a URL.

## Endpoints

| Endpoint | What it does |
|---|---|
| `GET /verdict?skill_url=<url>` | fetch + lint + live-check a skill.md → **rely / caution / avoid** |
| `POST /lint` | score a SkillMD (raw text or URL): 0–100, grade A–F, issues with fixes |
| `GET /probe?base_url=<url>` | live-check any service: latency, /health, /skill.md |
| `GET /history?url=<url>` | uptime % and avg latency across past checks |
| `GET /health` | liveness |
| `GET /skill.md` | the SkillMD for this service, base URL auto-filled |

No auth. No API keys. JSON in, JSON out.

## Try it in 10 seconds

The self-referential test — Town Watch judging its own SkillMD:

```bash
curl "https://townwatch.onrender.com/verdict?skill_url=https://townwatch.onrender.com/skill.md"
```

```json
{"verdict": "rely", "score": 100, "grade": "A", "reason": "Score 100/100 (grade A). Ready for a vanilla agent.", "dead_links": []}
```

Or just open **https://townwatch.onrender.com** — the homepage is a one-click
demo: run the self-verdict, watch the linter tear apart a broken SkillMD, and
paste any skill.md URL to judge it live.

## Run locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload            # http://127.0.0.1:8000
python judge_test.py                 # 5 agent-style tasks, skill.md-only knowledge
```

`judge_test.py` mirrors the official judging setup: five tasks an agent must
complete using only what `/skill.md` says. Passes 5/5 against the live deploy:

```bash
python judge_test.py https://townwatch.onrender.com
```

## Design notes

- **Recursion guard:** when Town Watch checks a document that references Town
  Watch URLs, it would probe itself probing itself forever. Outgoing checks
  carry a `TownWatch` User-Agent; incoming requests bearing it skip live
  checks. Depth is capped at one, so two Town Watch instances can safely
  judge each other.
- **Deterministic linting:** regex heuristics, not an LLM — fast, free, and
  the same input always yields the same score.
- **8-second timeout per URL check** — no call ever hangs an agent.

## Limits (honest)

- Check history is in-memory; it resets when the free host restarts.
- Heuristic linting can miss subtle ambiguity a human (or LLM) would catch.
- Render free tier cold-starts after idle: first call can take ~60s. The
  skill.md tells agents to retry once.

## Stack

Python 3 · FastAPI · httpx · deployed on Render free tier · zero API keys or
external services required.
