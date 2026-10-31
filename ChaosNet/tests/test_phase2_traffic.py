"""Tests for Phase 2: Traffic generation, load balancing, and shortest-path routing."""

from pathlib import Path

from chaosnet.core.models import LinkStatus, NodeStatus
from chaosnet.core.topology import VPCTopology
from chaosnet.core.traffic import LoadBalancingStrategy, TrafficRouter


SCENARIO_PATH = Path(__file__).resolve().parent.parent / "scenarios" / "default_vpc.json"


def test_single_request_end_to_end_and_exact_latency() -> None:
    """Verify a request routes IGW -> LB -> Router -> App -> Primary DB with exact latency."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    router = TrafficRouter(topo, strategy=LoadBalancingStrategy.ROUND_ROBIN)

    result = router.route_request(tick=1)

    assert result.success is True
    assert result.failure_reason is None
    assert result.path == ["igw-main", "lb-a", "router-a", "app-a1", "db-primary-a"]
    assert result.selected_lb == "lb-a"
    assert result.selected_app == "app-a1"
    assert result.selected_db == "db-primary-a"
    assert result.total_latency_ms == 13.4


def test_round_robin_load_balancing() -> None:
    """Verify ROUND_ROBIN cycles evenly through all healthy app instances."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    router = TrafficRouter(topo, strategy=LoadBalancingStrategy.ROUND_ROBIN)

    results = [router.route_request(tick=1) for _ in range(8)]
    selected_apps = [r.selected_app for r in results]

    assert all(r.success for r in results)
    assert selected_apps == [
        "app-a1",
        "app-a2",
        "app-b1",
        "app-b2",
        "app-a1",
        "app-a2",
        "app-b1",
        "app-b2",
    ]


def test_least_connections_load_balancing() -> None:
    """Verify LEAST_CONNECTIONS picks the instance with the fewest active connections."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    router = TrafficRouter(topo, strategy=LoadBalancingStrategy.LEAST_CONNECTIONS)

    topo.get_node("app-a1").active_connections = 5
    topo.get_node("app-a2").active_connections = 3
    topo.get_node("app-b1").active_connections = 2
    topo.get_node("app-b2").active_connections = 0

    first = router.route_request(tick=1)
    assert first.success is True
    assert first.selected_app == "app-b2"

    for app_id in ("app-a1", "app-a2", "app-b1", "app-b2"):
        topo.get_node(app_id).active_connections = 0

    batch_results = router.simulate_batch(num_requests=4, tick=2)
    batch_apps = [r.selected_app for r in batch_results]
    assert set(batch_apps) == {"app-a1", "app-a2", "app-b1", "app-b2"}
    assert all(
        topo.get_node(app_id).active_connections == 0
        for app_id in ("app-a1", "app-a2", "app-b1", "app-b2")
    )


def test_routing_around_down_nodes_and_links() -> None:
    """Verify shortest-path routing automatically avoids DOWN links and DOWN nodes."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    router = TrafficRouter(topo, strategy=LoadBalancingStrategy.ROUND_ROBIN)

    topo.set_link_status("igw-main", "lb-a", LinkStatus.DOWN)
    res_cross_lb = router.route_request(tick=1)
    assert res_cross_lb.success is True
    assert res_cross_lb.selected_app == "app-a1"
    assert res_cross_lb.selected_lb == "lb-b"
    assert res_cross_lb.path == ["igw-main", "lb-b", "router-a", "app-a1", "db-primary-a"]

    topo.set_node_status("router-a", NodeStatus.DOWN)
    batch = router.simulate_batch(num_requests=4, tick=2)
    assert all(r.success for r in batch)
    assert {r.selected_app for r in batch} == {"app-b1", "app-b2"}


def test_failure_when_primary_db_is_down_or_packet_loss() -> None:
    """Verify requests fail with clear error codes on packet loss or primary DB outage."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)
    router = TrafficRouter(topo, strategy=LoadBalancingStrategy.ROUND_ROBIN, seed=123)

    topo.get_link("app-a1", "db-primary-a").packet_loss = 1.0
    loss_result = router.route_request(tick=1)
    assert loss_result.success is False
    assert loss_result.failure_reason == "PACKET_LOSS:app-a1->db-primary-a"

    topo.get_link("app-a1", "db-primary-a").packet_loss = 0.0
    topo.set_node_status("db-primary-a", NodeStatus.DOWN)
    db_down_result = router.route_request(tick=2)
    assert db_down_result.success is False
    assert db_down_result.failure_reason == "NO_PRIMARY_DB"
