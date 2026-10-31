"""NetworkX-backed VPC topology graph and export utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import networkx as nx

from chaosnet.core.models import (
    AvailabilityZone,
    DBRole,
    Link,
    LinkStatus,
    Node,
    NodeStatus,
    NodeType,
    Subnet,
    TopologyConfig,
    VPC,
)


class VPCTopology:
    """Manages the VPC topology graph, state lookups, and visual/dict exports."""

    def __init__(self, config: TopologyConfig) -> None:
        """Initialize the VPC topology and construct the underlying NetworkX DiGraph.

        Args:
            config: Validated TopologyConfig containing VPC metadata, nodes, and links.
        """
        self.vpc: VPC = config.vpc
        self.graph: nx.DiGraph = nx.DiGraph(
            vpc_id=config.vpc.id,
            vpc_name=config.vpc.name,
            cidr=config.vpc.cidr,
        )
        self._az_index: dict[str, AvailabilityZone] = {
            az.id: az for az in config.vpc.availability_zones
        }
        self._subnet_index: dict[str, Subnet] = {
            subnet.id: subnet
            for az in config.vpc.availability_zones
            for subnet in az.subnets
        }
        self._build_graph(config.nodes, config.links)

    def _build_graph(self, nodes: list[Node], links: list[Link]) -> None:
        """Populate the NetworkX directed graph with nodes and links."""
        for node in nodes:
            self.add_node(node)

        for link in links:
            self.add_link(link)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VPCTopology:
        """Construct a VPCTopology instance from a raw dictionary."""
        config = TopologyConfig.model_validate(data)
        return cls(config)

    @classmethod
    def from_json_file(cls, file_path: str | Path) -> VPCTopology:
        """Load and validate a VPCTopology from a JSON scenario file.

        Args:
            file_path: Path to the JSON scenario file.

        Returns:
            Initialized VPCTopology instance.
        """
        path = Path(file_path)
        raw_data = json.loads(path.read_text(encoding="utf-8"))
        if "topology" in raw_data:
            raw_data = raw_data["topology"]
        return cls.from_dict(raw_data)

    def add_node(self, node: Node) -> None:
        """Add or update a Node in the topology graph."""
        self.graph.add_node(node.id, data=node.model_copy(deep=True))

    def add_link(self, link: Link) -> None:
        """Add a directed (or bidirectional) Link to the topology graph."""
        forward_link = link.model_copy(deep=True)
        self.graph.add_edge(link.source, link.target, data=forward_link)

        if link.bidirectional:
            reverse_link = link.model_copy(
                update={"source": link.target, "target": link.source},
                deep=True,
            )
            self.graph.add_edge(link.target, link.source, data=reverse_link)

    def get_node(self, node_id: str) -> Node:
        """Return the Node model for the given node_id.

        Raises:
            KeyError: If the node does not exist in the graph.
        """
        if node_id not in self.graph.nodes:
            raise KeyError(f"Node '{node_id}' not found in topology.")
        return self.graph.nodes[node_id]["data"]

    def get_all_nodes(self) -> list[Node]:
        """Return all Node instances in the topology."""
        return [attrs["data"] for _, attrs in self.graph.nodes(data=True)]

    def get_nodes_by_type(
        self,
        node_type: NodeType,
        only_healthy: bool = False,
        az: Optional[str] = None,
    ) -> list[Node]:
        """Filter nodes by NodeType, health status, and optional Availability Zone."""
        results: list[Node] = []
        for node in self.get_all_nodes():
            if node.type != node_type:
                continue
            if only_healthy and node.status == NodeStatus.DOWN:
                continue
            if az is not None and node.az != az:
                continue
            results.append(node)
        return results

    def get_primary_database(self) -> Optional[Node]:
        """Return the current PRIMARY database node, if one exists."""
        for node in self.get_nodes_by_type(NodeType.DATABASE):
            if node.db_role == DBRole.PRIMARY:
                return node
        return None

    def get_link(self, source: str, target: str) -> Link:
        """Return the directed Link between source and target.

        Raises:
            KeyError: If no directed edge exists between source and target.
        """
        if not self.graph.has_edge(source, target):
            raise KeyError(f"Link '{source} -> {target}' not found in topology.")
        return self.graph.edges[source, target]["data"]

    def get_all_links(self, deduplicate_bidirectional: bool = True) -> list[Link]:
        """Return all Link instances in the graph.

        Args:
            deduplicate_bidirectional: If True, collapse bidirectional edge pairs
                into a single Link entry for clean serialization.
        """
        seen_pairs: set[tuple[str, str]] = set()
        links: list[Link] = []

        for u, v, attrs in self.graph.edges(data=True):
            link: Link = attrs["data"]
            if deduplicate_bidirectional and link.bidirectional:
                canonical = (min(u, v), max(u, v))
                if canonical in seen_pairs:
                    continue
                seen_pairs.add(canonical)
            links.append(link)
        return links

    def set_node_status(self, node_id: str, status: NodeStatus) -> Node:
        """Update the operational status of a node."""
        node = self.get_node(node_id)
        node.status = status
        return node

    def set_link_status(
        self,
        source: str,
        target: str,
        status: LinkStatus,
        both_directions: bool = True,
    ) -> None:
        """Update the operational status of a link."""
        link = self.get_link(source, target)
        link.status = status
        if both_directions and self.graph.has_edge(target, source):
            self.get_link(target, source).status = status

    def to_dict(self) -> dict[str, Any]:
        """Export the full topology state as a JSON-serializable dictionary."""
        nodes = [node.model_dump(mode="json") for node in self.get_all_nodes()]
        links = [
            link.model_dump(mode="json")
            for link in self.get_all_links(deduplicate_bidirectional=True)
        ]
        return {
            "vpc": self.vpc.model_dump(mode="json"),
            "nodes": nodes,
            "links": links,
            "summary": {
                "total_azs": len(self._az_index),
                "total_subnets": len(self._subnet_index),
                "total_nodes": len(nodes),
                "up_nodes": sum(1 for n in self.get_all_nodes() if n.status == NodeStatus.UP),
                "degraded_nodes": sum(
                    1 for n in self.get_all_nodes() if n.status == NodeStatus.DEGRADED
                ),
                "down_nodes": sum(1 for n in self.get_all_nodes() if n.status == NodeStatus.DOWN),
                "total_links": len(links),
            },
        }

    def to_dot(self) -> str:
        """Export the topology as a Graphviz DOT string with AZ and subnet clusters."""
        status_colors = {
            NodeStatus.UP: "#d4edda",
            NodeStatus.DEGRADED: "#fff3cd",
            NodeStatus.DOWN: "#f8d7da",
        }
        node_shapes = {
            NodeType.INTERNET_GATEWAY: "octagon",
            NodeType.LOAD_BALANCER: "diamond",
            NodeType.ROUTER: "box3d",
            NodeType.NAT_GATEWAY: "trapezium",
            NodeType.APP_INSTANCE: "box",
            NodeType.DATABASE: "cylinder",
        }

        lines: list[str] = [
            f'digraph "{self.vpc.id}" {{',
            "  rankdir=TB;",
            '  fontname="Helvetica";',
            f'  label="VPC: {self.vpc.name} ({self.vpc.cidr})";',
            "  labelloc=t;",
            '  node [style="filled", fontname="Helvetica", fontsize=10];',
            '  edge [fontname="Helvetica", fontsize=9];',
            "",
        ]

        def _format_node_line(node: Node, indent: str = "  ") -> str:
            color = status_colors[node.status]
            shape = node_shapes[node.type]
            role_suffix = f" ({node.db_role.value})" if node.db_role else ""
            label = (
                f"{node.id}\\n[{node.type.value}{role_suffix}]\\n"
                f"status={node.status.value} | {node.latency_ms}ms"
            )
            return f'{indent}"{node.id}" [label="{label}", shape={shape}, fillcolor="{color}"];'

        for node in self.get_all_nodes():
            if node.az is None:
                lines.append(_format_node_line(node, indent="  "))

        lines.append("")

        for az in self.vpc.availability_zones:
            az_cluster_id = az.id.replace("-", "_")
            lines.append(f"  subgraph cluster_{az_cluster_id} {{")
            lines.append(f'    label="AZ: {az.name} ({az.id})";')
            lines.append('    style="rounded,dashed";')
            lines.append('    color="#6c757d";')

            for subnet in az.subnets:
                sub_cluster_id = subnet.id.replace("-", "_")
                lines.append(f"    subgraph cluster_{sub_cluster_id} {{")
                lines.append(
                    f'      label="{subnet.type.value} Subnet: {subnet.id} ({subnet.cidr})";'
                )
                lines.append('      style="rounded,filled";')
                bg = "#eef6ff" if subnet.type.value == "PUBLIC" else "#f8f9fa"
                lines.append(f'      fillcolor="{bg}";')

                for node in self.get_all_nodes():
                    if node.az == az.id and node.subnet == subnet.id:
                        lines.append(_format_node_line(node, indent="      "))

                lines.append("    }")
            lines.append("  }")
            lines.append("")

        for link in self.get_all_links(deduplicate_bidirectional=True):
            edge_color = {
                LinkStatus.UP: "#28a745",
                LinkStatus.DEGRADED: "#fd7e14",
                LinkStatus.DOWN: "#dc3545",
            }[link.status]
            edge_style = "dashed" if link.status == LinkStatus.DOWN else "solid"
            dir_attr = 'dir="both"' if link.bidirectional else 'dir="forward"'
            label = f"{link.latency}ms | {link.bandwidth}Mbps"
            lines.append(
                f'  "{link.source}" -> "{link.target}" '
                f'[label="{label}", color="{edge_color}", style="{edge_style}", {dir_attr}];'
            )

        lines.append("}")
        return "\n".join(lines)

    def format_summary(self) -> str:
        """Return a human-readable ASCII summary of the VPC topology."""
        lines: list[str] = [
            f"=== VPC: {self.vpc.name} ({self.vpc.id}) | CIDR: {self.vpc.cidr} ===",
        ]
        global_nodes = [n for n in self.get_all_nodes() if n.az is None]
        if global_nodes:
            lines.append("Global Resources:")
            for n in global_nodes:
                lines.append(
                    f"  * [{n.type.value}] {n.id} (status={n.status.value}, "
                    f"latency={n.latency_ms}ms, cap={n.capacity})"
                )

        for az in self.vpc.availability_zones:
            lines.append(f"\nAvailability Zone: {az.name} ({az.id})")
            for subnet in az.subnets:
                lines.append(f"  Subnet: {subnet.id} [{subnet.type.value}] ({subnet.cidr})")
                subnet_nodes = [
                    n for n in self.get_all_nodes() if n.az == az.id and n.subnet == subnet.id
                ]
                for n in subnet_nodes:
                    role = f" role={n.db_role.value}" if n.db_role else ""
                    lines.append(
                        f"    - {n.id:<14} | {n.type.value:<16} | status={n.status.value:<8} "
                        f"| latency={n.latency_ms:>4}ms | cap={n.capacity}{role}"
                    )

        dedup_links = self.get_all_links(deduplicate_bidirectional=True)
        lines.append(f"\nLinks ({len(dedup_links)} total):")
        for link in dedup_links:
            arrow = "<->" if link.bidirectional else "-->"
            lines.append(
                f"  {link.source:<14} {arrow} {link.target:<14} "
                f"| status={link.status.value:<8} | latency={link.latency:>4}ms "
                f"| bw={link.bandwidth}Mbps"
            )
        return "\n".join(lines)
