"""Tests for Phase 6: Metrics collector, detection time, MTTR, p95 latency, and simulation engine."""

import json
from pathlib import Path

from chaosnet.core.chaos import ChaosEvent, ChaosEventType
from chaosnet.core.engine import SimulationConfig, SimulationEngine
from chaosnet.core.health import HealthCheckConfig
from chaosnet.core.metrics import compute_percentile
from chaosnet.core.topology import VPCTopology


SCENARIO_PATH = Path(__file__).resolve().parent.parent / "scenarios" / "default_vpc.json"
AZ_FAILURE_SCENARIO_PATH = Path(__file__).resolve().parent.parent / "scenarios" / "az_failure.json"


def test_percentile_computation() -> None:
    """Verify compute_percentile accurately calculates percentiles."""
    values = [float(i) for i in range(1, 101)]  # 1.0 to 100.0
    assert compute_percentile(values, 0.95) == 96.0
    assert compute_percentile(values, 0.50) == 51.0
    assert compute_percentile([], 0.95) == 0.0


def test_baseline_simulation_run() -> None:
    """Verify clean 10-tick baseline simulation produces 100% availability and valid latency stats."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    config = SimulationConfig(requests_per_tick=10, seed=42)
    engine = SimulationEngine(topology=topo, config=config)

    summary = engine.run(num_ticks=10)

    assert summary.total_ticks == 10
    assert summary.total_requests == 100
    assert summary.successful_requests == 100
    assert summary.failed_requests == 0
    assert summary.availability_pct == 100.0
    assert summary.avg_latency_ms > 0.0
    assert summary.p95_latency_ms >= summary.avg_latency_ms
    assert len(summary.series) == 10
    assert summary.total_requests_lost_during_failover == 0


def test_detection_time_and_failover_metrics() -> None:
    """Verify metrics accurately calculate detection time, MTTR, and requests lost during failover."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    config = SimulationConfig(
        requests_per_tick=4,
        health_config=HealthCheckConfig(interval_ticks=1, unhealthy_threshold=2, healthy_threshold=2),
        seed=42,
    )
    engine = SimulationEngine(topology=topo, config=config)

    # Inject failure at tick 3: kill app-a1 with duration 5 ticks (recovers at tick 8)
    engine.chaos.schedule_event(
        ChaosEvent(tick=3, event_type=ChaosEventType.KILL_NODE, target="app-a1", duration_ticks=5)
    )

    summary = engine.run(num_ticks=10)

    assert summary.total_ticks == 10
    assert summary.total_requests == 40
    # Requests during detection lag (ticks 3 and 4) fail when routed to app-a1
    assert summary.failed_requests > 0
    assert summary.successful_requests > 0
    assert summary.availability_pct < 100.0

    # Incident tracking
    assert len(summary.incidents) == 1
    inc = summary.incidents[0]
    assert inc["fault_type"] == "kill_node"
    assert inc["target"] == "app-a1"
    assert inc["onset_tick"] == 3
    # Health check threshold is 2 -> detected at tick 4 (detection_time = 1 tick)
    assert inc["detected_tick"] == 4
    assert inc["detection_time_ticks"] == 1
    # Failover evicted node at tick 4 (failover_time = 1 tick)
    assert inc["failover_tick"] == 4
    assert inc["failover_time_ticks"] == 1
    # Lost requests tracked
    assert inc["requests_lost"] == summary.failed_requests
    assert summary.total_requests_lost_during_failover == summary.failed_requests

    # Summary metrics averages
    assert summary.mean_detection_time_ticks == 1.0
    assert summary.mean_failover_time_ticks == 1.0


def test_summary_report_json_and_table_formatting() -> None:
    """Verify summary exports valid JSON and human-readable ASCII table."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    engine = SimulationEngine(topology=topo, config=SimulationConfig(requests_per_tick=5))

    engine.chaos.schedule_event(
        ChaosEvent(tick=2, event_type=ChaosEventType.DB_PRIMARY_FAILURE, duration_ticks=3)
    )
    summary = engine.run(num_ticks=6)

    # JSON export
    raw_json = summary.to_json()
    parsed = json.loads(raw_json)
    assert parsed["total_ticks"] == 6
    assert "availability_pct" in parsed
    assert "p95_latency_ms" in parsed
    assert "incidents" in parsed
    assert "timeline" in parsed

    # Table formatting
    table = summary.format_table()
    assert "CHAOSNET SIMULATION SUMMARY REPORT" in table
    assert "Total Requests Generated:" in table
    assert "Availability (Uptime):" in table
    assert "Mean Detection Time:" in table


def test_simulation_from_scenario_file() -> None:
    """Verify loading from scenario file runs embedded chaos script automatically."""
    engine = SimulationEngine.from_scenario_file(
        AZ_FAILURE_SCENARIO_PATH,
        config=SimulationConfig(requests_per_tick=2),
    )

    # az_failure.json has kill_az at tick 50, recover at tick 120
    assert len(engine.chaos.scheduled_events) == 2

    # Run up to tick 60 (past AZ-a kill at tick 50)
    summary_mid = engine.run(num_ticks=60)
    assert summary_mid.total_ticks == 60
    assert any(entry.event_type == "INJECT_KILL_AZ" for entry in summary_mid.timeline)

    # Run remaining ticks past recovery at tick 120
    summary_end = engine.run(num_ticks=70)
    assert summary_end.total_ticks == 130
    assert any(entry.event_type == "RECOVER_MANUAL_RECOVERY" or "RECOVER" in entry.event_type for entry in summary_end.timeline)
