"""End-to-end integration tests for Phase 8: Multi-failure routing, hysteresis, DB promotion, and seed reproducibility."""

from pathlib import Path

from chaosnet.core.chaos import ChaosEvent, ChaosEventType
from chaosnet.core.engine import SimulationConfig, SimulationEngine
from chaosnet.core.failover import AutoScalingConfig, FailoverEngine, FailoverEventType
from chaosnet.core.health import HealthCheckConfig, HealthChecker, HealthState
from chaosnet.core.models import DBRole, LinkStatus, NodeStatus, NodeType
from chaosnet.core.topology import VPCTopology
from chaosnet.core.traffic import LoadBalancingStrategy, TrafficRouter


SCENARIO_PATH = Path(__file__).resolve().parent.parent / "scenarios" / "default_vpc.json"


def test_reproducibility_with_same_seed_and_random_chaos() -> None:
    """Verify two complete simulation runs with identical seeds produce 100% identical results."""
    config1 = SimulationConfig(
        requests_per_tick=5,
        seed=1337,
        health_config=HealthCheckConfig(interval_ticks=1, unhealthy_threshold=2, healthy_threshold=2),
    )
    engine1 = SimulationEngine.from_scenario_file(SCENARIO_PATH, config=config1)
    engine1.chaos.configure_random_chaos(enabled=True, probability=0.3, min_duration=3, max_duration=7)

    config2 = SimulationConfig(
        requests_per_tick=5,
        seed=1337,
        health_config=HealthCheckConfig(interval_ticks=1, unhealthy_threshold=2, healthy_threshold=2),
    )
    engine2 = SimulationEngine.from_scenario_file(SCENARIO_PATH, config=config2)
    engine2.chaos.configure_random_chaos(enabled=True, probability=0.3, min_duration=3, max_duration=7)

    summary1 = engine1.run(num_ticks=50)
    summary2 = engine2.run(num_ticks=50)

    assert summary1.total_ticks == summary2.total_ticks == 50
    assert summary1.total_requests == summary2.total_requests == 250
    assert summary1.successful_requests == summary2.successful_requests
    assert summary1.failed_requests == summary2.failed_requests
    assert summary1.availability_pct == summary2.availability_pct
    assert summary1.avg_latency_ms == summary2.avg_latency_ms
    assert summary1.p95_latency_ms == summary2.p95_latency_ms
    assert len(summary1.incidents) == len(summary2.incidents)
    assert len(summary1.timeline) == len(summary2.timeline)

    # Every tick metric in the series must match identically
    for m1, m2 in zip(summary1.series, summary2.series, strict=True):
        assert m1.tick == m2.tick
        assert m1.requests_succeeded == m2.requests_succeeded
        assert m1.requests_failed == m2.requests_failed
        assert m1.avg_latency_ms == m2.avg_latency_ms


def test_routing_around_complex_cascading_failures() -> None:
    """Verify Dijkstra routing navigates around broken cross-links and dead routers."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    router = TrafficRouter(topo, strategy=LoadBalancingStrategy.ROUND_ROBIN)

    # 1. Break direct link from igw-main to lb-a
    topo.set_link_status("igw-main", "lb-a", LinkStatus.DOWN)

    # 2. Kill router-b in az-b
    topo.set_node_status("router-b", NodeStatus.DOWN)

    # Any request to app-a1 must now go: igw-main -> lb-b -> router-a -> app-a1 -> db-primary-a
    res = router.route_request(tick=1)
    assert res.success is True
    assert res.path == ["igw-main", "lb-b", "router-a", "app-a1", "db-primary-a"]
    assert res.selected_lb == "lb-b"
    assert res.selected_app == "app-a1"

    # Latency:
    # Nodes: 1.0(igw) + 1.5(lb-b) + 0.5(router-a) + 4.0(app-a1) + 3.0(db) = 10.0ms
    # Links: 1.2(igw->lb-b) + 2.5(lb-b->router-a) + 0.6(router-a->app-a1) + 1.0(app-a1->db) = 5.3ms
    # Total: 15.3ms
    assert res.total_latency_ms == 15.3


def test_health_check_hysteresis_against_flapping_node() -> None:
    """Verify a flapping node that intermittently fails single probes never gets marked UNHEALTHY."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    checker = HealthChecker(
        topo,
        config=HealthCheckConfig(interval_ticks=1, unhealthy_threshold=3, healthy_threshold=2),
    )

    # Flapping sequence: DOWN -> UP -> DOWN -> UP
    # Tick 1: DOWN (failures=1/3) -> HEALTHY
    topo.set_node_status("app-a1", NodeStatus.DOWN)
    events = checker.step(tick=1)
    assert events == []
    assert checker.is_perceived_healthy("app-a1") is True

    # Tick 2: UP -> recovers counter
    topo.set_node_status("app-a1", NodeStatus.UP)
    events = checker.step(tick=2)
    assert events == []
    assert checker.records["app-a1"].consecutive_failures == 0
    assert checker.is_perceived_healthy("app-a1") is True

    # Tick 3: DOWN again (failures=1/3)
    topo.set_node_status("app-a1", NodeStatus.DOWN)
    checker.step(tick=3)
    assert checker.is_perceived_healthy("app-a1") is True

    # Tick 4: DOWN (failures=2/3)
    checker.step(tick=4)
    assert checker.is_perceived_healthy("app-a1") is True

    # Tick 5: DOWN (failures=3/3) -> Now transitions to UNHEALTHY!
    events_5 = checker.step(tick=5)
    assert len(events_5) == 1
    assert events_5[0].node_id == "app-a1"
    assert events_5[0].new_state == HealthState.UNHEALTHY
    assert checker.is_perceived_healthy("app-a1") is False


def test_complete_az_failure_db_promotion_and_auto_scaling() -> None:
    """Verify end-to-end multi-tier recovery: AZ failure, DB promotion, and auto-scaling replacement."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    config = SimulationConfig(
        requests_per_tick=4,
        health_config=HealthCheckConfig(interval_ticks=1, unhealthy_threshold=2, healthy_threshold=2),
        autoscale_config=AutoScalingConfig(
            enabled=True,
            min_healthy_capacity=600,
            startup_delay_ticks=2,
            cooldown_ticks=5,
        ),
        seed=42,
    )
    engine = SimulationEngine(topology=topo, config=config)

    # Initial state
    assert engine.failover.get_healthy_app_capacity() == 1000
    assert topo.get_primary_database().id == "db-primary-a"

    # Inject complete AZ outage on az-a at tick 5 (duration 10 ticks, recovers at tick 15)
    engine.chaos.schedule_event(
        ChaosEvent(tick=5, event_type=ChaosEventType.KILL_AZ, target="az-a", duration_ticks=10)
    )

    # Run through the failure lifecycle
    summary = engine.run(num_ticks=20)

    # 1. DB Replica in az-b was promoted to PRIMARY
    timeline_promotions = [e for e in summary.timeline if e.event_type == "DB_PROMOTION"]
    assert len(timeline_promotions) >= 1
    assert timeline_promotions[0].target == "db-replica-b"
    assert topo.get_primary_database().id == "db-replica-b"

    # 2. Auto-scaling spawned replacement instance in az-b
    timeline_spawns = [e for e in summary.timeline if e.event_type == "AUTOSCALE_SPAWN"]
    assert len(timeline_spawns) >= 1
    timeline_ready = [e for e in summary.timeline if e.event_type == "AUTOSCALE_READY"]
    assert len(timeline_ready) >= 1

    # 3. Post-failover requests succeeded
    post_failover_ticks = [m for m in summary.series if m.tick in range(8, 15)]
    assert all(m.success_rate_pct == 100.0 for m in post_failover_ticks)


def test_least_connections_strategy_load_distribution() -> None:
    """Verify LEAST_CONNECTIONS dynamically balances traffic when instances have uneven load."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    router = TrafficRouter(topo, strategy=LoadBalancingStrategy.LEAST_CONNECTIONS)

    # Artificially load app-a1 and app-b1 with connections
    topo.get_node("app-a1").active_connections = 10
    topo.get_node("app-b1").active_connections = 10

    # 2 requests should go to the lowest connection instances: app-a2 and app-b2
    r1 = router.route_request(tick=1, hold_connection=True)
    r2 = router.route_request(tick=1, hold_connection=True)

    assert {r1.selected_app, r2.selected_app} == {"app-a2", "app-b2"}
    router.release_path_connections(r1.path)
    router.release_path_connections(r2.path)
