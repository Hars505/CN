"""Tests for Phase 3: Health checker, consecutive thresholds, and detection lag."""

from pathlib import Path

from chaosnet.core.health import (
    HealthCheckConfig,
    HealthChecker,
    HealthState,
)
from chaosnet.core.models import NodeStatus
from chaosnet.core.topology import VPCTopology
from chaosnet.core.traffic import LoadBalancingStrategy, TrafficRouter


SCENARIO_PATH = Path(__file__).resolve().parent.parent / "scenarios" / "default_vpc.json"


def test_unhealthy_threshold_and_detection_time() -> None:
    """Verify a node is marked UNHEALTHY only after consecutive failed checks and records detection_time."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    config = HealthCheckConfig(
        interval_ticks=2,
        timeout_ms=50.0,
        unhealthy_threshold=3,
        healthy_threshold=2,
    )
    checker = HealthChecker(topo, config=config)

    assert checker.step(tick=0) == []

    topo.set_node_status("app-a1", NodeStatus.DOWN)
    assert checker.step(tick=1) == []
    assert checker.is_perceived_healthy("app-a1") is True
    assert checker.records["app-a1"].failure_started_tick == 1

    assert checker.step(tick=2) == []
    assert checker.records["app-a1"].consecutive_failures == 1
    assert checker.is_perceived_healthy("app-a1") is True

    assert checker.step(tick=3) == []
    assert checker.step(tick=4) == []
    assert checker.records["app-a1"].consecutive_failures == 2
    assert checker.is_perceived_healthy("app-a1") is True

    assert checker.step(tick=5) == []
    events = checker.step(tick=6)
    assert len(events) == 1
    event = events[0]
    assert event.node_id == "app-a1"
    assert event.previous_state == HealthState.HEALTHY
    assert event.new_state == HealthState.UNHEALTHY
    assert event.detection_time_ticks == 5
    assert checker.is_perceived_healthy("app-a1") is False
    assert checker.get_unhealthy_node_ids() == ["app-a1"]
    assert checker.get_average_detection_time() == 5.0


def test_healthy_threshold_recovery() -> None:
    """Verify an UNHEALTHY node requires healthy_threshold consecutive passing checks to recover."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    config = HealthCheckConfig(
        interval_ticks=1,
        timeout_ms=50.0,
        unhealthy_threshold=2,
        healthy_threshold=3,
    )
    checker = HealthChecker(topo, config=config)

    topo.set_node_status("app-b1", NodeStatus.DOWN)
    checker.step(tick=1)
    events_down = checker.step(tick=2)
    assert len(events_down) == 1
    assert checker.is_perceived_healthy("app-b1") is False

    topo.set_node_status("app-b1", NodeStatus.UP)

    assert checker.step(tick=3) == []
    assert checker.is_perceived_healthy("app-b1") is False

    assert checker.step(tick=4) == []
    assert checker.is_perceived_healthy("app-b1") is False

    events_up = checker.step(tick=5)
    assert len(events_up) == 1
    assert events_up[0].node_id == "app-b1"
    assert events_up[0].new_state == HealthState.HEALTHY
    assert checker.is_perceived_healthy("app-b1") is True


def test_latency_timeout_triggers_unhealthy() -> None:
    """Verify a DEGRADED node whose latency exceeds timeout_ms fails health probes."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    config = HealthCheckConfig(
        interval_ticks=2,
        timeout_ms=25.0,
        unhealthy_threshold=2,
        healthy_threshold=2,
    )
    checker = HealthChecker(topo, config=config)

    node = topo.get_node("app-a2")
    node.status = NodeStatus.DEGRADED
    node.latency_ms = 120.0

    checker.step(tick=2)
    events = checker.step(tick=4)

    assert len(events) == 1
    assert events[0].node_id == "app-a2"
    assert "PROBE_TIMEOUT" in events[0].reason
    assert checker.is_perceived_healthy("app-a2") is False


def test_transient_blip_does_not_mark_unhealthy() -> None:
    """Verify a node that fails 2 checks out of 3 and recovers resets its failure counter."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    config = HealthCheckConfig(
        interval_ticks=1,
        timeout_ms=50.0,
        unhealthy_threshold=3,
        healthy_threshold=2,
    )
    checker = HealthChecker(topo, config=config)

    topo.set_node_status("app-a1", NodeStatus.DOWN)
    checker.step(tick=1)
    checker.step(tick=2)
    assert checker.records["app-a1"].consecutive_failures == 2

    topo.set_node_status("app-a1", NodeStatus.UP)
    events = checker.step(tick=3)
    assert events == []
    assert checker.records["app-a1"].consecutive_failures == 0
    assert checker.records["app-a1"].failure_started_tick is None
    assert checker.is_perceived_healthy("app-a1") is True


def test_detection_lag_causes_dropped_requests_until_deregistered() -> None:
    """Demonstrate requests failing during detection lag until health check triggers deregistration."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    router = TrafficRouter(topo, strategy=LoadBalancingStrategy.ROUND_ROBIN)
    checker = HealthChecker(
        topo,
        config=HealthCheckConfig(interval_ticks=1, unhealthy_threshold=2, healthy_threshold=1),
    )

    topo.set_node_status("app-a1", NodeStatus.DOWN)

    checker.step(tick=1)
    batch_tick_1 = router.simulate_batch(4, tick=1, ignore_undetected_down=True)
    failed_t1 = [r for r in batch_tick_1 if not r.success]
    assert len(failed_t1) == 1
    assert failed_t1[0].selected_app == "app-a1"
    assert failed_t1[0].failure_reason == "NODE_DOWN:app-a1"

    events = checker.step(tick=2)
    for ev in events:
        if ev.new_state == HealthState.UNHEALTHY:
            router.deregister_node(ev.node_id)

    batch_tick_2 = router.simulate_batch(4, tick=2, ignore_undetected_down=True)
    assert all(r.success for r in batch_tick_2)
    assert {r.selected_app for r in batch_tick_2} == {"app-a2", "app-b1", "app-b2"}
