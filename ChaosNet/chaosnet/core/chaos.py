"""Chaos injection engine for simulating network and infrastructure failures."""

from __future__ import annotations

import random
from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, Field

from chaosnet.core.models import LinkStatus, NodeStatus, NodeType
from chaosnet.core.topology import VPCTopology


class ChaosEventType(StrEnum):
    """Supported chaos event categories."""

    KILL_NODE = "kill_node"
    KILL_AZ = "kill_az"
    DROP_LINK = "drop_link"
    LATENCY_SPIKE = "latency_spike"
    PACKET_LOSS = "packet_loss"
    NETWORK_PARTITION = "network_partition"
    DB_PRIMARY_FAILURE = "db_primary_failure"
    RECOVER = "recover"


class ChaosEvent(BaseModel):
    """Configuration definition for a scheduled, random, or manual chaos event."""

    tick: int = Field(..., ge=0, description="Simulation tick when chaos is injected")
    event_type: ChaosEventType = Field(..., description="Type of failure or recovery to inject")
    target: Optional[str] = Field(
        default=None,
        description="Target node ID, AZ ID, or source->target link specifier",
    )
    duration_ticks: Optional[int] = Field(
        default=None,
        ge=1,
        description="Duration in ticks before automatic recovery (None if manual recovery)",
    )
    magnitude: float = Field(
        default=100.0,
        ge=0.0,
        description="Magnitude parameter (e.g., latency ms spike or packet loss fraction 0.0-1.0)",
    )


class ActiveChaosRecord(BaseModel):
    """Tracks an active chaos injection and its scheduled recovery tick."""

    event: ChaosEvent
    recovery_tick: Optional[int] = Field(
        default=None,
        description="Tick at which this chaos event automatically recovers (None if manual)",
    )
    original_states: dict[str, Any] = Field(
        default_factory=dict,
        description="Snapshot of original property values prior to chaos injection",
    )


class RandomChaosConfig(BaseModel):
    """Configuration for seeded pseudo-random chaos generation."""

    enabled: bool = False
    probability_per_tick: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Probability of injecting a random chaos event on any tick",
    )
    allowed_events: list[ChaosEventType] = Field(
        default_factory=lambda: [
            ChaosEventType.KILL_NODE,
            ChaosEventType.DROP_LINK,
            ChaosEventType.LATENCY_SPIKE,
            ChaosEventType.PACKET_LOSS,
        ],
        description="Event types eligible for random generation",
    )
    min_duration: int = Field(
        default=5,
        ge=1,
        description="Minimum duration in ticks for random chaos events",
    )
    max_duration: int = Field(
        default=20,
        ge=1,
        description="Maximum duration in ticks for random chaos events",
    )


class ChaosEngine:
    """Manages scheduled, scripted, and random chaos injection and recoveries."""

    def __init__(self, topology: VPCTopology, seed: Optional[int] = 42) -> None:
        """Initialize the chaos engine.

        Args:
            topology: VPCTopology instance to mutate.
            seed: RNG seed for reproducible random chaos.
        """
        self.topology = topology
        self.seed = seed
        self.rng = random.Random(seed)
        self.scheduled_events: list[ChaosEvent] = []
        self.active_chaos: list[ActiveChaosRecord] = []
        self.history: list[dict[str, Any]] = []
        self.random_config = RandomChaosConfig()

    def configure_random_chaos(
        self,
        enabled: bool = True,
        probability: float = 0.05,
        allowed_events: Optional[list[ChaosEventType]] = None,
        min_duration: int = 5,
        max_duration: int = 20,
    ) -> None:
        """Configure reproducible random chaos injection parameters."""
        self.random_config = RandomChaosConfig(
            enabled=enabled,
            probability_per_tick=probability,
            allowed_events=allowed_events
            or [
                ChaosEventType.KILL_NODE,
                ChaosEventType.DROP_LINK,
                ChaosEventType.LATENCY_SPIKE,
                ChaosEventType.PACKET_LOSS,
            ],
            min_duration=min_duration,
            max_duration=max_duration,
        )

    def schedule_event(self, event: ChaosEvent) -> None:
        """Add a chaos event to the execution schedule."""
        self.scheduled_events.append(event)
        self.scheduled_events.sort(key=lambda e: e.tick)

    def load_script(self, script_data: list[dict[str, Any]]) -> None:
        """Load a list of chaos events from a JSON script."""
        for item in script_data:
            event = ChaosEvent.model_validate(item)
            self.schedule_event(event)

    def _resolve_partition_nodes(self, target: str) -> tuple[set[str], set[str]]:
        """Split a partition specifier (e.g. 'az-a<->az-b' or 'az-a|az-b') into two node sets."""
        if not target or target.strip() == "":
            target = "az-a<->az-b"
        delimiter = "<->" if "<->" in target else ("|" if "|" in target else ("->" if "->" in target else None))
        if delimiter is None:
            raise ValueError(
                f"network_partition target '{target}' must use '<->' or '|' separator (e.g. 'az-a<->az-b')."
            )
        part_a, part_b = target.split(delimiter, 1)
        part_a = part_a.strip()
        part_b = part_b.strip()

        all_azs = {az.id for az in self.topology.vpc.availability_zones}
        nodes_a: set[str] = set()
        nodes_b: set[str] = set()

        if part_a in all_azs:
            nodes_a = {n.id for n in self.topology.get_all_nodes() if n.az == part_a}
        else:
            nodes_a = {item.strip() for item in part_a.split(",")}

        if part_b in all_azs:
            nodes_b = {n.id for n in self.topology.get_all_nodes() if n.az == part_b}
        else:
            nodes_b = {item.strip() for item in part_b.split(",")}

        return nodes_a, nodes_b

    def inject(self, event: ChaosEvent, current_tick: int) -> dict[str, Any]:
        """Inject a chaos event immediately and record in history.

        Args:
            event: ChaosEvent to execute.
            current_tick: Current simulation tick.

        Returns:
            Structured log record of the action.
        """
        originals: dict[str, Any] = {}
        target = event.target

        if event.event_type == ChaosEventType.RECOVER:
            return self.recover_target(target=target, current_tick=current_tick)

        if event.event_type == ChaosEventType.KILL_NODE:
            if not target:
                raise ValueError("kill_node requires a target node ID.")
            node = self.topology.get_node(target)
            originals[target] = node.status
            self.topology.set_node_status(target, NodeStatus.DOWN)

        elif event.event_type == ChaosEventType.KILL_AZ:
            if not target:
                raise ValueError("kill_az requires a target AZ ID.")
            for node in self.topology.get_all_nodes():
                if node.az == target:
                    originals[node.id] = node.status
                    self.topology.set_node_status(node.id, NodeStatus.DOWN)

        elif event.event_type == ChaosEventType.DROP_LINK:
            if not target:
                raise ValueError("drop_link requires a target formatted as 'source->target' or 'source<->target'.")
            sep = "<->" if "<->" in target else ("->" if "->" in target else ("|" if "|" in target else None))
            if not sep:
                raise ValueError("drop_link target must contain '->', '<->', or '|'.")
            src, dst = target.split(sep, 1)
            src, dst = src.strip(), dst.strip()
            link = self.topology.get_link(src, dst)
            originals[f"{src}->{dst}"] = link.status
            self.topology.set_link_status(src, dst, LinkStatus.DOWN)

        elif event.event_type == ChaosEventType.LATENCY_SPIKE:
            if not target:
                raise ValueError("latency_spike requires a target node ID.")
            node = self.topology.get_node(target)
            originals[target] = node.latency_ms
            node.latency_ms += event.magnitude

        elif event.event_type == ChaosEventType.PACKET_LOSS:
            if not target:
                raise ValueError("packet_loss requires a target link formatted as 'source->target'.")
            sep = "<->" if "<->" in target else ("->" if "->" in target else ("|" if "|" in target else None))
            if not sep:
                raise ValueError("packet_loss target must contain '->', '<->', or '|'.")
            src, dst = target.split(sep, 1)
            src, dst = src.strip(), dst.strip()
            link = self.topology.get_link(src, dst)
            originals[f"{src}->{dst}"] = link.packet_loss
            link.packet_loss = event.magnitude

        elif event.event_type == ChaosEventType.NETWORK_PARTITION:
            if not target or target.strip() == "":
                target = "az-a<->az-b"
                event.target = target
            nodes_a, nodes_b = self._resolve_partition_nodes(target)
            for link in self.topology.get_all_links(deduplicate_bidirectional=True):
                if (link.source in nodes_a and link.target in nodes_b) or (
                    link.source in nodes_b and link.target in nodes_a
                ):
                    originals[f"{link.source}->{link.target}"] = link.status
                    self.topology.set_link_status(link.source, link.target, LinkStatus.DOWN)

        elif event.event_type == ChaosEventType.DB_PRIMARY_FAILURE:
            primary = self.topology.get_primary_database()
            if primary is not None:
                originals[primary.id] = primary.status
                self.topology.set_node_status(primary.id, NodeStatus.DOWN)
                event.target = primary.id

        recovery_tick = (
            current_tick + event.duration_ticks
            if event.duration_ticks is not None
            else None
        )
        self.active_chaos.append(
            ActiveChaosRecord(
                event=event,
                recovery_tick=recovery_tick,
                original_states=originals,
            )
        )

        log_entry = {
            "tick": current_tick,
            "action": "INJECT",
            "event_type": event.event_type.value,
            "target": event.target,
            "magnitude": event.magnitude,
            "duration_ticks": event.duration_ticks,
            "recovery_tick": recovery_tick,
        }
        self.history.append(log_entry)
        return log_entry

    def recover(self, record: ActiveChaosRecord, current_tick: int) -> dict[str, Any]:
        """Revert a chaos event to its original recorded state."""
        event = record.event
        target = event.target

        if event.event_type == ChaosEventType.KILL_NODE:
            if target and target in record.original_states:
                self.topology.set_node_status(target, record.original_states[target])

        elif event.event_type == ChaosEventType.KILL_AZ:
            for node_id, orig_status in record.original_states.items():
                self.topology.set_node_status(node_id, orig_status)

        elif event.event_type == ChaosEventType.DROP_LINK:
            for key, orig_status in record.original_states.items():
                src, dst = key.split("->")
                self.topology.set_link_status(src, dst, orig_status)

        elif event.event_type == ChaosEventType.LATENCY_SPIKE:
            if target and target in record.original_states:
                self.topology.get_node(target).latency_ms = record.original_states[target]

        elif event.event_type == ChaosEventType.PACKET_LOSS:
            for key, orig_loss in record.original_states.items():
                src, dst = key.split("->")
                self.topology.get_link(src, dst).packet_loss = orig_loss

        elif event.event_type == ChaosEventType.NETWORK_PARTITION:
            for key, orig_status in record.original_states.items():
                src, dst = key.split("->")
                self.topology.set_link_status(src, dst, orig_status)

        elif event.event_type == ChaosEventType.DB_PRIMARY_FAILURE:
            if target and target in record.original_states:
                self.topology.set_node_status(target, record.original_states[target])

        log_entry = {
            "tick": current_tick,
            "action": "RECOVER",
            "event_type": event.event_type.value,
            "target": event.target,
        }
        self.history.append(log_entry)
        return log_entry

    def recover_target(self, target: Optional[str], current_tick: int) -> dict[str, Any]:
        """Manually recover active chaos matching a specific target identifier."""
        matched: Optional[ActiveChaosRecord] = None
        for record in self.active_chaos:
            if record.event.target == target or (target is None and record.event.event_type == ChaosEventType.DB_PRIMARY_FAILURE):
                matched = record
                break

        if matched:
            self.active_chaos.remove(matched)
            return self.recover(matched, current_tick)

        # Fallback if no matching snapshot is in active_chaos
        fallback_entry: dict[str, Any] = {
            "tick": current_tick,
            "action": "RECOVER",
            "event_type": "manual_recovery",
            "target": target,
        }
        if target in (None, "", "all"):
            while self.active_chaos:
                rec = self.active_chaos.pop(0)
                self.recover(rec, current_tick)
            for node in self.topology.get_all_nodes():
                self.topology.set_node_status(node.id, NodeStatus.UP)
            for link in self.topology.get_all_links():
                self.topology.set_link_status(link.source, link.target, LinkStatus.UP, both_directions=True)
                link.packet_loss = 0.0
        elif target:
            if target in self.topology.graph.nodes:
                self.topology.set_node_status(target, NodeStatus.UP)
            elif any(az.id == target for az in self.topology.vpc.availability_zones):
                for node in self.topology.get_all_nodes():
                    if node.az == target:
                        self.topology.set_node_status(node.id, NodeStatus.UP)
            elif any(s in target for s in ("<->", "->", "|")):
                sep = "<->" if "<->" in target else ("->" if "->" in target else "|")
                src, dst = target.split(sep, 1)
                self.topology.set_link_status(src.strip(), dst.strip(), LinkStatus.UP, both_directions=True)
        self.history.append(fallback_entry)
        return fallback_entry

    def _generate_random_event(self, current_tick: int) -> Optional[ChaosEvent]:
        """Generate a random chaos event using the deterministic RNG."""
        if not self.random_config.enabled:
            return None
        if self.rng.random() >= self.random_config.probability_per_tick:
            return None

        event_type = self.rng.choice(self.random_config.allowed_events)
        duration = self.rng.randint(
            self.random_config.min_duration, self.random_config.max_duration
        )

        all_nodes = self.topology.get_all_nodes()
        all_links = self.topology.get_all_links(deduplicate_bidirectional=True)
        up_nodes = [n for n in all_nodes if n.status == NodeStatus.UP]
        up_links = [l for l in all_links if l.status == LinkStatus.UP]

        if event_type == ChaosEventType.KILL_NODE:
            if not up_nodes:
                return None
            target_node = self.rng.choice(up_nodes)
            return ChaosEvent(
                tick=current_tick,
                event_type=event_type,
                target=target_node.id,
                duration_ticks=duration,
            )

        elif event_type == ChaosEventType.DROP_LINK:
            if not up_links:
                return None
            target_link = self.rng.choice(up_links)
            return ChaosEvent(
                tick=current_tick,
                event_type=event_type,
                target=f"{target_link.source}->{target_link.target}",
                duration_ticks=duration,
            )

        elif event_type == ChaosEventType.LATENCY_SPIKE:
            if not up_nodes:
                return None
            target_node = self.rng.choice(up_nodes)
            spike = round(self.rng.uniform(30.0, 100.0), 1)
            return ChaosEvent(
                tick=current_tick,
                event_type=event_type,
                target=target_node.id,
                magnitude=spike,
                duration_ticks=duration,
            )

        elif event_type == ChaosEventType.PACKET_LOSS:
            if not up_links:
                return None
            target_link = self.rng.choice(up_links)
            loss = round(self.rng.uniform(0.1, 0.4), 2)
            return ChaosEvent(
                tick=current_tick,
                event_type=event_type,
                target=f"{target_link.source}->{target_link.target}",
                magnitude=loss,
                duration_ticks=duration,
            )

        elif event_type == ChaosEventType.KILL_AZ:
            azs = self.topology.vpc.availability_zones
            if not azs:
                return None
            target_az = self.rng.choice(azs)
            return ChaosEvent(
                tick=current_tick,
                event_type=event_type,
                target=target_az.id,
                duration_ticks=duration,
            )

        elif event_type == ChaosEventType.NETWORK_PARTITION:
            azs = self.topology.vpc.availability_zones
            if len(azs) < 2:
                return None
            pair = self.rng.sample(azs, 2)
            return ChaosEvent(
                tick=current_tick,
                event_type=event_type,
                target=f"{pair[0].id}<->{pair[1].id}",
                duration_ticks=duration,
            )

        elif event_type == ChaosEventType.DB_PRIMARY_FAILURE:
            primary = self.topology.get_primary_database()
            if primary is None or primary.status == NodeStatus.DOWN:
                return None
            return ChaosEvent(
                tick=current_tick,
                event_type=event_type,
                target=primary.id,
                duration_ticks=duration,
            )

        return None

    def step(self, current_tick: int) -> list[dict[str, Any]]:
        """Advance the chaos engine by one tick.

        1. Injects scheduled script events matching current_tick.
        2. Evaluates and injects random chaos if enabled.
        3. Recovers active chaos whose recovery_tick has arrived.
        """
        logs: list[dict[str, Any]] = []

        # 1. Trigger scheduled injections for this tick
        remaining_scheduled: list[ChaosEvent] = []
        for event in self.scheduled_events:
            if event.tick == current_tick:
                logs.append(self.inject(event, current_tick))
            else:
                remaining_scheduled.append(event)
        self.scheduled_events = remaining_scheduled

        # 2. Random chaos generation
        random_event = self._generate_random_event(current_tick)
        if random_event is not None:
            logs.append(self.inject(random_event, current_tick))

        # 3. Check active chaos for automatic recovery
        still_active: list[ActiveChaosRecord] = []
        for record in self.active_chaos:
            if record.recovery_tick is not None and record.recovery_tick == current_tick:
                logs.append(self.recover(record, current_tick))
            else:
                still_active.append(record)
        self.active_chaos = still_active

        return logs
