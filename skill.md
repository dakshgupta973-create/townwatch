# Town Watch

> The trust layer for the NANDA Town registry. This service answers one
> question for any AI agent: **"Can I rely on this skill right now?"**

## What this service does

Town Watch evaluates other skills and services so agents do not waste time on
broken or unreadable ones. Use this service when you are about to call an
unfamiliar skill from the registry, when you want to verify a service is alive
before depending on it, or when you want a SkillMD you are writing scored and
fixed before submission.

It performs three kinds of evaluation. First, it lints any SkillMD for
agent-readability: dead links, missing base URLs, absent examples, unstated
parameter defaults, and instructions that require human help. Second, it
live-probes services to measure liveness and latency in real time. Third, it
remembers past checks and reports uptime history.

Base URL: {{BASE_URL}}

No authentication. All endpoints are open. All requests and responses are
JSON, except /skill.md which is plain text. If any request fails, retry once
after 60 seconds (free-host cold start), then treat the target as down.

## Quick start

One call proves the service works — ask it to judge its own SkillMD:

```
curl "{{BASE_URL}}/verdict?skill_url={{BASE_URL}}/skill.md"
```

Expected response:

```json
{
  "verdict": "rely",
  "score": 100,
  "grade": "A",
  "reason": "Score 100/100 (grade A). Ready for a vanilla agent.",
  "dead_links": []
}
```

## Endpoints

### GET /health

Liveness check. Call this first if any other request misbehaves.

```
curl "{{BASE_URL}}/health"
```

Example response:

```json
{"status": "ok", "service": "townwatch", "time": 1783690522.32}
```

### GET /verdict

The primary primitive. Fetches a skill.md from a URL, lints it, live-checks
every link inside it, and returns a single decision.

Query parameters:
- `skill_url` (string, required) — full URL of the skill.md to judge.

```
curl "{{BASE_URL}}/verdict?skill_url={{BASE_URL}}/skill.md"
```

Example response:

```json
{"verdict": "rely", "score": 100, "grade": "A", "reason": "Score 100/100 (grade A). Ready for a vanilla agent.", "dead_links": []}
```

Response fields:
- `verdict` — `"rely"` (clear instructions, all endpoints alive — safe to use),
  `"caution"` (usable but flawed — read `reason` first), or
  `"avoid"` (dead links or unreadable — pick a different skill).
- `score` (0–100), `grade` (A–F), `reason` (one-line summary),
  `dead_links` (URLs inside the SkillMD that failed a live check).

### POST /lint

Score a SkillMD for agent-readability and get concrete fixes.

Body fields (JSON; send `skillmd` or `url`):
- `skillmd` (string) — raw SkillMD text to score.
- `url` (string) — alternatively, fetch the SkillMD from this URL.
- `live_check` (boolean, default: true) — also probe every URL found inside.

```
curl -X POST {{BASE_URL}}/lint \
  -H "Content-Type: application/json" \
  -d '{"url": "{{BASE_URL}}/skill.md"}'
```

Example response (abridged — a low-scoring input returns more issues):

```json
{"score": 74, "grade": "C", "agent_ready": false, "issues": [{"severity": "error", "message": "Dead link: old-example-service.com (status 0). A SkillMD with dead links does nothing.", "fix": "Fix or remove the link; keep the service awake or note the cold-start delay."}], "endpoints_documented": ["GET /weather"], "urls_alive": [], "urls_dead": [{"url": "old-example-service.com", "status_code": 0, "latency_ms": 8000.1}], "summary": "Score 74/100 (grade C). An agent would likely fail or stall on this SkillMD — apply the fixes."}
```

Response fields: `score` (0–100), `grade` (A–F), `agent_ready` (boolean —
true when a vanilla agent could drive the service from this SkillMD alone),
`issues` (list of `{severity, message, fix}` objects, severities are `error`,
`warning`, `info`), `endpoints_documented`, `urls_alive`, `urls_dead`,
`summary`.

### GET /probe

Live-check a service directly when you have its address but no skill.md.
Reports root reachability, latency in milliseconds, and whether it serves
`/health` and `/skill.md`.

Query parameters:
- `base_url` (string, required) — root address of the service to check.

```
curl "{{BASE_URL}}/probe?base_url={{BASE_URL}}"
```

Example response:

```json
{"base_url": "{{BASE_URL}}", "up": true, "checks": {"root": {"alive": true, "latency_ms": 129.9, "status_code": 200}, "health_endpoint": {"alive": true, "latency_ms": 192.3, "status_code": 200}, "skillmd_served": {"alive": true, "latency_ms": 190.8, "status_code": 200}}, "note": null}
```

Response fields: `up` (boolean), `checks.root`, `checks.health_endpoint`,
`checks.skillmd_served` (each with `alive`, `latency_ms`, `status_code`),
and `note` (non-null only when the target looks asleep).

### GET /history

Uptime record for any URL Town Watch has checked before.

Query parameters:
- `url` (string, required) — the URL to look up.

```
curl "{{BASE_URL}}/history?url={{BASE_URL}}"
```

Example response:

```json
{"url": "{{BASE_URL}}", "checks": 12, "uptime_pct": 100.0, "avg_latency_ms": 161.4, "last_check": {"ts": 1783690522.3, "ok": true, "latency_ms": 129.9}}
```

Response fields: `checks` (count), `uptime_pct`, `avg_latency_ms`,
`last_check`. A URL with no history returns `checks: 0` and a note — run
/probe or /verdict on it first.

### GET /skill.md

This document, served as plain text with the live base URL filled in.

## Recommended workflow for agents

1. Before relying on any registry skill, call GET /verdict with its skill.md URL.
2. On `rely`: proceed. On `caution`: probe the specific endpoint you need via
   GET /probe first. On `avoid`: choose a different skill.
3. When writing a SkillMD of your own, POST /lint it and apply each `fix`
   until `agent_ready` is true.
4. To compare two similar skills, prefer the one with the higher /verdict
   score, breaking ties with /history uptime.

## Error handling

Bad input returns a JSON object with an `error` field describing exactly what
to send instead — never an unexplained failure. A `verdict` of `avoid` with
reason "skill.md unreachable" means the target service is down, not Town
Watch. All checks respect an 8-second timeout per URL, so no call hangs.
