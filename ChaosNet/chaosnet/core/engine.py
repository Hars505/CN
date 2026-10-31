"""Tick-based deterministic simulation loop orchestrating all VPC subsystems."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from chaosnet.core.chaos import ChaosEngine, ChaosEvent
from chaosnet.core.failover import AutoScalingConfig, FailoverEngine
from chaosnet.core.health import HealthCheckConfig, HealthChecker, HealthState
from chaosnet.core.metrics import MetricsCollector, SimulationSummary, TickMetrics
from chaosnet.core.models import TopologyConfig
from chaosnet.core.topology import VPCTopology
from chaosnet.core.traffic import LoadBalancingStrategy, TrafficRouter


class SimulationConfig(BaseModel):
    """Runtime configuration options for a simulation execution."""

    requests_per_tick: int = Field(
        default=10,
        ge=1,
        description="Number of concurrent requests routed in each simulation tick",
    )
    strategy: LoadBalancingStrategy = Field(
        default=LoadBalancingStrategy.ROUND_ROBIN,
        description="Load balancing algorithm (ROUND_ROBIN or LEAST_CONNECTIONS)",
    )
    seed: Optional[int] = Field(
        default=42,
        description="RNG seed for deterministic network simulation and random chaos",
    )
    health_config: Optional[HealthCheckConfig] = None
    autoscale_config: Optional[AutoScalingConfig] = None


class SimulationEngine:
    """Deterministic, tick-based simulation orchestrator coordinating VPC subsystems."""

    def __init__(
        self,
        topology: VPCTopology,
        config: Optional[SimulationConfig] = None,
        chaos_script: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        """Initialize the simulation engine and wire all subsystems together.

        Args:
            topology: Initialized VPCTopology instance.
            config: SimulationConfig options (uses defaults if omitted).
            chaos_script: Optional list of scheduled chaos event definitions.
        """
        self.config = config or SimulationConfig()
        self.topology = topology
        self.current_tick: int = 0

        self.router = TrafficRouter(
            topology=self.topology,
            strategy=self.config.strategy,
            seed=self.config.seed,
        )
        self.health = HealthChecker(
            topology=self.topology,
            config=self.config.health_config or HealthCheckConfig(),
        )
        self.failover = FailoverEngine(
            topology=self.topology,
            router=self.router,
            health_checker=self.health,
            autoscale_config=self.config.autoscale_config or AutoScalingConfig(),
        )
        self.chaos = ChaosEngine(
            topology=self.topology,
            seed=self.config.seed,
        )
        self.metrics = MetricsCollector()

        if chaos_script:
            self.chaos.load_script(chaos_script)

    @classmethod
    def from_scenario_file(
        cls,
        file_path: str | Path,
        config: Optional[SimulationConfig] = None,
    ) -> SimulationEngine:
        """Construct a ready-to-run SimulationEngine from a scenario JSON file.

        Loads both the VPC topology graph and any defined 'chaos_script'.
        """
        path = Path(file_path)
        raw_data = json.loads(path.read_text(encoding="utf-8"))

        topo_data = raw_data.get("topology", raw_data)
        topology = VPCTopology.from_dict(topo_data)

        chaos_script = raw_data.get("chaos_script", None)
        return cls(topology=topology, config=config, chaos_script=chaos_script)

    def step(self) -> TickMetrics:
        """Advance the simulation by exactly one tick and collect all metrics.

        Execution order within each tick:
          1. Chaos engine injects failures or reverts recovered resources.
          2. Health checker probes nodes and emits health state transitions.
          3. Failover engine evicts unhealthy nodes, promotes DB replica, or scales instances.
          4. Traffic router generates and routes the batch of concurrent requests.
          5. Metrics collector aggregates results and records performance telemetry.

        Returns:
            TickMetrics for the executed tick.
        """
        self.current_tick += 1
        tick = self.current_tick

        # 1. Chaos Engine Step
        chaos_logs = self.chaos.step(tick)
        for log in chaos_logs:
            if log["action"] == "INJECT":
                self.metrics.record_chaos_injection(
                    tick=tick,
                    event_type=log["event_type"],
                    target=log["target"],
                    duration_ticks=log.get("duration_ticks"),
                    magnitude=log.get("magnitude", 0.0),
                )
            elif log["action"] == "RECOVER":
                self.metrics.record_recovery(
                    tick=tick,
                    target=log["target"],
                    event_type=f"RECOVER_{log['event_type'].upper()}",
                )

        # 2. Health Checker Step
        health_events = self.health.step(tick)
        for h_ev in health_events:
            if h_ev.new_state == HealthState.UNHEALTHY:
                self.metrics.record_detection(
                    tick=tick,
                    node_id=h_ev.node_id,
                    detection_delay_ticks=h_ev.detection_time_ticks,
                    reason=h_ev.reason,
                )
            elif h_ev.new_state == HealthState.HEALTHY:
                self.metrics.record_recovery(
                    tick=tick,
                    target=h_ev.node_id,
                    event_type="HEALTH_RESTORED",
                )

        # 3. Failover Engine Step
        failover_events = self.failover.step(tick, health_events=health_events)
        for f_ev in failover_events:
            self.metrics.record_failover(
                tick=tick,
                event_type=f_ev.event_type.value,
                target=f_ev.target,
                reason=f_ev.reason,
                details=f_ev.details,
            )

        # 4. Traffic Routing Batch
        request_results = self.router.simulate_batch(
            num_requests=self.config.requests_per_tick,
            tick=tick,
            ignore_undetected_down=True,
        )

        # 5. Metrics Aggregation
        healthy_capacity = self.failover.get_healthy_app_capacity()
        tick_metric = self.metrics.record_tick_traffic(
            tick=tick,
            results=request_results,
            healthy_capacity=healthy_capacity,
        )

        return tick_metric

    def run(self, num_ticks: int) -> SimulationSummary:
        """Run the simulation for the specified number of ticks and return the summary report.

        Args:
            num_ticks: Total number of ticks to advance.

        Returns:
            SimulationSummary containing complete timeline, series, and aggregated KPIs.
        """
        for _ in range(num_ticks):
            self.step()

        return self.get_summary()

    def get_summary(self) -> SimulationSummary:
        """Return the current comprehensive simulation summary."""
        return self.metrics.compute_summary(total_ticks=self.current_tick)
