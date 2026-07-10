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

Liveness check. Returns `{"status": "ok", "service": "townwatch", "time": <unix>}`.
Call this first if any other request misbehaves.

### GET /verdict

The primary primitive. Fetches a skill.md from a URL, lints it, live-checks
every link inside it, and returns a single decision.

Query parameters:
- `skill_url` (string, required) — full URL of the skill.md to judge.

```
curl "{{BASE_URL}}/verdict?skill_url={{BASE_URL}}/skill.md"
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
