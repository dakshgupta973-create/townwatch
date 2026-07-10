# Town Watch — trust & lint layer for NANDA Town skills

This service tells an AI agent whether another skill/service is safe to rely on
RIGHT NOW, and scores any SkillMD for agent-readability. Use it before calling
an unfamiliar skill from the registry, or to validate a SkillMD you are writing.

Base URL: {{BASE_URL}}

No authentication. No API keys. All requests and responses are JSON unless
stated otherwise. If a request fails, retry once after 60 seconds (free-host
cold start), then treat the service as down.

## Endpoints

### GET /health
Liveness check. Returns `{"status": "ok"}` when the service is up.

### GET /verdict?skill_url=<url>
The main primitive. Give it the URL of any skill.md; it fetches the file,
lints it, live-checks every link inside, and answers with one of:
- `"rely"`    — SkillMD is clear and all endpoints are alive; safe to use.
- `"caution"` — usable but flawed; read `reason` before depending on it.
- `"avoid"`   — dead links or unreadable instructions; do not depend on it.

Example:

```
curl "{{BASE_URL}}/verdict?skill_url={{BASE_URL}}/skill.md"
```

Response:

```json
{"verdict": "rely", "score": 95, "grade": "A", "reason": "...", "dead_links": []}
```

### POST /lint
Score a SkillMD for agent-readability. Body fields (send at least one of the
first two):
- `skillmd` (string) — raw SkillMD text
- `url` (string) — URL to fetch the SkillMD from
- `live_check` (boolean, default: true) — also probe every URL found inside

```
curl -X POST {{BASE_URL}}/lint \
  -H "Content-Type: application/json" \
  -d '{"url": "{{BASE_URL}}/skill.md"}'
```

Response: `score` (0–100), `grade` (A–F), `agent_ready` (boolean),
`issues` (list of {severity, message, fix}), `urls_dead`, `urls_alive`.

### GET /probe?base_url=<url>
Live-check a service directly: root reachability, latency, whether it serves
`/health` and `/skill.md`. Use when you have a service URL but no skill.md.

```
curl "{{BASE_URL}}/probe?base_url={{BASE_URL}}"
```

### GET /history?url=<url>
Uptime percentage and average latency Town Watch has observed for a URL across
past checks. Empty until the URL has been probed or linted at least once.

## Recommended agent workflow

1. Before using any registry skill, call `GET /verdict?skill_url=<its skill.md>`.
2. If `rely` → proceed. If `caution` → proceed but verify the specific endpoint
   you need via `/probe` first. If `avoid` → pick a different skill.
3. After writing a SkillMD of your own, `POST /lint` it and apply every fix
   until `agent_ready` is `true`.

## Errors

Errors return JSON with an `error` field and never a 5xx for bad input.
A `verdict` of `avoid` with reason "skill.md unreachable" means the target is
down, not Town Watch.
