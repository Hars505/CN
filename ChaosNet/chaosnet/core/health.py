"""Control-plane health checker with configurable thresholds and detection lag."""

from __future__ import annotations

from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, Field

from chaosnet.core.models import Node, NodeStatus
from chaosnet.core.topology import VPCTopology


class HealthState(StrEnum):
    """Perceived health state of a node from the control plane's perspective."""

    HEALTHY = "HEALTHY"
    UNHEALTHY = "UNHEALTHY"


class HealthCheckConfig(BaseModel):
    """Configuration parameters for periodic node health checks."""

    interval_ticks: int = Field(
        default=2,
        ge=1,
        description="Number of simulation ticks between consecutive health probes",
    )
    timeout_ms: float = Field(
        default=50.0,
        gt=0.0,
        description="Maximum allowed node latency (ms) before a health probe times out",
    )
    unhealthy_threshold: int = Field(
        default=3,
        ge=1,
        description="Consecutive failed probes required to mark a HEALTHY node UNHEALTHY",
    )
    healthy_threshold: int = Field(
        default=2,
        ge=1,
        description="Consecutive successful probes required to mark an UNHEALTHY node HEALTHY",
    )


class NodeHealthRecord(BaseModel):
    """Per-node health tracking state and failure detection metrics."""

    node_id: str
    perceived_state: HealthState = HealthState.HEALTHY
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_check_tick: Optional[int] = None
    failure_started_tick: Optional[int] = None
    detected_unhealthy_tick: Optional[int] = None
    last_detection_time_ticks: Optional[int] = None
    last_failure_reason: Optional[str] = None


class HealthTransitionEvent(BaseModel):
    """Structured event emitted when a node's perceived health state changes."""

    tick: int
    node_id: str
    previous_state: HealthState
    new_state: HealthState
    reason: str
    detection_time_ticks: Optional[int] = Field(
        default=None,
        description="Ticks elapsed between physical failure onset and UNHEALTHY detection",
    )


class HealthChecker:
    """Executes periodic health probes across VPC nodes and tracks detection times."""

    def __init__(
        self,
        topology: VPCTopology,
        config: Optional[HealthCheckConfig] = None,
    ) -> None:
        """Initialize the health checker for a given VPC topology.

        Args:
            topology: The VPCTopology instance to monitor.
            config: HealthCheckConfig parameters (uses defaults if omitted).
        """
        self.topology = topology
        self.config = config or HealthCheckConfig()
        self.records: dict[str, NodeHealthRecord] = {
            node.id: NodeHealthRecord(node_id=node.id)
            for node in self.topology.get_all_nodes()
        }
        self.transition_history: list[HealthTransitionEvent] = []
        self.detection_times: list[int] = []

    def sync_nodes(self) -> None:
        """Ensure any dynamically spawned nodes (e.g., auto-scaling) have health records."""
        for node in self.topology.get_all_nodes():
            if node.id not in self.records:
                self.records[node.id] = NodeHealthRecord(node_id=node.id)

    def probe_node(self, node: Node) -> tuple[bool, str]:
        """Perform a single health probe against a node.

        Returns:
            Tuple of (passed, reason_code).
        """
        if node.status == NodeStatus.DOWN:
            return False, "NODE_STATUS_DOWN"
        if node.latency_ms > self.config.timeout_ms:
            return (
                False,
                f"PROBE_TIMEOUT:{node.latency_ms}ms>{self.config.timeout_ms}ms",
            )
        return True, "OK"

    def _observe_underlying_fault_onset(self, tick: int) -> None:
        """Track the exact tick a node first becomes physically faulty."""
        for node in self.topology.get_all_nodes():
            record = self.records[node.id]
            passed, _ = self.probe_node(node)
            if not passed:
                if (
                    record.perceived_state == HealthState.HEALTHY
                    and record.failure_started_tick is None
                ):
                    record.failure_started_tick = tick
            else:
                if (
                    record.perceived_state == HealthState.HEALTHY
                    and record.consecutive_failures == 0
                ):
                    record.failure_started_tick = None

    def step(self, tick: int) -> list[HealthTransitionEvent]:
        """Advance the health checker by one simulation tick."""
        self.sync_nodes()
        self._observe_underlying_fault_onset(tick)

        if tick % self.config.interval_ticks != 0:
            return []

        events: list[HealthTransitionEvent] = []

        for node in sorted(self.topology.get_all_nodes(), key=lambda n: n.id):
            record = self.records[node.id]
            record.last_check_tick = tick
            passed, reason = self.probe_node(node)

            if passed:
                record.consecutive_successes += 1
                record.consecutive_failures = 0

                if record.perceived_state == HealthState.HEALTHY:
                    record.failure_started_tick = None
                elif (
                    record.perceived_state == HealthState.UNHEALTHY
                    and record.consecutive_successes >= self.config.healthy_threshold
                ):
                    record.perceived_state = HealthState.HEALTHY
                    record.failure_started_tick = None
                    record.detected_unhealthy_tick = None
                    record.last_failure_reason = None

                    event = HealthTransitionEvent(
                        tick=tick,
                        node_id=node.id,
                        previous_state=HealthState.UNHEALTHY,
                        new_state=HealthState.HEALTHY,
                        reason=f"Passed {record.consecutive_successes} consecutive health checks",
                        detection_time_ticks=None,
                    )
                    self.transition_history.append(event)
                    events.append(event)
            else:
                record.consecutive_failures += 1
                record.consecutive_successes = 0
                record.last_failure_reason = reason

                if record.failure_started_tick is None:
                    record.failure_started_tick = tick

                if (
                    record.perceived_state == HealthState.HEALTHY
                    and record.consecutive_failures >= self.config.unhealthy_threshold
                ):
                    record.perceived_state = HealthState.UNHEALTHY
                    record.detected_unhealthy_tick = tick
                    detection_delay = max(0, tick - record.failure_started_tick)
                    record.last_detection_time_ticks = detection_delay
                    self.detection_times.append(detection_delay)

                    event = HealthTransitionEvent(
                        tick=tick,
                        node_id=node.id,
                        previous_state=HealthState.HEALTHY,
                        new_state=HealthState.UNHEALTHY,
                        reason=(
                            f"Failed {record.consecutive_failures} consecutive checks "
                            f"({reason})"
                        ),
                        detection_time_ticks=detection_delay,
                    )
                    self.transition_history.append(event)
                    events.append(event)

        return events

    def is_perceived_healthy(self, node_id: str) -> bool:
        """Return True if the control plane currently considers node_id HEALTHY."""
        return self.records[node_id].perceived_state == HealthState.HEALTHY

    def get_unhealthy_node_ids(self) -> list[str]:
        """Return sorted list of node IDs currently marked UNHEALTHY."""
        return sorted(
            node_id
            for node_id, rec in self.records.items()
            if rec.perceived_state == HealthState.UNHEALTHY
        )

    def get_average_detection_time(self) -> float:
        """Return the mean failure detection time in ticks across all detected failures."""
        if not self.detection_times:
            return 0.0
        return round(sum(self.detection_times) / len(self.detection_times), 3)
