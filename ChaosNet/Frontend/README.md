# ChaosNet — Failure, made visible

ChaosNet is a cloud VPC and auto-failover simulator. The public landing page at `/` centers on a guided two-availability-zone failure and recovery story; the complete operations dashboard remains at `/simulator`.

## Run locally

Install frontend dependencies once with `pnpm install`, then run both processes:

```bash
# terminal 1, repository root
python cli.py serve --host 127.0.0.1 --port 8000

# terminal 2, Frontend/
pnpm dev
```

Vite serves the app at `http://localhost:3000`. Use `/` for the landing page or `/simulator` for the full control room.

## Guided demo and backend connection

The landing page connects to the simulator through REST and WebSocket. By default the browser client uses `http://127.0.0.1:8000` and `ws://127.0.0.1:8000/ws`. It reads `GET /topology` and `GET /metrics`, listens to `INITIAL_STATE` and `TICK_UPDATE`, and issues reset, start, `kill_az` and recovery controls through the existing WebSocket control messages when connected, with REST controls as a fallback.

If the browser cannot reach a complete topology and metric snapshot, the guided story switches to a deterministic local sequence. It is visibly labelled **Deterministic local demo** and its illustrative metrics are not represented as live backend measurements. API-backed captions confirm failure, promotion and recovery only when the reported topology supports those states; otherwise the page says it is awaiting confirmation.

The default URLs are `http://127.0.0.1:8000` and `ws://127.0.0.1:8000/ws`; optional overrides can point to a deployed backend in `Frontend/.env.local`:

```dotenv
VITE_API_BASE_URL=https://api.example.com
VITE_WS_URL=wss://api.example.com/ws
```

A hosted frontend must set both values to a reachable backend. Loopback addresses (`127.0.0.1` and `localhost`) refer to the viewer's own machine, not the host or preview sandbox. The simulator must allow connections from the browser origin used to open the dashboard; configure the backend's CORS and WebSocket origin policy accordingly.

The supplied backend protocol does not define a strategy-change command or field. The existing strategy selector therefore changes request allocation in local demo mode; a live backend continues to apply its own configured strategy.

## Backend contract

REST endpoints: `GET /topology`, `GET /metrics`, `POST /simulation/step`, `/simulation/start`, `/simulation/pause`, `/simulation/reset`, and `POST /chaos/{event_type}`.

WebSocket: `/ws`. The client handles `INITIAL_STATE` and `TICK_UPDATE` messages and sends `start`, `pause`, `step`, `reset` and `inject` control messages.
