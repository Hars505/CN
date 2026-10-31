"""Tests for Phase 4: Chaos injection engine, network partition, and seeded random chaos."""

from pathlib import Path

from chaosnet.core.chaos import ChaosEngine, ChaosEvent, ChaosEventType
from chaosnet.core.models import LinkStatus, NodeStatus
from chaosnet.core.topology import VPCTopology


SCENARIO_PATH = Path(__file__).resolve().parent.parent / "scenarios" / "default_vpc.json"


def test_kill_node_and_auto_recovery() -> None:
    """Verify killing a node sets it to DOWN and duration-based recovery restores it."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    engine = ChaosEngine(topo)

    event = ChaosEvent(
        tick=5,
        event_type=ChaosEventType.KILL_NODE,
        target="app-a1",
        duration_ticks=10,
    )
    engine.schedule_event(event)

    for t in range(1, 5):
        engine.step(t)
    assert topo.get_node("app-a1").status == NodeStatus.UP

    engine.step(5)
    assert topo.get_node("app-a1").status == NodeStatus.DOWN

    for t in range(6, 15):
        engine.step(t)
    assert topo.get_node("app-a1").status == NodeStatus.DOWN

    engine.step(15)
    assert topo.get_node("app-a1").status == NodeStatus.UP


def test_kill_az() -> None:
    """Verify killing an entire AZ takes down all nodes residing within it."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    engine = ChaosEngine(topo)

    event = ChaosEvent(
        tick=2,
        event_type=ChaosEventType.KILL_AZ,
        target="az-a",
        duration_ticks=5,
    )
    engine.schedule_event(event)

    engine.step(2)

    for node in topo.get_all_nodes():
        if node.az == "az-a":
            assert node.status == NodeStatus.DOWN

    for node in topo.get_all_nodes():
        if node.az == "az-b":
            assert node.status == NodeStatus.UP

    engine.step(7)
    for node in topo.get_all_nodes():
        if node.az == "az-a":
            assert node.status == NodeStatus.UP


def test_latency_spike_and_packet_loss() -> None:
    """Verify latency spikes and packet loss configurations apply correctly to links/nodes."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    engine = ChaosEngine(topo)

    engine.schedule_event(
        ChaosEvent(
            tick=1,
            event_type=ChaosEventType.LATENCY_SPIKE,
            target="app-a1",
            magnitude=50.0,
            duration_ticks=3,
        )
    )
    engine.schedule_event(
        ChaosEvent(
            tick=1,
            event_type=ChaosEventType.PACKET_LOSS,
            target="router-a->app-a1",
            magnitude=0.25,
            duration_ticks=3,
        )
    )

    engine.step(1)
    assert topo.get_node("app-a1").latency_ms == 54.0
    assert topo.get_link("router-a", "app-a1").packet_loss == 0.25

    engine.step(4)
    assert topo.get_node("app-a1").latency_ms == 4.0
    assert topo.get_link("router-a", "app-a1").packet_loss == 0.0


def test_network_partition_and_recovery() -> None:
    """Verify network partition severs all cross-AZ links and recovers cleanly."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    engine = ChaosEngine(topo)

    event = ChaosEvent(
        tick=3,
        event_type=ChaosEventType.NETWORK_PARTITION,
        target="az-a<->az-b",
        duration_ticks=4,
    )
    engine.schedule_event(event)

    engine.step(3)

    # Cross-AZ links should now be DOWN
    assert topo.get_link("router-a", "router-b").status == LinkStatus.DOWN
    assert topo.get_link("lb-a", "router-b").status == LinkStatus.DOWN
    assert topo.get_link("lb-b", "router-a").status == LinkStatus.DOWN
    assert topo.get_link("app-b1", "db-primary-a").status == LinkStatus.DOWN

    # Intra-AZ links remain UP
    assert topo.get_link("router-a", "app-a1").status == LinkStatus.UP
    assert topo.get_link("router-b", "app-b1").status == LinkStatus.UP

    # Recover at tick 7
    engine.step(7)
    assert topo.get_link("router-a", "router-b").status == LinkStatus.UP
    assert topo.get_link("lb-a", "router-b").status == LinkStatus.UP
    assert topo.get_link("app-b1", "db-primary-a").status == LinkStatus.UP


def test_db_primary_failure() -> None:
    """Verify db_primary_failure targets the active primary database."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    engine = ChaosEngine(topo)

    event = ChaosEvent(
        tick=1,
        event_type=ChaosEventType.DB_PRIMARY_FAILURE,
        duration_ticks=5,
    )
    engine.schedule_event(event)

    engine.step(1)
    primary = topo.get_primary_database()
    assert primary is not None
    assert primary.id == "db-primary-a"
    assert primary.status == NodeStatus.DOWN

    engine.step(6)
    assert topo.get_node("db-primary-a").status == NodeStatus.UP


def test_manual_recovery_and_script_schedule() -> None:
    """Verify manual recovery via script action at a future tick."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    engine = ChaosEngine(topo)

    script = [
        {"tick": 50, "event_type": "kill_az", "target": "az-a"},
        {"tick": 120, "event_type": "recover", "target": "az-a"},
    ]
    engine.load_script(script)

    engine.step(50)
    assert topo.get_node("app-a1").status == NodeStatus.DOWN
    assert topo.get_node("router-a").status == NodeStatus.DOWN

    # Still DOWN at tick 119
    engine.step(119)
    assert topo.get_node("app-a1").status == NodeStatus.DOWN

    # Recovered at tick 120 by script event
    engine.step(120)
    assert topo.get_node("app-a1").status == NodeStatus.UP
    assert topo.get_node("router-a").status == NodeStatus.UP


def test_reproducible_random_chaos_with_seed() -> None:
    """Verify random chaos mode is 100% reproducible given the same RNG seed."""
    topo1 = VPCTopology.from_json_file(SCENARIO_PATH)
    engine1 = ChaosEngine(topo1, seed=999)
    engine1.configure_random_chaos(enabled=True, probability=1.0)

    topo2 = VPCTopology.from_json_file(SCENARIO_PATH)
    engine2 = ChaosEngine(topo2, seed=999)
    engine2.configure_random_chaos(enabled=True, probability=1.0)

    logs1 = [engine1.step(t) for t in range(1, 10)]
    logs2 = [engine2.step(t) for t in range(1, 10)]

    # The exact same sequence of events, targets, and tick actions must occur
    assert logs1 == logs2
