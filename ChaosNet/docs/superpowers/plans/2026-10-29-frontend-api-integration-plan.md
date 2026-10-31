# Frontend API Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the ChaosNet landing page and full simulator continuously connected to every existing REST and WebSocket control surface, with explicit live, reconnecting, and local-demo states.

**Architecture:** Preserve the existing React/Vite frontend and FastAPI backend. Centralize endpoint URL resolution, request timeout/error handling, payload normalization, and WebSocket message types in the existing frontend API layer; keep route-specific behavior in the landing demo and simulator. Fix the backend's static SPA serving imports and verify the complete REST/WebSocket contract with the existing Python test suite.

**Tech Stack:** React 18, TypeScript 5.7, Vite 6, Lucide React, browser Fetch/WebSocket APIs, FastAPI, Pydantic, pytest, FastAPI TestClient.

**Spec:** `docs/superpowers/specs/2026-10-29-chaosnet-landing-page-design.md`

## Global Constraints

- The first delivery is the landing page and its self-contained guided demo.
- Reuse the existing simulator terminology and scenario behavior where practical.
- Do not add a design system, state-management library, chart library, or animation library unless an existing project dependency requires it.
- The landing-page demo must visibly distinguish live API operation from deterministic local mode.
- Do not fabricate production claims, customer logos, or operational data.
- Maintain responsive behavior down to mobile, visible keyboard focus, and reduced-motion behavior.
- Keep the existing full simulator reachable at `/simulator`.
- Use `VITE_API_BASE_URL` and `VITE_WS_URL` for non-local deployments; retain a local fallback for the documented development ports.

## Review Focus

- Backend is started with the frontend build present: `/`, `/simulator`, and asset requests must not crash on missing `StaticFiles`/`FileResponse` imports; pin this with a TestClient route test in Task 1.
- A WebSocket disconnects during a control send: the client must not lose the action silently; it must reconnect and use REST or show an explicit unavailable state; pin the transport fallback in Task 2's build/runtime checklist and the route behavior in Task 3.
- A backend sends an incomplete or differently shaped topology/metric payload: the UI must preserve the last valid state and never render `NaN`, blank node sets, or fake live values; pin this with normalization examples in Task 2 and a browser verification in Task 3.
- The user injects every supported chaos type, including `drop_link`, `packet_loss`, and `network_partition`: the request must use the backend's accepted target and magnitude format; pin this with API contract tests in Task 1 and control coverage in Task 3.
- The landing demo is opened without a reachable backend: it must remain interactive but clearly say it is a deterministic local demo, and must not label illustrative values as measured live values; pin this with the existing local-mode path and manual verification in Task 4.

---

### Task 1: Verify and harden the FastAPI serving and endpoint contract

**Files:**
- Modify: `chaosnet/api/main.py:10-18, 468-481`
- Modify: `tests/test_phase7_api_cli.py:22-132`

**Interfaces:**
- Produces: working REST endpoints `GET /topology`, `GET /metrics`, `POST /simulation/step`, `POST /simulation/start`, `POST /simulation/pause`, `POST /simulation/reset`, and `POST /chaos/{event_type}`.
- Produces: WebSocket `/ws` messages `INITIAL_STATE`, `TICK_UPDATE`, `SIMULATION_STATE`, `SIMULATION_RESET`, `CHAOS_INJECTED`, and `ERROR`.
- Produces: SPA fallback responses for `/` and `/simulator` when `Frontend/dist` exists.

- [ ] **Step 1: Add a failing static-serving test**

Add this test after the existing topology test:

```python
def test_spa_routes_serve_frontend_when_dist_exists() -> None:
    """Verify the API serves the built SPA for both public routes."""
    from chaosnet.api.main import frontend_dist

    if not (frontend_dist / "index.html").exists():
        pytest.skip("Frontend/dist is not built in this checkout")

    with TestClient(app) as client:
        home = client.get("/")
        simulator = client.get("/simulator")

    assert home.status_code == 200
    assert simulator.status_code == 200
    assert "ChaosNet" in home.text
    assert "ChaosNet" in simulator.text
```

- [ ] **Step 2: Run the focused test and verify the current failure**

Run:

```bash
pytest tests/test_phase7_api_cli.py::test_spa_routes_serve_frontend_when_dist_exists -v
```

Expected: the test fails at module import or route handling if the static response classes are not imported.

- [ ] **Step 3: Import the static serving classes used by the existing code**

At the FastAPI imports in `chaosnet/api/main.py`, add:

```python
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
```

Do not change the route fallback logic or introduce another server layer.

- [ ] **Step 4: Add endpoint contract coverage for link target normalization and all chaos routes**

Add this test to `tests/test_phase7_api_cli.py`:

```python
@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("kill_node", {"target": "app-a1", "duration": 2}),
        ("kill_az", {"target": "az-a", "duration": 2}),
        ("drop_link", {"target": "router-a|router-b"}),
        ("latency_spike", {"target": "app-a1", "magnitude": 25}),
        ("packet_loss", {"target": "router-a|router-b", "magnitude": 0.3}),
        ("network_partition", {}),
        ("db_primary_failure", {}),
        ("recover", {"target": "az-a"}),
    ],
)
def test_all_supported_chaos_event_types_are_accepted(event_type: str, payload: dict[str, object]) -> None:
    """Verify the browser's documented chaos payload shapes are accepted."""
    with TestClient(app) as client:
        response = client.post(f"/chaos/{event_type}", json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "injected"
```

- [ ] **Step 5: Run the API test module**

Run:

```bash
pytest tests/test_phase7_api_cli.py -v
```

Expected: all endpoint, WebSocket, chaos, and SPA tests pass.

- [ ] **Step 6: Commit the backend contract verification**

```bash
git add chaosnet/api/main.py tests/test_phase7_api_cli.py
git commit -m "fix: verify frontend API serving contract\n\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: Make the frontend transport and payload normalization explicit and resilient

**Files:**
- Modify: `Frontend/src/api.ts:1-40, 143-197`
- Modify: `Frontend/src/types.ts:1-57`
- Modify: `Frontend/.env.example:1-2`
- Modify: `Frontend/README.md:14-35`

**Interfaces:**
- Consumes: backend REST paths and JSON payloads from Task 1.
- Produces: `API_BASE`, `WS_URL`, `request<T>`, `getTopology`, `getMetrics`, `postSimulation`, `postChaos`, `mergeNodes`, `mergeLinks`, `normalizeMetric`, and `normalizeEvents` for both React routes.
- Produces: stable `NodeStatus`, `ChaosAction`, `TickMetric`, `TimelineEvent`, and topology response types without requiring a new runtime dependency.

- [ ] **Step 1: Define the endpoint names and payload types used by both routes**

Add these types near the existing frontend interfaces:

```ts
export type SimulationAction = 'step' | 'start' | 'pause' | 'reset';

export interface TopologyResponse {
  vpc?: Record<string, unknown>;
  nodes?: unknown;
  links?: unknown;
  summary?: Record<string, unknown>;
}

export interface ApiErrorShape {
  detail?: string;
  message?: string;
}
```

Keep the existing normalized UI types as the source of truth for rendering. Do not mirror every backend Pydantic model in TypeScript.

- [ ] **Step 2: Make URL resolution safe for same-origin and hosted deployments**

Keep the current local fallback, but implement URL resolution with these rules:

```ts
const configuredApi = String(import.meta.env.VITE_API_BASE_URL ?? '').trim();
const sameOriginBackend = typeof window !== 'undefined' && window.location.port === '8000';
export const API_BASE = (configuredApi || (sameOriginBackend ? window.location.origin : 'http://127.0.0.1:8000')).replace(/\/$/, '');

const configuredWs = String(import.meta.env.VITE_WS_URL ?? '').trim();
export const WS_URL = configuredWs || (sameOriginBackend
  ? `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`
  : 'ws://127.0.0.1:8000/ws');
```

Do not use a hard-coded public hostname or canonical URL.

- [ ] **Step 3: Improve request errors without leaking fake live state**

Change `request<T>` so non-2xx responses include the backend's `detail`/`message` when available, while preserving abort timeout behavior:

```ts
if (!response.ok) {
  const body = await response.json().catch(() => ({} as ApiErrorShape));
  throw new Error(String(body.detail ?? body.message ?? `Backend returned ${response.status}`));
}
```

Keep the existing four-second timeout and always clear it in `finally`.

- [ ] **Step 4: Normalize incomplete payloads conservatively**

Keep the last valid UI state when `nodes`, `links`, `metric`, or `events` are absent. Change `normalizeMetric` so it uses a provided fallback metric rather than hard-coded values when a live response is incomplete:

```ts
export function normalizeMetric(
  input: Record<string, unknown>,
  tickFallback = 0,
  fallback: TickMetric = demoMetric,
): TickMetric {
  const sent = numberFrom(input.requests_sent, fallback.requests_sent);
  const succeeded = numberFrom(input.requests_succeeded, fallback.requests_succeeded);
  return {
    tick: numberFrom(input.tick, tickFallback),
    requests_sent: sent,
    requests_succeeded: succeeded,
    requests_failed: numberFrom(input.requests_failed, Math.max(0, sent - succeeded)),
    success_rate_pct: numberFrom(input.success_rate_pct, sent ? (succeeded / sent) * 100 : fallback.success_rate_pct),
    avg_latency_ms: numberFrom(input.avg_latency_ms, fallback.avg_latency_ms),
    p95_latency_ms: numberFrom(input.p95_latency_ms, fallback.p95_latency_ms),
    healthy_app_capacity: numberFrom(input.healthy_app_capacity, fallback.healthy_app_capacity),
    active_incidents: numberFrom(input.active_incidents, fallback.active_incidents),
  };
}
```

Use the existing initial metric values as `demoMetric`; do not label them as backend measurements.

- [ ] **Step 5: Include the missing `drop_link` control type and documented target forms**

Keep `ChaosAction` including `drop_link`, and ensure the transport accepts both `source|target` from UI controls and the backend's `source->target` form. The REST helper should send JSON unchanged; the API already normalizes pipe targets.

- [ ] **Step 6: Document connection modes and environment overrides**

Update `Frontend/.env.example` to show that the values are optional local defaults and may point to a deployed API. Update `Frontend/README.md` with the exact two-process local start sequence:

```bash
# terminal 1, repository root
python cli.py serve --host 127.0.0.1 --port 8000

# terminal 2, Frontend/
pnpm dev
```

Document that a hosted frontend must set `VITE_API_BASE_URL` and `VITE_WS_URL` to a reachable backend; loopback addresses refer to the viewer's machine.

- [ ] **Step 7: Type-check and build the frontend**

Run:

```bash
cd Frontend && npm run build
```

Expected: TypeScript and Vite build pass with no `NaN`-producing type regressions.

- [ ] **Step 8: Commit the transport layer**

```bash
git add Frontend/src/api.ts Frontend/src/types.ts Frontend/.env.example Frontend/README.md
git commit -m "feat: harden frontend API transport\n\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: Connect the full simulator to every REST and WebSocket control

**Files:**
- Modify: `Frontend/src/Simulator.tsx:71-79, 227-399, 457-590`
- Modify: `Frontend/src/types.ts:1-7`
- Modify: `Frontend/src/styles.css` only if the new chaos option needs an existing control style adjustment

**Interfaces:**
- Consumes: shared transport and normalized payloads from Task 2.
- Produces: live controls for `step`, `start`, `pause`, `reset`, `kill_node`, `kill_az`, `drop_link`, `latency_spike`, `packet_loss`, `network_partition`, `db_primary_failure`, and `recover`.
- Produces: visible connection status that distinguishes WebSocket live, REST-only, reconnecting, and local demo states.

- [ ] **Step 1: Add the missing `drop_link` scenario to the control list**

Add a scenario option beside `packet_loss`:

```tsx
{ id: 'drop_link', title: 'Drop link', description: 'Take a network link offline', icon: Link2 }
```

Use the existing link selector and send `target` as `source|target`. Do not add a new control panel.

- [ ] **Step 2: Route all controls through WebSocket first and REST second**

Preserve the existing `control()` and `injectChaos()` functions, but make the fallback deterministic:

```tsx
if (ws?.readyState === WebSocket.OPEN) {
  ws.send(JSON.stringify(message));
  setConnectionMode('websocket');
  return;
}

try {
  await postSimulation(endpoint, body);
  setConnectionMode('rest');
} catch (error) {
  setConnectionMode('offline');
  appendEvent('HEALTH', error instanceof Error ? error.message : 'Backend request failed', undefined, 'connection_error');
}
```

For injection, apply local visual state only when the backend request was not accepted; when accepted, let `CHAOS_INJECTED` and subsequent topology updates become the source of truth. Keep the local fallback available when no backend is reachable.

- [ ] **Step 3: Handle all server message types consistently**

Ensure `INITIAL_STATE`, `TICK_UPDATE`, `SIMULATION_STATE`, `SIMULATION_RESET`, and `CHAOS_INJECTED` update tick, nodes, links, metrics, events, and running state using the normalized helpers. Handle `ERROR` by appending a visible HEALTH event and retaining the last valid state.

Do not clear a working topology because a message contains only `topology_summary`; only merge fields actually present.

- [ ] **Step 4: Make reconnect behavior bounded and visible**

Keep one socket for the lifetime of the simulator route. On close, retry after 2.5 seconds while mounted, but clear the timer on unmount. Show `RECONNECTING` while disconnected from both REST and WebSocket; show `REST LINK` when REST responds; show `LIVE LINK` when WebSocket is open. Do not create an interval per reconnect attempt.

- [ ] **Step 5: Verify the full simulator manually against the live API**

Start the backend and frontend, then open `/simulator`. Verify:

1. Initial REST topology and metrics load.
2. WebSocket state changes to LIVE LINK.
3. Play sends `start` and tick updates arrive.
4. Pause stops tick updates.
5. Step advances one tick.
6. Reset returns to tick zero and restores topology.
7. Each chaos option sends the expected endpoint/message and updates the event terminal.
8. Closing the backend changes the label to reconnecting without crashing the page; restarting it reconnects.

- [ ] **Step 6: Build the frontend**

Run:

```bash
cd Frontend && npm run build
```

Expected: PASS.

- [ ] **Step 7: Commit the full simulator connection**

```bash
git add Frontend/src/Simulator.tsx Frontend/src/types.ts Frontend/src/styles.css
 git commit -m "feat: connect simulator controls to every chaos endpoint\n\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: Keep the landing demo live, replayable, and honest about local mode

**Files:**
- Modify: `Frontend/src/landing/useGuidedDemo.ts:47-438`
- Modify: `Frontend/src/landing/GuidedFailureDemo.tsx:12-59`
- Modify: `Frontend/src/landing/demoModel.ts:1-85` only if local-mode evidence needs a correction
- Modify: `Frontend/src/landing/TopologyScene.tsx:52-112` only if live topology status needs a rendering fix

**Interfaces:**
- Consumes: Task 2 transport, normalized topology, metrics, events, and WebSocket lifecycle.
- Produces: guided sequence with live API evidence when available, deterministic local fallback when unavailable, pause/resume, replay, technical details, and explicit source labels.

- [ ] **Step 1: Preserve the three source states**

Keep `checking`, `live`, and `local`. The UI must show:

- `LIVE API · WS` when the socket is open and live state is being received.
- `LIVE API · REST` when the API is reachable but the socket is reconnecting.
- `DETERMINISTIC LOCAL DEMO` when the backend cannot provide a complete snapshot.

Never show local illustrative values under a LIVE label.

- [ ] **Step 2: Make live run setup and replay reset the backend**

When a live run starts, execute this exact sequence through WebSocket-first controls with REST fallback:

```ts
await simulationControl('reset');
await simulationControl('start', { tick_rate_hz: 2, requests_per_tick: 10 });
await injectControl('kill_az', { target: 'az-a', duration: 60 });
```

At the end, request `recover` for `az-a`, wait for topology evidence that all nodes are up and exactly one database is `PRIMARY`, then pause. If any request fails, stop the live sequence and show the failure reason rather than silently switching to fabricated live values.

- [ ] **Step 3: Confirm captions from actual evidence**

Use the existing predicates and event evidence:

- Zone A caption requires all Zone A nodes to report `DOWN`.
- Health-check caption requires a health event or an explicit waiting state.
- Reroute caption requires a reroute event or an explicit waiting state.
- Promotion caption requires `db-replica-b` to report `PRIMARY`.
- Recovery caption requires all nodes up and exactly one primary.

Keep the plain-language headline first and show the event type/tick/target/change only in the technical disclosure.

- [ ] **Step 4: Verify local mode without a backend**

Run the frontend without starting FastAPI. Open `/`, click `Run the failure demo`, pause, resume, replay, click a topology node, and open `Show technical details`. Confirm the page remains interactive and visibly says the values are illustrative local-demo values.

- [ ] **Step 5: Verify live mode with the actual backend**

Run:

```bash
python cli.py serve --host 127.0.0.1 --port 8000
cd Frontend && npm run dev
```

Open `http://localhost:3000/`, run the guided demo, and verify the browser observes the actual topology, tick stream, chaos injection, database role transition, recovery state, and final metrics. Stop/restart the backend during the demo and confirm the page says it is waiting or stopped instead of claiming recovery was confirmed.

- [ ] **Step 6: Build and commit the landing connection**

Run:

```bash
cd Frontend && npm run build
```

Expected: PASS.

```bash
git add Frontend/src/landing/useGuidedDemo.ts Frontend/src/landing/GuidedFailureDemo.tsx Frontend/src/landing/demoModel.ts Frontend/src/landing/TopologyScene.tsx
git commit -m "feat: keep guided landing demo connected\n\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: Run the complete verification pass and keep route metadata synchronized

**Files:**
- Modify: `Frontend/public/manus-routes.json:1`
- Modify: `Frontend/index.html:7-22` only if build output metadata is stale
- Modify: `Frontend/README.md` only if the final run instructions need correction

**Interfaces:**
- Consumes: completed backend and frontend integration from Tasks 1–4.
- Produces: a buildable SPA whose `/` and `/simulator` routes are declared and served consistently.

- [ ] **Step 1: Verify route manifest**

Keep exactly these public route entries:

```json
{"routes":[{"path":"/","title":"ChaosNet — Failure, made visible"},{"path":"/simulator","title":"ChaosNet — Full simulator"}]}
```

- [ ] **Step 2: Run backend tests**

Run from the repository root:

```bash
pytest -v
```

Expected: all existing tests and the new API/static-serving tests pass.

- [ ] **Step 3: Run the production frontend build**

Run:

```bash
cd Frontend && npm run build
```

Expected: PASS and `Frontend/dist/index.html` exists.

- [ ] **Step 4: Verify FastAPI serves the production frontend**

Start the backend and request both routes:

```bash
python cli.py serve --host 127.0.0.1 --port 8000
curl -f http://127.0.0.1:8000/
curl -f http://127.0.0.1:8000/simulator
curl -f http://127.0.0.1:8000/topology
curl -f http://127.0.0.1:8000/metrics
```

Expected: the first two return the SPA HTML and the API endpoints return JSON.

- [ ] **Step 5: Perform responsive and accessibility smoke checks**

In a browser, check desktop width and a 375px mobile viewport. Confirm keyboard focus is visible for header links, demo controls, node buttons, chaos controls, and technical details. Enable reduced motion and confirm the page still exposes every state without animated particles.

- [ ] **Step 6: Commit final metadata and verification-only changes**

```bash
git add Frontend/public/manus-routes.json Frontend/index.html Frontend/README.md
 git commit -m "chore: verify ChaosNet frontend routes\n\nCo-Authored-By: Claude Code <noreply@anthropic.com>"
```

## Self-review

- **Spec coverage:** the plan covers the approved live guided demo, explicit local fallback, REST/WebSocket integration, route preservation, responsive/accessibility checks, and verified technical evidence without adding a new framework.
- **Placeholder scan:** no implementation step relies on TBD/TODO language, undefined files, or undefined endpoint names.
- **Type consistency:** `ChaosAction` includes every chaos event named by the backend; transport helpers remain the existing `getTopology`, `getMetrics`, `postSimulation`, and `postChaos` interfaces; both routes consume the same normalizers.
- **Review focus coverage:** static serving is tested in Task 1; transport and malformed payload behavior are covered in Task 2; every chaos action and reconnection behavior are covered in Task 3; local/live honesty and evidence-gated captions are covered in Task 4.
