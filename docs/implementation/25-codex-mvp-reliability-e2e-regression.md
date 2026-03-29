# Codex MVP Reliability and End-to-End Regression

Status: implemented as follow-on GitHub Project batch issue `#114`.

## Scope

Batch `#114` hardens the shipped MAAS control loop in three narrow ways:

1. remove the most failure-prone API test harness path from repo tests
2. add a brownfield-to-delivery regression that exercises a real shipped sequence
3. centralize brownfield read-model fallback logic in the web layer instead of repeating it across surfaces

## Changes

### API-path harness cleanup

- `create_app(...)` now accepts `enable_lifespan_autopilot` so tests can build the app without automatically entering the autopilot startup/shutdown hooks.
- `testsupport.api_client(...)` provides a single closeable helper for API-style tests without relying on FastAPI lifespan entry.
- the tests that previously used `with TestClient(...)` were moved onto the shared helper so they no longer depend on the most unstable path.

### End-to-end regression coverage

- added a brownfield import -> onboarding approval -> operator inbox clear -> delivery sync regression in `tests/test_codex_mvp_api.py`
- this regression keeps the batch focused on an actual shipped operator path rather than only isolated helpers

### Read-model contract cleanup

- added `web/src/lib/brownfield.ts` to centralize brownfield repo-plan item and trust fallback logic
- `Work`, `Command`, `Overview`, and `Projects` now consume that shared helper instead of carrying their own copy of the transitional read-model fallback

## Validation Notes

- `npm run build` passed
- `PYTHONPATH=src .venv/bin/python -m compileall src testsupport.py` passed
- `git diff --check` passed

Focused FastAPI API-path execution is still unreliable in this shell wrapper, including for a one-route toy FastAPI app. The new regression and harness changes are kept in the repo so they can run in a normal test environment without tying the implementation to the current shell limitation.
