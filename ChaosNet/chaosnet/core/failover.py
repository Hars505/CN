"""Automated failover engine: LB pool eviction, DB promotion, AZ failover, and auto-scaling."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, Field

from chaosnet.core.health import HealthChecker, HealthState, HealthTransitionEvent
from chaosnet.core.models import DBRole, Link, LinkStatus, Node, NodeStatus, NodeType
from chaosnet.core.topology import VPCTopology
from chaosnet.core.traffic import TrafficRouter


class FailoverEventType(StrEnum):
    """Categories of automated failover and scaling actions."""

    DEREGISTER_NODE = "deregister_node"
    REGISTER_NODE = "register_node"
    DB_PROMOTION = "db_promotion"
    AZ_FAILOVER = "az_failover"
    AZ_RECOVERY = "az_recovery"
    AUTOSCALE_SPAWN = "autoscale_spawn"
    AUTOSCALE_READY = "autoscale_ready"


class FailoverEvent(BaseModel):
    """Structured audit log record for failover and auto-scaling decisions."""

    tick: int = Field(..., ge=0, description="Simulation tick when the failover event occurred")
    event_type: FailoverEventType = Field(..., description="Category of failover action taken")
    target: str = Field(..., description="Target node ID or Availability Zone ID")
    reason: str = Field(..., description="Human-readable rationale for the failover action")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Auxiliary metadata relating to the failover action",
    )


class AutoScalingConfig(BaseModel):
    """Configuration parameters for dynamic replacement instance scaling."""

    enabled: bool = False
    min_healthy_capacity: int = Field(
        default=600,
        ge=0,
        description="Minimum healthy APP_INSTANCE capacity threshold before scaling out",
    )
    max_instances_per_az: int = Field(
        default=4,
        ge=1,
        description="Maximum number of app instances permitted per Availability Zone",
    )
    startup_delay_ticks: int = Field(
        default=3,
        ge=1,
        description="Ticks required for a newly provisioned instance to boot and become ready",
    )
    cooldown_ticks: int = Field(
        default=4,
        ge=0,
        description="Minimum ticks required between successive auto-scaling spawn actions",
    )
    default_instance_capacity: int = Field(
        default=250,
        ge=1,
        description="Throughput capacity assigned to newly spawned instances",
    )
    default_instance_latency_ms: float = Field(
        default=4.0,
        ge=0.0,
        description="Processing latency assigned to newly spawned instances",
    )


class PendingInstance(BaseModel):
    """Represents an auto-scaling replacement instance currently booting."""

    instance_id: str
    az_id: str
    subnet_id: str
    router_id: str
    capacity: int
    latency_ms: float
    spawned_tick: int
    ready_tick: int


class FailoverEngine:
    """Orchestrates automated control-plane failover, target pool management, and auto-scaling."""

    def __init__(
        self,
        topology: VPCTopology,
        router: TrafficRouter,
        health_checker: HealthChecker,
        autoscale_config: Optional[AutoScalingConfig] = None,
    ) -> None:
        """Initialize the failover engine.

        Args:
            topology: Managed VPCTopology instance.
            router: TrafficRouter governing load balancing and path selection.
            health_checker: HealthChecker providing node health telemetry.
            autoscale_config: AutoScalingConfig parameters.
        """
        self.topology = topology
        self.router = router
        self.health_checker = health_checker
        self.autoscale_config = autoscale_config or AutoScalingConfig()

        self.event_history: list[FailoverEvent] = []
        self.disabled_azs: set[str] = set()
        self.pending_instances: list[PendingInstance] = []
        self._asg_counter: int = 0
        self._last_autoscale_tick: int = -999

    def _process_health_transitions(
        self,
        health_events: list[HealthTransitionEvent],
        tick: int,
    ) -> list[FailoverEvent]:
        """React to health checker state changes (deregistrations, registrations, DB failure)."""
        events: list[FailoverEvent] = []

        for h_ev in health_events:
            node = self.topology.get_node(h_ev.node_id)

            # 1. Node became UNHEALTHY
            if h_ev.new_state == HealthState.UNHEALTHY:
                # Evict from load balancer pool
                if node.id not in self.router.deregistered_nodes:
                    self.router.deregister_node(node.id)
                    ev = FailoverEvent(
                        tick=tick,
                        event_type=FailoverEventType.DEREGISTER_NODE,
                        target=node.id,
                        reason=f"Evicted from LB target pool: {h_ev.reason}",
                        details={"node_type": node.type.value, "az": node.az},
                    )
                    self.event_history.append(ev)
                    events.append(ev)

                # Database primary failure detection
                if node.type == NodeType.DATABASE and node.db_role == DBRole.PRIMARY:
                    promotion_ev = self.promote_database_replica(tick, failed_primary_id=node.id)
                    if promotion_ev is not None:
                        events.append(promotion_ev)

            # 2. Node recovered to HEALTHY
            elif h_ev.new_state == HealthState.HEALTHY:
                if node.id in self.router.deregistered_nodes:
                    self.router.register_node(node.id)
                    ev = FailoverEvent(
                        tick=tick,
                        event_type=FailoverEventType.REGISTER_NODE,
                        target=node.id,
                        reason=f"Re-added to LB target pool: {h_ev.reason}",
                        details={"node_type": node.type.value, "az": node.az},
                    )
                    self.event_history.append(ev)
                    events.append(ev)

        return events

    def promote_database_replica(
        self,
        tick: int,
        failed_primary_id: Optional[str] = None,
    ) -> Optional[FailoverEvent]:
        """Promote a healthy DATABASE replica to PRIMARY if the active primary fails.

        Args:
            tick: Current simulation tick.
            failed_primary_id: ID of the failed primary node (auto-detected if None).

        Returns:
            FailoverEvent if a replica was successfully promoted, otherwise None.
        """
        current_primary = self.topology.get_primary_database()
        if failed_primary_id and current_primary and current_primary.id != failed_primary_id:
            return None

        # Search for eligible healthy replicas
        replicas = [
            n
            for n in self.topology.get_nodes_by_type(NodeType.DATABASE)
            if n.db_role == DBRole.REPLICA
            and n.status != NodeStatus.DOWN
            and self.health_checker.is_perceived_healthy(n.id)
        ]
        if not replicas:
            return None

        # Select replica with lowest processing latency
        promoted = sorted(replicas, key=lambda r: (r.latency_ms, r.id))[0]

        # Demote old primary if present
        demoted_id: Optional[str] = None
        if current_primary:
            current_primary.db_role = DBRole.REPLICA
            demoted_id = current_primary.id

        # Promote chosen replica
        promoted.db_role = DBRole.PRIMARY

        event = FailoverEvent(
            tick=tick,
            event_type=FailoverEventType.DB_PROMOTION,
            target=promoted.id,
            reason=(
                f"Promoted replica '{promoted.id}' to PRIMARY after primary "
                f"'{demoted_id}' failure"
            ),
            details={
                "demoted_primary": demoted_id,
                "promoted_primary": promoted.id,
                "az": promoted.az,
            },
        )
        self.event_history.append(event)
        return event

    def _check_az_failover(self, tick: int) -> list[FailoverEvent]:
        """Evaluate AZ-level health and fail traffic over to healthy AZs when an AZ drops."""
        events: list[FailoverEvent] = []

        for az in self.topology.vpc.availability_zones:
            az_apps = self.topology.get_nodes_by_type(NodeType.APP_INSTANCE, az=az.id)
            az_routers = self.topology.get_nodes_by_type(NodeType.ROUTER, az=az.id)

            if not az_apps:
                continue

            # An AZ is considered down if all apps are down/unhealthy, or all routers are down/unhealthy
            healthy_apps = [
                app
                for app in az_apps
                if app.status != NodeStatus.DOWN
                and self.health_checker.is_perceived_healthy(app.id)
            ]
            healthy_routers = [
                r
                for r in az_routers
                if r.status != NodeStatus.DOWN
                and self.health_checker.is_perceived_healthy(r.id)
            ]

            az_is_down = (len(healthy_apps) == 0) or (len(az_routers) > 0 and len(healthy_routers) == 0)

            # AZ newly failed
            if az_is_down and az.id not in self.disabled_azs:
                self.disabled_azs.add(az.id)
                self.router.disable_az(az.id)
                ev = FailoverEvent(
                    tick=tick,
                    event_type=FailoverEventType.AZ_FAILOVER,
                    target=az.id,
                    reason=(
                        f"All app instances or routers in AZ '{az.id}' are unhealthy; "
                        f"rerouting traffic to alternate AZs"
                    ),
                    details={"total_apps": len(az_apps), "healthy_apps": len(healthy_apps)},
                )
                self.event_history.append(ev)
                events.append(ev)

            # AZ recovered
            elif not az_is_down and az.id in self.disabled_azs:
                self.disabled_azs.remove(az.id)
                self.router.enable_az(az.id)
                ev = FailoverEvent(
                    tick=tick,
                    event_type=FailoverEventType.AZ_RECOVERY,
                    target=az.id,
                    reason=(
                        f"Healthy app instances and routers restored in AZ '{az.id}'; "
                        f"re-enabling AZ traffic"
                    ),
                    details={"healthy_apps": len(healthy_apps)},
                )
                self.event_history.append(ev)
                events.append(ev)

        return events

    def get_healthy_app_capacity(self) -> int:
        """Compute the aggregate throughput capacity of all currently routable app instances."""
        total = 0
        for app in self.topology.get_nodes_by_type(NodeType.APP_INSTANCE):
            if (
                app.status != NodeStatus.DOWN
                and self.health_checker.is_perceived_healthy(app.id)
                and app.id not in self.router.deregistered_nodes
                and (app.az is None or app.az not in self.router.disabled_azs)
            ):
                total += app.capacity
        return total

    def _process_autoscale_ready(self, tick: int) -> list[FailoverEvent]:
        """Finalize boot sequence for pending replacement instances whose startup delay elapsed."""
        events: list[FailoverEvent] = []
        still_pending: list[PendingInstance] = []

        for pending in self.pending_instances:
            if tick >= pending.ready_tick:
                # 1. Add new Node to the topology graph
                new_node = Node(
                    id=pending.instance_id,
                    type=NodeType.APP_INSTANCE,
                    az=pending.az_id,
                    subnet=pending.subnet_id,
                    status=NodeStatus.UP,
                    latency_ms=pending.latency_ms,
                    capacity=pending.capacity,
                )
                self.topology.add_node(new_node)

                # 2. Add Link to AZ Router
                self.topology.add_link(
                    Link(
                        source=pending.router_id,
                        target=pending.instance_id,
                        latency=0.6,
                        bandwidth=1000,
                        status=LinkStatus.UP,
                        bidirectional=True,
                    )
                )

                # 3. Add Links to all database nodes in the VPC
                for db in self.topology.get_nodes_by_type(NodeType.DATABASE):
                    link_latency = 1.0 if db.az == pending.az_id else 3.2
                    self.topology.add_link(
                        Link(
                            source=pending.instance_id,
                            target=db.id,
                            latency=link_latency,
                            bandwidth=2000,
                            status=LinkStatus.UP,
                            bidirectional=True,
                        )
                    )

                # 4. Sync with health checker & register in load balancer
                self.health_checker.sync_nodes()
                self.router.register_node(pending.instance_id)

                ev = FailoverEvent(
                    tick=tick,
                    event_type=FailoverEventType.AUTOSCALE_READY,
                    target=pending.instance_id,
                    reason=(
                        f"Auto-scaled replacement instance '{pending.instance_id}' completed "
                        f"startup and joined LB target pool"
                    ),
                    details={
                        "az": pending.az_id,
                        "capacity": pending.capacity,
                        "latency_ms": pending.latency_ms,
                    },
                )
                self.event_history.append(ev)
                events.append(ev)
            else:
                still_pending.append(pending)

        self.pending_instances = still_pending
        return events

    def _evaluate_autoscale_capacity(self, tick: int) -> list[FailoverEvent]:
        """Trigger auto-scaling spawn when aggregate healthy capacity falls below threshold."""
        if not self.autoscale_config.enabled:
            return []

        if tick < self._last_autoscale_tick + self.autoscale_config.cooldown_ticks:
            return []

        healthy_capacity = self.get_healthy_app_capacity()
        if healthy_capacity >= self.autoscale_config.min_healthy_capacity:
            return []

        # Find healthy AZ with capacity headroom
        eligible_azs: list[str] = []
        for az in self.topology.vpc.availability_zones:
            if az.id in self.disabled_azs:
                continue
            current_count = len(self.topology.get_nodes_by_type(NodeType.APP_INSTANCE, az=az.id))
            pending_count = sum(1 for p in self.pending_instances if p.az_id == az.id)
            if current_count + pending_count < self.autoscale_config.max_instances_per_az:
                eligible_azs.append(az.id)

        if not eligible_azs:
            return []

        # Pick AZ with fewest app instances
        chosen_az_id = sorted(
            eligible_azs,
            key=lambda az_id: len(
                self.topology.get_nodes_by_type(NodeType.APP_INSTANCE, az=az_id)
            ),
        )[0]

        # Identify private subnet and router in chosen AZ
        chosen_az = self.topology._az_index[chosen_az_id]
        priv_subnets = [s for s in chosen_az.subnets if s.type.value == "PRIVATE"]
        if not priv_subnets:
            return []
        subnet_id = priv_subnets[0].id

        routers = self.topology.get_nodes_by_type(NodeType.ROUTER, az=chosen_az_id)
        if not routers:
            return []
        router_id = routers[0].id

        self._asg_counter += 1
        inst_id = f"app-{chosen_az_id[-1]}-asg-{self._asg_counter}"
        ready_tick = tick + self.autoscale_config.startup_delay_ticks

        pending = PendingInstance(
            instance_id=inst_id,
            az_id=chosen_az_id,
            subnet_id=subnet_id,
            router_id=router_id,
            capacity=self.autoscale_config.default_instance_capacity,
            latency_ms=self.autoscale_config.default_instance_latency_ms,
            spawned_tick=tick,
            ready_tick=ready_tick,
        )
        self.pending_instances.append(pending)
        self._last_autoscale_tick = tick

        ev = FailoverEvent(
            tick=tick,
            event_type=FailoverEventType.AUTOSCALE_SPAWN,
            target=inst_id,
            reason=(
                f"Healthy capacity {healthy_capacity} < threshold "
                f"{self.autoscale_config.min_healthy_capacity}; spawning replacement "
                f"instance '{inst_id}' in '{chosen_az_id}' (ready at tick {ready_tick})"
            ),
            details={
                "healthy_capacity": healthy_capacity,
                "threshold": self.autoscale_config.min_healthy_capacity,
                "az": chosen_az_id,
                "startup_delay_ticks": self.autoscale_config.startup_delay_ticks,
            },
        )
        self.event_history.append(ev)
        return [ev]

    def step(
        self,
        tick: int,
        health_events: Optional[list[HealthTransitionEvent]] = None,
    ) -> list[FailoverEvent]:
        """Advance the failover engine by one simulation tick.

        Args:
            tick: Current simulation tick.
            health_events: State transitions emitted by HealthChecker on this tick.

        Returns:
            List of FailoverEvent objects executed on this tick.
        """
        all_events: list[FailoverEvent] = []

        # 1. Process health check transitions (evictions, recovery, DB failure)
        if health_events:
            all_events.extend(self._process_health_transitions(health_events, tick))

        # 2. Check AZ-level outages and recoveries
        all_events.extend(self._check_az_failover(tick))

        # 3. Finalize booting replacement instances
        all_events.extend(self._process_autoscale_ready(tick))

        # 4. Evaluate auto-scaling capacity deficit
        all_events.extend(self._evaluate_autoscale_capacity(tick))

        return all_events
