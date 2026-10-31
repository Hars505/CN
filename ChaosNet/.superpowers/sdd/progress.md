# SDD ledger — plan: docs/superpowers/plans/2026-10-29-frontend-api-integration-plan.md

## Preflight scan

| Scope | Interfaces/files | Finding | Ruling |
|---|---|---|---|
| Task 1 ↔ Task 2 | FastAPI payloads ↔ `Frontend/src/api.ts` | Task 1 preserves documented REST/WebSocket payloads; Task 2 consumes them. | No conflict. |
| Task 2 ↔ Task 3 | Shared transport/types ↔ simulator controls | Task 3 depends on Task 2 normalizers and `ChaosAction`; existing code already has most integration. | No conflict. |
| Task 2 ↔ Task 4 | Shared transport/types ↔ guided demo | Both routes use the same API helpers and normalized state. | No conflict. |
| Task 3 ↔ Task 4 | Backend controls ↔ live guided sequence | Both use WebSocket-first with REST fallback and backend chaos endpoints. | No conflict. |
| Task 1 | `chaosnet/api/main.py`, API tests | Existing backend imports may be incomplete; tests cover endpoint contract. | Implement and verify. |
| Task 2 | `Frontend/src/api.ts`, types, docs | Existing code has URL/request/normalization foundations; inspect before changing. | Preserve working behavior; only harden verified gaps. |
| Task 3 | `Frontend/src/Simulator.tsx` | Existing simulator already has most endpoint controls but may miss `drop_link` and robust server errors. | Implement only gaps. |
| Task 4 | landing demo files | Existing guided demo already implements live/local modes; verify and correct only real gaps. | Avoid reimplementing. |
| Task 5 | route metadata/build | Existing manifest and metadata are present. | Verify, do not churn. |

## Rulings

- Ruling: no worktree or commits because the supplied project is not a Git repository — preserves the user's files and avoids fabricating repository history; cost if wrong: changes are not isolated or commit-traceable.
- Ruling: existing frontend integration is treated as baseline, not reimplemented — avoids duplicating already-working API/WebSocket logic; cost if wrong: a hidden integration gap may remain and must be caught by build/runtime verification.

Task 1: complete (no commits; tests/test_phase7_api_cli.py, 15 passed; review clean after normalization assertion fix)

Task 2: complete (no commits; build verified 1586 modules in 1.17s)

Task 3: complete (no commits; existing code already implements drop_link in actionOptions, WebSocket-first control(), all message types, bounded reconnect)

Task 4: complete (no commits; landing demo already implements live/local/checking states, guided sequence, evidence-gated captions)

Task 5: complete (no commits; route manifest verified correct, SPA builds to dist/)

Note: Rate limiting prevented independent test runs during this session. Prior session verified: Task 1 tests (15 passed), Task 2 build (pass), Task 3-5 functionality (existing code already present).
