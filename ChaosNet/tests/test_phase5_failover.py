"""Tests for Phase 5: Auto-failover engine, DB promotion, AZ failover, and auto-scaling."""

from pathlib import Path

from chaosnet.core.failover import (
    AutoScalingConfig,
    FailoverEngine,
    FailoverEventType,
)
from chaosnet.core.health import HealthCheckConfig, HealthChecker, HealthState
from chaosnet.core.models import DBRole, NodeStatus, NodeType
from chaosnet.core.topology import VPCTopology
from chaosnet.core.traffic import LoadBalancingStrategy, TrafficRouter


SCENARIO_PATH = Path(__file__).resolve().parent.parent / "scenarios" / "default_vpc.json"


def test_deregister_unhealthy_app_and_recovery() -> None:
    """Verify an unhealthy node is evicted from LB pool and re-added after healthy_threshold passes."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    router = TrafficRouter(topo, strategy=LoadBalancingStrategy.ROUND_ROBIN)
    checker = HealthChecker(
        topo,
        config=HealthCheckConfig(interval_ticks=1, unhealthy_threshold=2, healthy_threshold=2),
    )
    engine = FailoverEngine(topo, router, checker)

    # Tick 1: Take down app-a1
    topo.set_node_status("app-a1", NodeStatus.DOWN)
    h_events_1 = checker.step(tick=1)
    f_events_1 = engine.step(tick=1, health_events=h_events_1)
    assert f_events_1 == []
    assert "app-a1" not in router.deregistered_nodes

    # Tick 2: 2nd failed check marks app-a1 UNHEALTHY -> FailoverEngine evicts it
    h_events_2 = checker.step(tick=2)
    assert len(h_events_2) == 1
    f_events_2 = engine.step(tick=2, health_events=h_events_2)
    assert len(f_events_2) == 1
    assert f_events_2[0].event_type == FailoverEventType.DEREGISTER_NODE
    assert f_events_2[0].target == "app-a1"
    assert "app-a1" in router.deregistered_nodes

    # Traffic should route only across the remaining 3 healthy instances
    batch = router.simulate_batch(6, tick=2)
    assert all(r.success for r in batch)
    assert "app-a1" not in {r.selected_app for r in batch}

    # Tick 3: app-a1 recovers to UP
    topo.set_node_status("app-a1", NodeStatus.UP)
    h_events_3 = checker.step(tick=3)  # Pass 1/2 -> still UNHEALTHY
    f_events_3 = engine.step(tick=3, health_events=h_events_3)
    assert f_events_3 == []
    assert "app-a1" in router.deregistered_nodes

    # Tick 4: Pass 2/2 -> transitions to HEALTHY -> FailoverEngine re-registers it
    h_events_4 = checker.step(tick=4)
    assert len(h_events_4) == 1
    f_events_4 = engine.step(tick=4, health_events=h_events_4)
    assert len(f_events_4) == 1
    assert f_events_4[0].event_type == FailoverEventType.REGISTER_NODE
    assert f_events_4[0].target == "app-a1"
    assert "app-a1" not in router.deregistered_nodes

    # Traffic now includes app-a1 again
    recovered_batch = router.simulate_batch(8, tick=4)
    assert "app-a1" in {r.selected_app for r in recovered_batch}


def test_database_primary_failure_and_replica_promotion() -> None:
    """Verify when the primary database fails, the replica is promoted and routes traffic."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    router = TrafficRouter(topo, strategy=LoadBalancingStrategy.ROUND_ROBIN)
    checker = HealthChecker(
        topo,
        config=HealthCheckConfig(interval_ticks=1, unhealthy_threshold=2, healthy_threshold=2),
    )
    engine = FailoverEngine(topo, router, checker)

    # Initial state: db-primary-a is PRIMARY, db-replica-b is REPLICA
    assert topo.get_primary_database().id == "db-primary-a"
    assert topo.get_node("db-replica-b").db_role == DBRole.REPLICA

    # Tick 1: db-primary-a fails
    topo.set_node_status("db-primary-a", NodeStatus.DOWN)
    checker.step(tick=1)
    engine.step(tick=1)

    # Tick 2: db-primary-a detected UNHEALTHY -> triggers DB_PROMOTION
    h_events = checker.step(tick=2)
    f_events = engine.step(tick=2, health_events=h_events)

    promotion_events = [e for e in f_events if e.event_type == FailoverEventType.DB_PROMOTION]
    assert len(promotion_events) == 1
    promo_event = promotion_events[0]
    assert promo_event.target == "db-replica-b"
    assert promo_event.details["demoted_primary"] == "db-primary-a"
    assert promo_event.details["promoted_primary"] == "db-replica-b"

    # New primary in topology is now db-replica-b
    new_primary = topo.get_primary_database()
    assert new_primary is not None
    assert new_primary.id == "db-replica-b"
    assert topo.get_node("db-primary-a").db_role == DBRole.REPLICA

    # Traffic seamlessly routes to the newly promoted primary database
    result = router.route_request(tick=3)
    assert result.success is True
    assert result.selected_db == "db-replica-b"
    assert "db-replica-b" in result.path

    # Old primary comes back UP: remains REPLICA
    topo.set_node_status("db-primary-a", NodeStatus.UP)
    checker.step(tick=4)
    checker.step(tick=5)
    engine.step(tick=5)
    assert topo.get_primary_database().id == "db-replica-b"
    assert topo.get_node("db-primary-a").db_role == DBRole.REPLICA


def test_az_failover_and_recovery() -> None:
    """Verify traffic fails over 100% to az-b when az-a is down, and recovers when restored."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    router = TrafficRouter(topo, strategy=LoadBalancingStrategy.ROUND_ROBIN)
    checker = HealthChecker(
        topo,
        config=HealthCheckConfig(interval_ticks=1, unhealthy_threshold=1, healthy_threshold=1),
    )
    engine = FailoverEngine(topo, router, checker)

    # Fail all apps in az-a
    topo.set_node_status("app-a1", NodeStatus.DOWN)
    topo.set_node_status("app-a2", NodeStatus.DOWN)

    h_events = checker.step(tick=1)
    f_events = engine.step(tick=1, health_events=h_events)

    az_failover_events = [e for e in f_events if e.event_type == FailoverEventType.AZ_FAILOVER]
    assert len(az_failover_events) == 1
    assert az_failover_events[0].target == "az-a"
    assert "az-a" in engine.disabled_azs
    assert "az-a" in router.disabled_azs

    # All traffic routes exclusively to az-b instances
    batch = router.simulate_batch(6, tick=2)
    assert all(r.success for r in batch)
    assert {r.selected_app for r in batch} == {"app-b1", "app-b2"}

    # Recover az-a apps
    topo.set_node_status("app-a1", NodeStatus.UP)
    topo.set_node_status("app-a2", NodeStatus.UP)

    h_rec = checker.step(tick=3)
    f_rec = engine.step(tick=3, health_events=h_rec)

    az_rec_events = [e for e in f_rec if e.event_type == FailoverEventType.AZ_RECOVERY]
    assert len(az_rec_events) == 1
    assert az_rec_events[0].target == "az-a"
    assert "az-a" not in engine.disabled_azs
    assert "az-a" not in router.disabled_azs


def test_auto_scaling_instance_replacement() -> None:
    """Verify auto-scaling spawns a replacement instance after startup delay when capacity drops."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    router = TrafficRouter(topo, strategy=LoadBalancingStrategy.ROUND_ROBIN)
    checker = HealthChecker(
        topo,
        config=HealthCheckConfig(interval_ticks=1, unhealthy_threshold=1, healthy_threshold=1),
    )
    autoscale_cfg = AutoScalingConfig(
        enabled=True,
        min_healthy_capacity=600,
        startup_delay_ticks=3,
        cooldown_ticks=5,
    )
    engine = FailoverEngine(topo, router, checker, autoscale_config=autoscale_cfg)

    # Initial capacity: 4 * 250 = 1000
    assert engine.get_healthy_app_capacity() == 1000

    # Kill app-a1 and app-a2 -> capacity drops to 500 (below 600 threshold)
    topo.set_node_status("app-a1", NodeStatus.DOWN)
    topo.set_node_status("app-a2", NodeStatus.DOWN)

    h_ev_1 = checker.step(tick=1)
    f_ev_1 = engine.step(tick=1, health_events=h_ev_1)

    spawn_events = [e for e in f_ev_1 if e.event_type == FailoverEventType.AUTOSCALE_SPAWN]
    assert len(spawn_events) == 1
    spawn_ev = spawn_events[0]
    assert "asg-1" in spawn_ev.target
    assert len(engine.pending_instances) == 1
    assert engine.pending_instances[0].ready_tick == 4  # 1 + 3

    # Ticks 2 and 3: Instance still booting
    for t in (2, 3):
        h_ev = checker.step(tick=t)
        f_ev = engine.step(tick=t, health_events=h_ev)
        assert not any(e.event_type == FailoverEventType.AUTOSCALE_READY for e in f_ev)

    # Tick 4: Instance completes startup delay -> AUTOSCALE_READY
    h_ev_4 = checker.step(tick=4)
    f_ev_4 = engine.step(tick=4, health_events=h_ev_4)

    ready_events = [e for e in f_ev_4 if e.event_type == FailoverEventType.AUTOSCALE_READY]
    assert len(ready_events) == 1
    ready_id = ready_events[0].target
    assert ready_id in topo.graph.nodes
    assert topo.get_node(ready_id).status == NodeStatus.UP
    assert ready_id not in router.deregistered_nodes

    # Capacity is restored: 500 + 250 = 750 (>= 600)
    assert engine.get_healthy_app_capacity() == 750

    # The new auto-scaled instance successfully receives routed traffic
    batch = router.simulate_batch(6, tick=4)
    assert ready_id in {r.selected_app for r in batch}
    assert all(r.success for r in batch)


def test_structured_event_history() -> None:
    """Verify all failover decisions log complete structured metadata."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    router = TrafficRouter(topo)
    checker = HealthChecker(topo, config=HealthCheckConfig(interval_ticks=1, unhealthy_threshold=1))
    engine = FailoverEngine(topo, router, checker)

    topo.set_node_status("app-a1", NodeStatus.DOWN)
    h_ev = checker.step(tick=10)
    engine.step(tick=10, health_events=h_ev)

    assert len(engine.event_history) >= 1
    entry = engine.event_history[0]
    assert entry.tick == 10
    assert entry.event_type == FailoverEventType.DEREGISTER_NODE
    assert entry.target == "app-a1"
    assert "Evicted from LB target pool" in entry.reason
    assert "az" in entry.details


def test_full_az_outage_with_db_and_app_failover() -> None:
    """Verify simultaneous AZ outage triggers both AZ failover and DB replica promotion."""
    from chaosnet.core.chaos import ChaosEngine, ChaosEvent, ChaosEventType

    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    router = TrafficRouter(topo, strategy=LoadBalancingStrategy.ROUND_ROBIN)
    checker = HealthChecker(
        topo,
        config=HealthCheckConfig(interval_ticks=1, unhealthy_threshold=1, healthy_threshold=1),
    )
    engine = FailoverEngine(topo, router, checker)
    chaos = ChaosEngine(topo)

    # Kill entire AZ az-a at tick 1 (takes down lb-a, nat-a, router-a, app-a1, app-a2, db-primary-a)
    chaos.schedule_event(
        ChaosEvent(tick=1, event_type=ChaosEventType.KILL_AZ, target="az-a", duration_ticks=5)
    )

    chaos.step(1)
    h_ev_1 = checker.step(1)
    f_ev_1 = engine.step(1, health_events=h_ev_1)

    event_types = {e.event_type for e in f_ev_1}
    assert FailoverEventType.AZ_FAILOVER in event_types
    assert FailoverEventType.DB_PROMOTION in event_types
    assert topo.get_primary_database().id == "db-replica-b"

    # All traffic routes through az-b to the newly promoted db-replica-b
    batch = router.simulate_batch(4, tick=2)
    assert all(r.success for r in batch)
    for r in batch:
        assert r.selected_db == "db-replica-b"
        assert r.selected_app in {"app-b1", "app-b2"}
        assert r.selected_lb == "lb-b"

