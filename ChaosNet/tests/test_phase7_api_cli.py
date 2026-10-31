"""Tests for Phase 7: FastAPI REST API, WebSocket event streaming, and CLI runner."""

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from chaosnet.api.main import app, manager


@pytest.fixture(autouse=True)
def reset_api_manager() -> None:
    """Reset the API manager state before and after each test."""
    manager.reset(scenario_path="scenarios/default_vpc.json")
    yield
    manager.pause()
    manager.reset(scenario_path="scenarios/default_vpc.json")


def test_get_topology_endpoint() -> None:
    """Verify GET /topology returns nodes, links, and VPC summary."""
    with TestClient(app) as client:
        response = client.get("/topology")
        assert response.status_code == 200
        data = response.json()

        assert "vpc" in data
        assert "nodes" in data
        assert "links" in data
        assert "summary" in data
        assert data["summary"]["total_nodes"] == 13


def test_simulation_step_pause_and_reset_endpoints() -> None:
    """Verify /simulation/step, /simulation/pause, and /simulation/reset endpoints."""
    with TestClient(app) as client:
        # Step once
        res_step = client.post("/simulation/step")
        assert res_step.status_code == 200
        step_data = res_step.json()
        assert step_data["status"] == "stepped"
        assert step_data["tick"] == 1
        assert "metric" in step_data

        # Pause
        res_pause = client.post("/simulation/pause")
        assert res_pause.status_code == 200
        assert res_pause.json()["status"] == "paused"

        # Start
        res_start = client.post("/simulation/start", json={"tick_rate_hz": 5.0})
        assert res_start.status_code == 200
        assert res_start.json()["status"] == "running"
        manager.pause()

        # Reset
        res_reset = client.post("/simulation/reset")
        assert res_reset.status_code == 200
        assert res_reset.json()["status"] == "reset"
        assert res_reset.json()["tick"] == 0


def test_chaos_inject_endpoint() -> None:
    """Verify POST /chaos/{event_type} injects failure and returns audit entry."""
    with TestClient(app) as client:
        # Inject kill_node on app-a1
        res = client.post(
            "/chaos/kill_node",
            json={"target": "app-a1", "duration": 4},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "injected"
        assert data["event"]["event_type"] == "kill_node"
        assert data["event"]["target"] == "app-a1"

        # Verify node is DOWN
        node = manager.engine.topology.get_node("app-a1")
        assert node.status.value == "DOWN"

        # Invalid event type returns 400
        bad_res = client.post("/chaos/nonexistent_type", json={"target": "app-a1"})
        assert bad_res.status_code == 400


@pytest.mark.parametrize(
    ("event_type", "payload", "expected_target"),
    [
        ("kill_node", {"target": "app-a1", "duration": 2}, None),
        ("kill_az", {"target": "az-a", "duration": 2}, None),
        ("drop_link", {"target": "router-a|router-b"}, "router-a->router-b"),
        ("latency_spike", {"target": "app-a1", "magnitude": 25}, None),
        ("packet_loss", {"target": "router-a|router-b", "magnitude": 0.3}, "router-a->router-b"),
        ("network_partition", {}, None),
        ("db_primary_failure", {}, None),
        ("recover", {"target": "az-a"}, None),
    ],
)
def test_chaos_injection_payloads(
    event_type: str, payload: dict[str, object], expected_target: str | None
) -> None:
    """Verify each frontend chaos injection payload is accepted."""
    with TestClient(app) as client:
        response = client.post(f"/chaos/{event_type}", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "injected"
    if expected_target:
        assert data["event"]["target"] == expected_target


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "Frontend" / "dist" / "index.html").exists(),
    reason="Frontend build is absent",
)
def test_frontend_routes_serve_spa() -> None:
    """Verify frontend routes return the built SPA entry point."""
    with TestClient(app) as client:
        for path in ("/", "/simulator"):
            response = client.get(path)
            assert response.status_code == 200
            assert "ChaosNet" in response.text


def test_get_metrics_endpoint() -> None:
    """Verify GET /metrics returns the simulation summary report."""
    with TestClient(app) as client:
        client.post("/simulation/step")
        client.post("/simulation/step")

        res = client.get("/metrics")
        assert res.status_code == 200
        summary = res.json()
        assert summary["total_ticks"] == 2
        assert summary["total_requests"] > 0
        assert "availability_pct" in summary
        assert "p95_latency_ms" in summary
        assert "timeline" in summary


def test_websocket_streaming_and_control() -> None:
    """Verify WebSocket /ws receives initial state, processes commands, and streams tick updates."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            # 1. On connection, receive INITIAL_STATE
            init_msg = ws.receive_json()
            assert init_msg["type"] == "INITIAL_STATE"
            assert "topology" in init_msg

            # 2. Send step command through WebSocket
            ws.send_json({"action": "step"})
            update_msg = ws.receive_json()
            assert update_msg["type"] == "TICK_UPDATE"
            assert update_msg["tick"] == 1
            assert "metric" in update_msg

            # 3. Send chaos injection through WebSocket
            ws.send_json(
                {
                    "action": "inject",
                    "event_type": "kill_node",
                    "target": "app-b1",
                    "duration": 5,
                }
            )
            chaos_msg = ws.receive_json()
            assert chaos_msg["type"] == "CHAOS_INJECTED"
            assert chaos_msg["chaos_event"]["target"] == "app-b1"


def test_cli_runner_execution() -> None:
    """Verify cli.py runs a scenario and exits with 0."""
    result = subprocess.run(
        [
            sys.executable,
            "cli.py",
            "run",
            "scenarios/az_failure.json",
            "--ticks",
            "10",
            "--requests-per-tick",
            "2",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "CHAOSNET SIMULATION SUMMARY REPORT" in result.stdout
    assert "Total Ticks Simulated:" in result.stdout
