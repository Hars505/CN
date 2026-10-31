"""Tests for Phase 1: VPC Topology model, validation, and exports."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from chaosnet.core.models import (
    DBRole,
    LinkStatus,
    Node,
    NodeStatus,
    NodeType,
    TopologyConfig,
)
from chaosnet.core.topology import VPCTopology


SCENARIO_PATH = Path(__file__).resolve().parent.parent / "scenarios" / "default_vpc.json"


def test_load_default_vpc_from_json() -> None:
    """Verify the default scenario loads into NetworkX with expected counts."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)

    assert topo.vpc.id == "vpc-01"
    assert topo.vpc.cidr == "10.0.0.0/16"
    assert len(topo.vpc.availability_zones) == 2
    assert len(topo.get_all_nodes()) == 13
    assert len(topo.get_all_links(deduplicate_bidirectional=True)) == 22

    # Bidirectional links create 2 directed edges in the DiGraph
    assert topo.graph.number_of_edges() == 44


def test_node_queries_and_primary_db() -> None:
    """Verify querying nodes by type, AZ, health status, and primary DB role."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)

    app_nodes = topo.get_nodes_by_type(NodeType.APP_INSTANCE)
    assert len(app_nodes) == 4

    az_a_apps = topo.get_nodes_by_type(NodeType.APP_INSTANCE, az="az-a")
    assert {n.id for n in az_a_apps} == {"app-a1", "app-a2"}

    primary_db = topo.get_primary_database()
    assert primary_db is not None
    assert primary_db.id == "db-primary-a"
    assert primary_db.db_role == DBRole.PRIMARY


def test_status_mutations() -> None:
    """Verify node and link status mutations update graph state accurately."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)

    topo.set_node_status("app-a1", NodeStatus.DOWN)
    assert topo.get_node("app-a1").status == NodeStatus.DOWN

    healthy_apps = topo.get_nodes_by_type(NodeType.APP_INSTANCE, only_healthy=True)
    assert len(healthy_apps) == 3

    topo.set_link_status("igw-main", "lb-a", LinkStatus.DOWN)
    assert topo.get_link("igw-main", "lb-a").status == LinkStatus.DOWN
    assert topo.get_link("lb-a", "igw-main").status == LinkStatus.DOWN


def test_validation_rejects_invalid_db_or_subnet() -> None:
    """Ensure Pydantic validators catch missing db_role or invalid subnet references."""
    with pytest.raises(ValidationError, match="must specify db_role"):
        Node(
            id="db-invalid",
            type=NodeType.DATABASE,
            az="az-a",
            subnet="subnet-priv-a",
        )

    raw = VPCTopology.from_json_file(SCENARIO_PATH).to_dict()
    raw["nodes"][1]["subnet"] = "subnet-nonexistent"
    with pytest.raises(ValidationError, match="does not exist in AZ"):
        TopologyConfig.model_validate(raw)


def test_exports_dict_dot_and_summary() -> None:
    """Verify dictionary, Graphviz DOT, and ASCII summary exports."""
    topo = VPCTopology.from_json_file(SCENARIO_PATH)

    exported = topo.to_dict()
    assert exported["summary"]["total_nodes"] == 13
    assert exported["summary"]["up_nodes"] == 13

    dot_output = topo.to_dot()
    assert 'digraph "vpc-01"' in dot_output
    assert "subgraph cluster_az_a" in dot_output
    assert "subgraph cluster_subnet_priv_a" in dot_output
    assert '"db-primary-a"' in dot_output

    summary = topo.format_summary()
    assert "chaosnet-prod-vpc" in summary
    assert "db-primary-a" in summary