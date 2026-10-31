"""FastAPI application providing REST endpoints and live WebSocket event streaming for ChaosNet."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from chaosnet.core.chaos import ChaosEvent, ChaosEventType
from chaosnet.core.engine import SimulationConfig, SimulationEngine
from chaosnet.core.metrics import TickMetrics


class ChaosInjectRequest(BaseModel):
    """Payload for injecting a chaos event via REST API."""

    target: Optional[str] = Field(
        default=None,
        description="Target node ID, AZ ID, or link specifier ('source->target')",
    )
    duration: Optional[int] = Field(
        default=None,
        ge=1,
        description="Duration in ticks before automatic recovery (None for manual recovery)",
    )
    magnitude: float = Field(
        default=100.0,
        ge=0.0,
        description="Magnitude parameter (e.g. latency spike ms or packet loss fraction)",
    )


class SimulationStartRequest(BaseModel):
    """Options for starting continuous background simulation ticking."""

    tick_rate_hz: float = Field(
        default=2.0,
        ge=0.1,
        le=50.0,
        description="Ticks per second in background running mode",
    )
    requests_per_tick: Optional[int] = Field(
        default=None,
        ge=1,
        description="Override requests generated per tick",
    )


class SimulationResetRequest(BaseModel):
    """Options for resetting simulation state."""

    scenario_path: Optional[str] = Field(
        default=None,
        description="Optional scenario file path to reload topology and chaos script",
    )


class SimulationManager:
    """Manages the lifecycle, background execution, and WebSocket broadcast of a simulation."""

    def __init__(self, default_scenario: str = "scenarios/default_vpc.json") -> None:
        """Initialize the simulation manager."""
        self.default_scenario = default_scenario
        self.current_scenario_path = default_scenario
        self.engine: SimulationEngine = self._load_engine(default_scenario)
        self.is_running: bool = False
        self.tick_rate_hz: float = 2.0
        self._bg_task: Optional[asyncio.Task[None]] = None
        self.connected_websockets: set[WebSocket] = set()

    def _load_engine(self, scenario_path: str) -> SimulationEngine:
        """Load a SimulationEngine from a scenario JSON file."""
        path = Path(scenario_path)
        if not path.exists():
            path = Path(__file__).resolve().parent.parent.parent / scenario_path
        if not path.exists():
            raise FileNotFoundError(f"Scenario file '{scenario_path}' not found.")
        return SimulationEngine.from_scenario_file(path)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast a JSON message to all connected WebSocket clients."""
        dead_sockets: list[WebSocket] = []
        for ws in self.connected_websockets:
            try:
                await ws.send_json(message)
            except Exception:
                dead_sockets.append(ws)

        for ws in dead_sockets:
            self.connected_websockets.discard(ws)

    def step_once(self) -> TickMetrics:
        """Advance the simulation by a single tick and collect newly emitted events."""
        metric = self.engine.step()
        return metric

    async def _background_tick_loop(self) -> None:
        """Continuous async loop advancing ticks when is_running is True."""
        try:
            while self.is_running:
                start_len = len(self.engine.metrics.timeline)
                metric = self.step_once()
                new_events = self.engine.metrics.timeline[start_len:]

                topo_dict = self.engine.topology.to_dict()
                summary_dict = self.engine.get_summary().to_dict()
                await self.broadcast(
                    {
                        "type": "TICK_UPDATE",
                        "tick": metric.tick,
                        "metric": metric.model_dump(mode="json"),
                        "topology": topo_dict,
                        "topology_summary": {**topo_dict["summary"], **summary_dict},
                        "summary": summary_dict,
                        "events": [e.model_dump(mode="json") for e in new_events],
                    }
                )

                delay = 1.0 / max(0.1, self.tick_rate_hz)
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            pass

    def start(self, tick_rate_hz: float = 2.0, requests_per_tick: Optional[int] = None) -> None:
        """Start or resume continuous simulation."""
        self.tick_rate_hz = tick_rate_hz
        if requests_per_tick is not None:
            self.engine.config.requests_per_tick = requests_per_tick

        if not self.is_running:
            self.is_running = True
            self._bg_task = asyncio.create_task(self._background_tick_loop())

    def pause(self) -> None:
        """Pause continuous simulation."""
        self.is_running = False
        if self._bg_task and not self._bg_task.done():
            self._bg_task.cancel()
            self._bg_task = None

    def reset(self, scenario_path: Optional[str] = None) -> None:
        """Reset the simulation back to tick 0."""
        self.pause()
        target_scenario = scenario_path or self.current_scenario_path
        self.engine = self._load_engine(target_scenario)
        self.current_scenario_path = target_scenario


manager = SimulationManager()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI application lifespan manager for clean background task cleanup."""
    yield
    manager.pause()


app = FastAPI(
    title="ChaosNet VPC Simulator API",
    description="Interactive Cloud VPC & Auto-Failover Simulator REST API and WebSocket events",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/topology", summary="Get VPC topology")
def get_topology() -> dict[str, Any]:
    """Return the complete VPC topology graph, node operational statuses, and link states."""
    return manager.engine.topology.to_dict()


@app.post("/chaos/{event_type}", summary="Inject a chaos failure event")
async def inject_chaos(event_type: str, req: ChaosInjectRequest) -> dict[str, Any]:
    """Inject a simulated infrastructure failure into the active topology."""
    try:
        chaos_type = ChaosEventType(event_type)
    except ValueError:
        valid_types = [e.value for e in ChaosEventType]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid event_type '{event_type}'. Valid types: {valid_types}",
        )

    target = req.target
    if chaos_type == ChaosEventType.NETWORK_PARTITION and not target:
        target = "az-a<->az-b"
    elif (
        chaos_type in (ChaosEventType.DROP_LINK, ChaosEventType.PACKET_LOSS)
        and target
        and "|" in target
    ):
        target = target.replace("|", "->")

    event = ChaosEvent(
        tick=manager.engine.current_tick,
        event_type=chaos_type,
        target=target,
        duration_ticks=req.duration,
        magnitude=req.magnitude,
    )

    try:
        log_entry = manager.engine.chaos.inject(event, current_tick=manager.engine.current_tick)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if log_entry["action"] == "INJECT":
        manager.engine.metrics.record_chaos_injection(
            tick=manager.engine.current_tick,
            event_type=log_entry["event_type"],
            target=log_entry["target"],
            duration_ticks=log_entry.get("duration_ticks"),
            magnitude=log_entry.get("magnitude", 0.0),
        )
    elif log_entry["action"] == "RECOVER":
        manager.engine.metrics.record_recovery(
            tick=manager.engine.current_tick,
            target=log_entry["target"],
            event_type=f"RECOVER_{log_entry['event_type'].upper()}",
        )

    topo_dict = manager.engine.topology.to_dict()
    summary_dict = manager.engine.get_summary().to_dict()
    await manager.broadcast(
        {
            "type": "CHAOS_INJECTED",
            "tick": manager.engine.current_tick,
            "chaos_event": log_entry,
            "topology": topo_dict,
            "summary": summary_dict,
        }
    )

    return {"status": "injected", "event": log_entry, "topology": topo_dict, "summary": summary_dict}


@app.post("/simulation/start", summary="Start or resume simulation ticking")
async def start_simulation(req: SimulationStartRequest = SimulationStartRequest()) -> dict[str, Any]:
    """Start continuous simulation ticks in the background."""
    manager.start(tick_rate_hz=req.tick_rate_hz, requests_per_tick=req.requests_per_tick)
    await manager.broadcast(
        {
            "type": "SIMULATION_STATE",
            "is_running": True,
            "tick": manager.engine.current_tick,
        }
    )
    return {
        "status": "running",
        "tick": manager.engine.current_tick,
        "tick_rate_hz": manager.tick_rate_hz,
    }


@app.post("/simulation/pause", summary="Pause simulation")
async def pause_simulation() -> dict[str, Any]:
    """Pause continuous simulation ticking."""
    manager.pause()
    await manager.broadcast(
        {
            "type": "SIMULATION_STATE",
            "is_running": False,
            "tick": manager.engine.current_tick,
        }
    )
    return {"status": "paused", "tick": manager.engine.current_tick}


@app.post("/simulation/step", summary="Advance simulation by 1 tick")
async def step_simulation() -> dict[str, Any]:
    """Advance the simulation by exactly one tick and return the tick metrics."""
    start_len = len(manager.engine.metrics.timeline)
    metric = manager.step_once()
    new_events = manager.engine.metrics.timeline[start_len:]

    topo_dict = manager.engine.topology.to_dict()
    summary_dict = manager.engine.get_summary().to_dict()
    payload = {
        "type": "TICK_UPDATE",
        "tick": metric.tick,
        "metric": metric.model_dump(mode="json"),
        "topology": topo_dict,
        "topology_summary": {**topo_dict["summary"], **summary_dict},
        "summary": summary_dict,
        "events": [e.model_dump(mode="json") for e in new_events],
    }
    await manager.broadcast(payload)
    return {"status": "stepped", "tick": metric.tick, "metric": metric.model_dump(mode="json")}


@app.post("/simulation/reset", summary="Reset simulation")
async def reset_simulation(req: SimulationResetRequest = SimulationResetRequest()) -> dict[str, Any]:
    """Reset the simulation back to tick 0."""
    try:
        manager.reset(scenario_path=req.scenario_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    topo_dict = manager.engine.topology.to_dict()
    summary_dict = manager.engine.get_summary().to_dict()
    await manager.broadcast(
        {
            "type": "SIMULATION_RESET",
            "tick": 0,
            "topology": topo_dict,
            "summary": summary_dict,
        }
    )
    return {"status": "reset", "tick": 0, "scenario": manager.current_scenario_path}


@app.get("/metrics", summary="Get simulation metrics and summary report")
def get_metrics() -> dict[str, Any]:
    """Return cumulative metrics, MTTR, detection time, percentiles, timeline, and incident reports."""
    summary = manager.engine.get_summary()
    return summary.to_dict()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Live WebSocket connection streaming tick updates and accepting control commands."""
    await websocket.accept()
    manager.connected_websockets.add(websocket)

    # Send initial state snapshot on connect
    try:
        await websocket.send_json(
            {
                "type": "INITIAL_STATE",
                "tick": manager.engine.current_tick,
                "is_running": manager.is_running,
                "topology": manager.engine.topology.to_dict(),
                "summary": manager.engine.get_summary().to_dict(),
            }
        )

        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "step":
                start_len = len(manager.engine.metrics.timeline)
                metric = manager.step_once()
                new_events = manager.engine.metrics.timeline[start_len:]
                topo_dict = manager.engine.topology.to_dict()
                summary_dict = manager.engine.get_summary().to_dict()
                await manager.broadcast(
                    {
                        "type": "TICK_UPDATE",
                        "tick": metric.tick,
                        "metric": metric.model_dump(mode="json"),
                        "topology": topo_dict,
                        "topology_summary": {**topo_dict["summary"], **summary_dict},
                        "summary": summary_dict,
                        "events": [e.model_dump(mode="json") for e in new_events],
                    }
                )

            elif action == "start":
                rate = float(data.get("tick_rate_hz", 2.0))
                reqs = data.get("requests_per_tick")
                manager.start(tick_rate_hz=rate, requests_per_tick=reqs)
                await manager.broadcast(
                    {
                        "type": "SIMULATION_STATE",
                        "is_running": True,
                        "tick": manager.engine.current_tick,
                    }
                )

            elif action == "pause":
                manager.pause()
                await manager.broadcast(
                    {
                        "type": "SIMULATION_STATE",
                        "is_running": False,
                        "tick": manager.engine.current_tick,
                    }
                )

            elif action == "reset":
                manager.reset(scenario_path=data.get("scenario_path"))
                topo_dict = manager.engine.topology.to_dict()
                summary_dict = manager.engine.get_summary().to_dict()
                await manager.broadcast(
                    {
                        "type": "SIMULATION_RESET",
                        "tick": 0,
                        "topology": topo_dict,
                        "summary": summary_dict,
                    }
                )

            elif action == "inject":
                try:
                    event_type = ChaosEventType(data["event_type"])
                    raw_target = data.get("target")
                    if event_type == ChaosEventType.NETWORK_PARTITION and not raw_target:
                        raw_target = "az-a<->az-b"
                    elif (
                        event_type in (ChaosEventType.DROP_LINK, ChaosEventType.PACKET_LOSS)
                        and raw_target
                        and "|" in raw_target
                    ):
                        raw_target = raw_target.replace("|", "->")

                    event = ChaosEvent(
                        tick=manager.engine.current_tick,
                        event_type=event_type,
                        target=raw_target,
                        duration_ticks=data.get("duration") or data.get("duration_ticks"),
                        magnitude=float(data.get("magnitude", 100.0)),
                    )
                    log_entry = manager.engine.chaos.inject(
                        event, current_tick=manager.engine.current_tick
                    )
                    if log_entry["action"] == "INJECT":
                        manager.engine.metrics.record_chaos_injection(
                            tick=manager.engine.current_tick,
                            event_type=log_entry["event_type"],
                            target=log_entry["target"],
                            duration_ticks=log_entry.get("duration_ticks"),
                            magnitude=log_entry.get("magnitude", 0.0),
                        )
                    elif log_entry["action"] == "RECOVER":
                        manager.engine.metrics.record_recovery(
                            tick=manager.engine.current_tick,
                            target=log_entry["target"],
                            event_type=f"RECOVER_{log_entry['event_type'].upper()}",
                        )

                    topo_dict = manager.engine.topology.to_dict()
                    summary_dict = manager.engine.get_summary().to_dict()
                    await manager.broadcast(
                        {
                            "type": "CHAOS_INJECTED",
                            "tick": manager.engine.current_tick,
                            "chaos_event": log_entry,
                            "topology": topo_dict,
                            "summary": summary_dict,
                        }
                    )
                except Exception as exc:
                    await websocket.send_json({"type": "ERROR", "message": str(exc)})

    except WebSocketDisconnect:
        manager.connected_websockets.discard(websocket)
    except Exception:
        manager.connected_websockets.discard(websocket)


# Mount static frontend build if present
frontend_dist = Path(__file__).resolve().parent.parent.parent / "Frontend" / "dist"
if (frontend_dist / "assets").exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="frontend_assets")

if frontend_dist.exists():
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa_frontend(full_path: str) -> FileResponse:
        """Serve SPA assets and fallback to index.html for frontend routing."""
        target_file = frontend_dist / full_path
        if full_path and target_file.is_file():
            return FileResponse(target_file)
        return FileResponse(frontend_dist / "index.html")
