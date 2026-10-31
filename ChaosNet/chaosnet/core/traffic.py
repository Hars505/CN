"""Traffic generation, load balancing, and shortest-path latency routing."""

from __future__ import annotations

import random
import uuid
from enum import StrEnum
from typing import Optional

import networkx as nx
from pydantic import BaseModel, Field

from chaosnet.core.models import Link, LinkStatus, Node, NodeStatus, NodeType
from chaosnet.core.topology import VPCTopology

TRANSIT_NODE_TYPES: frozenset[NodeType] = frozenset(
    {
        NodeType.INTERNET_GATEWAY,
        NodeType.LOAD_BALANCER,
        NodeType.ROUTER,
    }
)


class LoadBalancingStrategy(StrEnum):
    """Supported load balancer target selection algorithms."""

    ROUND_ROBIN = "ROUND_ROBIN"
    LEAST_CONNECTIONS = "LEAST_CONNECTIONS"


class RequestResult(BaseModel):
    """Outcome of a single simulated request through the VPC."""

    request_id: str = Field(..., description="Unique identifier for the request")
    tick: int = Field(default=0, description="Simulation tick when the request occurred")
    success: bool = Field(..., description="True if the request reached the primary DB")
    path: list[str] = Field(
        default_factory=list,
        description="Ordered list of node IDs traversed by the request",
    )
    total_latency_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Sum of node processing and link propagation latencies along the path",
    )
    selected_lb: Optional[str] = Field(default=None, description="Chosen LOAD_BALANCER ID")
    selected_app: Optional[str] = Field(default=None, description="Chosen APP_INSTANCE ID")
    selected_db: Optional[str] = Field(default=None, description="Chosen DATABASE ID")
    failure_reason: Optional[str] = Field(
        default=None,
        description="Machine-readable error code if success is False",
    )


class TrafficRouter:
    """Routes simulated requests across the VPC topology using shortest-path latency."""

    def __init__(
        self,
        topology: VPCTopology,
        strategy: LoadBalancingStrategy = LoadBalancingStrategy.ROUND_ROBIN,
        seed: Optional[int] = 42,
    ) -> None:
        """Initialize the traffic router.

        Args:
            topology: The underlying VPCTopology instance.
            strategy: Load balancing algorithm (ROUND_ROBIN or LEAST_CONNECTIONS).
            seed: Seed for deterministic packet-loss evaluation.
        """
        self.topology = topology
        self.strategy = strategy
        self.rng = random.Random(seed)
        self._rr_cursor: int = 0
        self._request_counter: int = 0
        self.deregistered_nodes: set[str] = set()
        self.disabled_azs: set[str] = set()

    def register_node(self, node_id: str) -> None:
        """Ensure a node is eligible in the load balancer target pool."""
        self.deregistered_nodes.discard(node_id)

    def deregister_node(self, node_id: str) -> None:
        """Remove a node from the load balancer target pool."""
        self.deregistered_nodes.add(node_id)

    def disable_az(self, az_id: str) -> None:
        """Exclude an entire Availability Zone from load balancer routing."""
        self.disabled_azs.add(az_id)

    def enable_az(self, az_id: str) -> None:
        """Re-enable an Availability Zone for load balancer routing."""
        self.disabled_azs.discard(az_id)

    def _is_node_usable(
        self,
        node: Node,
        ignore_actual_down: bool = False,
        check_capacity: bool = True,
    ) -> bool:
        """Return True if a node can carry traffic."""
        if node.id in self.deregistered_nodes:
            return False
        if (
            node.az is not None
            and node.az in self.disabled_azs
            and node.type != NodeType.DATABASE
        ):
            return False
        if not ignore_actual_down and node.status == NodeStatus.DOWN:
            return False
        if check_capacity and node.active_connections >= node.capacity:
            return False
        return True

    def find_shortest_segment(
        self,
        source_id: str,
        target_id: str,
        ignore_actual_down: bool = False,
    ) -> Optional[list[str]]:
        """Compute the lowest-latency path between source_id and target_id.

        Only healthy links and valid transit nodes (IGW, LB, ROUTER) or the
        segment endpoints themselves may be traversed.

        Args:
            source_id: Starting node ID.
            target_id: Destination node ID.
            ignore_actual_down: If True, allow routing toward nodes not yet
                deregistered by health checks (used for detection-lag simulation).

        Returns:
            Ordered list of node IDs from source_id to target_id, or None if unreachable.
        """
        source_node = self.topology.get_node(source_id)
        target_node = self.topology.get_node(target_id)

        if not self._is_node_usable(source_node, ignore_actual_down=ignore_actual_down):
            return None
        if not self._is_node_usable(target_node, ignore_actual_down=ignore_actual_down):
            return None

        def edge_weight(u: str, v: str, attrs: dict) -> Optional[float]:
            link: Link = attrs["data"]
            if not ignore_actual_down and link.status == LinkStatus.DOWN:
                return None

            node_u = self.topology.get_node(u)
            node_v = self.topology.get_node(v)

            if not self._is_node_usable(node_u, ignore_actual_down=ignore_actual_down):
                return None
            if not self._is_node_usable(node_v, ignore_actual_down=ignore_actual_down):
                return None

            if v != target_id and node_v.type not in TRANSIT_NODE_TYPES:
                return None

            return float(link.latency + node_v.latency_ms)

        try:
            return nx.dijkstra_path(
                self.topology.graph,
                source=source_id,
                target=target_id,
                weight=edge_weight,
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def calculate_path_latency(self, path: list[str]) -> float:
        """Compute total node + link latency in milliseconds across a full node path."""
        if not path:
            return 0.0

        total = sum(self.topology.get_node(node_id).latency_ms for node_id in path)
        for i in range(len(path) - 1):
            link = self.topology.get_link(path[i], path[i + 1])
            total += link.latency

        return round(total, 3)

    def _verify_path_health_and_packet_loss(self, path: list[str]) -> Optional[str]:
        """Verify that every node and link on the chosen path is UP/DEGRADED and passes packet loss."""
        for node_id in path:
            node = self.topology.get_node(node_id)
            if node.status == NodeStatus.DOWN:
                return f"NODE_DOWN:{node_id}"
            if node.active_connections >= node.capacity:
                return f"CAPACITY_EXCEEDED:{node_id}"

        for i in range(len(path) - 1):
            link = self.topology.get_link(path[i], path[i + 1])
            if link.status == LinkStatus.DOWN:
                return f"LINK_DOWN:{path[i]}->{path[i + 1]}"
            if link.packet_loss > 0.0 and self.rng.random() < link.packet_loss:
                return f"PACKET_LOSS:{path[i]}->{path[i + 1]}"

        return None

    def _find_best_lb_to_app_route(
        self,
        igw_id: str,
        app_id: str,
        candidate_lbs: list[Node],
        ignore_actual_down: bool = False,
    ) -> Optional[tuple[str, list[str], float]]:
        """Find the LOAD_BALANCER that yields the lowest latency path from IGW to app_id."""
        best_lb_id: Optional[str] = None
        best_path: Optional[list[str]] = None
        best_latency = float("inf")

        for lb in sorted(candidate_lbs, key=lambda n: n.id):
            seg_igw_lb = self.find_shortest_segment(
                igw_id, lb.id, ignore_actual_down=ignore_actual_down
            )
            if not seg_igw_lb:
                continue

            seg_lb_app = self.find_shortest_segment(
                lb.id, app_id, ignore_actual_down=ignore_actual_down
            )
            if not seg_lb_app:
                continue

            combined_path = seg_igw_lb + seg_lb_app[1:]
            latency = self.calculate_path_latency(combined_path)
            if latency < best_latency:
                best_latency = latency
                best_lb_id = lb.id
                best_path = combined_path

        if best_lb_id is None or best_path is None:
            return None
        return best_lb_id, best_path, best_latency

    def route_request(
        self,
        tick: int = 0,
        hold_connection: bool = False,
        ignore_undetected_down: bool = False,
    ) -> RequestResult:
        """Simulate a single request from Internet Gateway -> Load Balancer -> App -> Primary DB."""
        self._request_counter += 1
        req_id = f"req-{self._request_counter:05d}-{uuid.uuid4().hex[:6]}"

        igws = [
            n
            for n in self.topology.get_nodes_by_type(NodeType.INTERNET_GATEWAY)
            if self._is_node_usable(n, ignore_actual_down=ignore_undetected_down)
        ]
        if not igws:
            return RequestResult(
                request_id=req_id,
                tick=tick,
                success=False,
                failure_reason="NO_HEALTHY_IGW",
            )
        igw = sorted(igws, key=lambda n: (n.latency_ms, n.id))[0]

        candidate_lbs = [
            n
            for n in self.topology.get_nodes_by_type(NodeType.LOAD_BALANCER)
            if self._is_node_usable(n, ignore_actual_down=ignore_undetected_down)
        ]
        if not candidate_lbs:
            return RequestResult(
                request_id=req_id,
                tick=tick,
                success=False,
                path=[igw.id],
                failure_reason="NO_HEALTHY_LB",
            )

        all_apps = sorted(
            self.topology.get_nodes_by_type(NodeType.APP_INSTANCE),
            key=lambda n: n.id,
        )
        usable_apps = [
            app
            for app in all_apps
            if self._is_node_usable(app, ignore_actual_down=ignore_undetected_down)
        ]
        if not usable_apps:
            up_apps = [
                app
                for app in all_apps
                if self._is_node_usable(
                    app,
                    ignore_actual_down=ignore_undetected_down,
                    check_capacity=False,
                )
            ]
            reason = "CAPACITY_EXCEEDED" if up_apps else "NO_HEALTHY_APP"
            return RequestResult(
                request_id=req_id,
                tick=tick,
                success=False,
                path=[igw.id],
                failure_reason=reason,
            )

        reachable_app_routes: list[tuple[Node, str, list[str], float]] = []
        for app in usable_apps:
            route_info = self._find_best_lb_to_app_route(
                igw.id,
                app.id,
                candidate_lbs,
                ignore_actual_down=ignore_undetected_down,
            )
            if route_info is not None:
                lb_id, path_to_app, latency_to_app = route_info
                reachable_app_routes.append((app, lb_id, path_to_app, latency_to_app))

        if not reachable_app_routes:
            return RequestResult(
                request_id=req_id,
                tick=tick,
                success=False,
                path=[igw.id],
                failure_reason="NO_ROUTE_TO_APP",
            )

        if self.strategy == LoadBalancingStrategy.ROUND_ROBIN:
            idx = self._rr_cursor % len(reachable_app_routes)
            self._rr_cursor += 1
            chosen_app, chosen_lb_id, path_to_app, _ = reachable_app_routes[idx]
        elif self.strategy == LoadBalancingStrategy.LEAST_CONNECTIONS:
            chosen_app, chosen_lb_id, path_to_app, _ = min(
                reachable_app_routes,
                key=lambda item: (item[0].active_connections, item[3], item[0].id),
            )
        else:
            raise ValueError(f"Unsupported load balancing strategy: {self.strategy}")

        primary_db = self.topology.get_primary_database()
        if primary_db is None or not self._is_node_usable(
            primary_db, ignore_actual_down=ignore_undetected_down
        ):
            return RequestResult(
                request_id=req_id,
                tick=tick,
                success=False,
                path=path_to_app,
                selected_lb=chosen_lb_id,
                selected_app=chosen_app.id,
                failure_reason="NO_PRIMARY_DB",
            )

        seg_app_db = self.find_shortest_segment(
            chosen_app.id,
            primary_db.id,
            ignore_actual_down=ignore_undetected_down,
        )
        if not seg_app_db:
            return RequestResult(
                request_id=req_id,
                tick=tick,
                success=False,
                path=path_to_app,
                selected_lb=chosen_lb_id,
                selected_app=chosen_app.id,
                selected_db=primary_db.id,
                failure_reason="NO_ROUTE_TO_DB",
            )

        full_path = path_to_app + seg_app_db[1:]

        failure = self._verify_path_health_and_packet_loss(full_path)
        if failure is not None:
            return RequestResult(
                request_id=req_id,
                tick=tick,
                success=False,
                path=full_path,
                selected_lb=chosen_lb_id,
                selected_app=chosen_app.id,
                selected_db=primary_db.id,
                failure_reason=failure,
            )

        if hold_connection:
            for node_id in full_path:
                self.topology.get_node(node_id).active_connections += 1

        total_latency = self.calculate_path_latency(full_path)
        return RequestResult(
            request_id=req_id,
            tick=tick,
            success=True,
            path=full_path,
            total_latency_ms=total_latency,
            selected_lb=chosen_lb_id,
            selected_app=chosen_app.id,
            selected_db=primary_db.id,
        )

    def release_path_connections(self, path: list[str]) -> None:
        """Decrement active_connections for each node in a previously held path."""
        for node_id in path:
            node = self.topology.get_node(node_id)
            node.active_connections = max(0, node.active_connections - 1)

    def simulate_batch(
        self,
        num_requests: int,
        tick: int = 0,
        ignore_undetected_down: bool = False,
    ) -> list[RequestResult]:
        """Simulate a batch of concurrent requests arriving within the same tick."""
        results: list[RequestResult] = []
        held_paths: list[list[str]] = []

        try:
            for _ in range(num_requests):
                res = self.route_request(
                    tick=tick,
                    hold_connection=True,
                    ignore_undetected_down=ignore_undetected_down,
                )
                if res.success:
                    held_paths.append(res.path)
                results.append(res)
        finally:
            for path in held_paths:
                self.release_path_connections(path)

        return results
