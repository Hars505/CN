"""Metrics collection, MTTR, detection time, latency percentiles, and summary reports."""

from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, Field

from chaosnet.core.traffic import RequestResult


def compute_percentile(values: list[float], percentile: float = 0.95) -> float:
    """Compute the specified percentile (e.g. 0.95 for p95) from a list of numerical values."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = min(len(sorted_vals) - 1, int(percentile * len(sorted_vals)))
    return round(sorted_vals[idx], 2)


class TimelineEntry(BaseModel):
    """Structured entry in the simulation event timeline."""

    tick: int
    category: str = Field(..., description="CHAOS, HEALTH, FAILOVER, or TRAFFIC")
    event_type: str
    target: Optional[str] = None
    description: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class IncidentRecord(BaseModel):
    """Tracks a single failure event from onset through detection, failover, and full recovery."""

    incident_id: str
    fault_type: str
    target: Optional[str] = None
    onset_tick: int
    detected_tick: Optional[int] = None
    detection_time_ticks: Optional[int] = None
    failover_tick: Optional[int] = None
    failover_time_ticks: Optional[int] = None
    recovered_tick: Optional[int] = None
    recovery_time_ticks: Optional[int] = None
    requests_lost: int = 0
    status: str = "ACTIVE"


class TickMetrics(BaseModel):
    """Aggregated performance and health telemetry for a single simulation tick."""

    tick: int
    requests_sent: int = 0
    requests_succeeded: int = 0
    requests_failed: int = 0
    success_rate_pct: float = 100.0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    healthy_app_capacity: int = 0
    active_incidents: int = 0


class SimulationSummary(BaseModel):
    """Comprehensive post-run summary report of simulation performance and reliability."""

    total_ticks: int
    total_requests: int
    successful_requests: int
    failed_requests: int
    availability_pct: float
    avg_latency_ms: float
    p95_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    mean_detection_time_ticks: float
    mean_failover_time_ticks: float
    total_requests_lost_during_failover: int
    incidents: list[dict[str, Any]]
    timeline: list[TimelineEntry]
    series: list[TickMetrics]

    def to_dict(self) -> dict[str, Any]:
        """Convert the summary model into a JSON-compatible dictionary."""
        return self.model_dump(mode="json")

    def to_json(self, indent: int = 2) -> str:
        """Serialize the summary report into a formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def format_table(self) -> str:
        """Format key metrics into an executive ASCII summary table."""
        lines = [
            "=" * 64,
            "               CHAOSNET SIMULATION SUMMARY REPORT               ",
            "=" * 64,
            f" Total Ticks Simulated:         {self.total_ticks:>12}",
            f" Total Requests Generated:      {self.total_requests:>12}",
            f" Successful Requests:           {self.successful_requests:>12}",
            f" Failed Requests:               {self.failed_requests:>12}",
            f" Availability (Uptime):         {self.availability_pct:>11.2f}%",
            "-" * 64,
            f" Mean Detection Time:           {self.mean_detection_time_ticks:>10.2f} ticks",
            f" Mean Failover Time (MTTR):     {self.mean_failover_time_ticks:>10.2f} ticks",
            f" Requests Lost During Failover: {self.total_requests_lost_during_failover:>12}",
            "-" * 64,
            f" Average Request Latency:       {self.avg_latency_ms:>10.2f} ms",
            f" P95 Request Latency:           {self.p95_latency_ms:>10.2f} ms",
            f" Min / Max Latency:             {self.min_latency_ms:.1f}ms / {self.max_latency_ms:.1f}ms",
            "-" * 64,
            f" Total Chaos Incidents:         {len(self.incidents):>12}",
            "=" * 64,
        ]
        return "\n".join(lines)


class MetricsCollector:
    """Collects and aggregates request results, incident timelines, and failover metrics."""

    def __init__(self) -> None:
        """Initialize the metrics collector."""
        self.timeline: list[TimelineEntry] = []
        self.incidents: list[IncidentRecord] = []
        self.tick_series: list[TickMetrics] = []
        self._all_request_latencies: list[float] = []
        self._total_requests: int = 0
        self._total_succeeded: int = 0
        self._total_failed: int = 0
        self._incident_counter: int = 0

    def log_event(
        self,
        tick: int,
        category: str,
        event_type: str,
        target: Optional[str] = None,
        description: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> TimelineEntry:
        """Add an event to the chronological timeline."""
        entry = TimelineEntry(
            tick=tick,
            category=category,
            event_type=event_type,
            target=target,
            description=description,
            metadata=metadata or {},
        )
        self.timeline.append(entry)
        return entry

    def record_chaos_injection(
        self,
        tick: int,
        event_type: str,
        target: Optional[str],
        duration_ticks: Optional[int] = None,
        magnitude: float = 0.0,
    ) -> IncidentRecord:
        """Register the onset of a new chaos failure incident."""
        self._incident_counter += 1
        inc_id = f"inc-{self._incident_counter:04d}-{event_type}"
        record = IncidentRecord(
            incident_id=inc_id,
            fault_type=event_type,
            target=target,
            onset_tick=tick,
        )
        self.incidents.append(record)

        self.log_event(
            tick=tick,
            category="CHAOS",
            event_type=f"INJECT_{event_type.upper()}",
            target=target,
            description=f"Injected {event_type} on target '{target}' (duration={duration_ticks}t)",
            metadata={"incident_id": inc_id, "magnitude": magnitude, "duration": duration_ticks},
        )
        return record

    def record_detection(
        self,
        tick: int,
        node_id: str,
        detection_delay_ticks: Optional[int] = None,
        reason: str = "",
    ) -> None:
        """Log health check failure detection and update matching active incidents."""
        self.log_event(
            tick=tick,
            category="HEALTH",
            event_type="UNHEALTHY_DETECTED",
            target=node_id,
            description=f"Node '{node_id}' detected UNHEALTHY (detection_lag={detection_delay_ticks}t): {reason}",
            metadata={"detection_delay": detection_delay_ticks},
        )

        # Match active incident for this node
        for inc in self.incidents:
            if inc.status == "ACTIVE" and (inc.target == node_id or inc.target is None):
                if inc.detected_tick is None:
                    inc.detected_tick = tick
                    inc.detection_time_ticks = max(0, tick - inc.onset_tick)

    def record_failover(
        self,
        tick: int,
        event_type: str,
        target: str,
        reason: str = "",
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """Log a failover decision and mark failover completion for active incidents."""
        self.log_event(
            tick=tick,
            category="FAILOVER",
            event_type=event_type.upper(),
            target=target,
            description=f"Failover action {event_type} on '{target}': {reason}",
            metadata=details or {},
        )

        for inc in self.incidents:
            if inc.status == "ACTIVE":
                if inc.failover_tick is None:
                    inc.failover_tick = tick
                    inc.failover_time_ticks = max(0, tick - inc.onset_tick)

    def record_recovery(self, tick: int, target: Optional[str], event_type: str = "RECOVER") -> None:
        """Mark an incident as fully recovered."""
        self.log_event(
            tick=tick,
            category="CHAOS" if "RECOVER" in event_type else "HEALTH",
            event_type=event_type.upper(),
            target=target,
            description=f"Target '{target}' restored to operational state",
        )

        for inc in self.incidents:
            if inc.status == "ACTIVE" and (inc.target == target or target is None):
                inc.recovered_tick = tick
                inc.recovery_time_ticks = max(0, tick - inc.onset_tick)
                inc.status = "RESOLVED"

    def record_tick_traffic(
        self,
        tick: int,
        results: list[RequestResult],
        healthy_capacity: int = 0,
    ) -> TickMetrics:
        """Aggregate batch request outcomes for the current tick."""
        total = len(results)
        succeeded = sum(1 for r in results if r.success)
        failed = total - succeeded

        self._total_requests += total
        self._total_succeeded += succeeded
        self._total_failed += failed

        # Attribute dropped requests to all currently active incidents
        if failed > 0:
            for inc in self.incidents:
                if inc.status == "ACTIVE":
                    inc.requests_lost += failed

        latencies = [r.total_latency_ms for r in results if r.success]
        self._all_request_latencies.extend(latencies)

        avg_lat = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
        p95_lat = compute_percentile(latencies, 0.95)
        min_lat = min(latencies) if latencies else 0.0
        max_lat = max(latencies) if latencies else 0.0
        success_pct = round((succeeded / total) * 100.0, 2) if total > 0 else 100.0

        active_inc_count = sum(1 for inc in self.incidents if inc.status == "ACTIVE")

        metric = TickMetrics(
            tick=tick,
            requests_sent=total,
            requests_succeeded=succeeded,
            requests_failed=failed,
            success_rate_pct=success_pct,
            avg_latency_ms=avg_lat,
            p95_latency_ms=p95_lat,
            min_latency_ms=round(min_lat, 2),
            max_latency_ms=round(max_lat, 2),
            healthy_app_capacity=healthy_capacity,
            active_incidents=active_inc_count,
        )
        self.tick_series.append(metric)
        return metric

    def compute_summary(self, total_ticks: int) -> SimulationSummary:
        """Compute the final comprehensive metrics summary."""
        avail_pct = (
            round((self._total_succeeded / self._total_requests) * 100.0, 2)
            if self._total_requests > 0
            else 100.0
        )
        avg_lat = (
            round(sum(self._all_request_latencies) / len(self._all_request_latencies), 2)
            if self._all_request_latencies
            else 0.0
        )
        p95_lat = compute_percentile(self._all_request_latencies, 0.95)
        min_lat = min(self._all_request_latencies) if self._all_request_latencies else 0.0
        max_lat = max(self._all_request_latencies) if self._all_request_latencies else 0.0

        # Mean detection times
        detection_times = [
            inc.detection_time_ticks
            for inc in self.incidents
            if inc.detection_time_ticks is not None
        ]
        mean_detection = (
            round(sum(detection_times) / len(detection_times), 2)
            if detection_times
            else 0.0
        )

        # Mean failover times
        failover_times = [
            inc.failover_time_ticks
            for inc in self.incidents
            if inc.failover_time_ticks is not None
        ]
        mean_failover = (
            round(sum(failover_times) / len(failover_times), 2)
            if failover_times
            else 0.0
        )

        total_lost = sum(inc.requests_lost for inc in self.incidents)

        return SimulationSummary(
            total_ticks=total_ticks,
            total_requests=self._total_requests,
            successful_requests=self._total_succeeded,
            failed_requests=self._total_failed,
            availability_pct=avail_pct,
            avg_latency_ms=avg_lat,
            p95_latency_ms=p95_lat,
            min_latency_ms=round(min_lat, 2),
            max_latency_ms=round(max_lat, 2),
            mean_detection_time_ticks=mean_detection,
            mean_failover_time_ticks=mean_failover,
            total_requests_lost_during_failover=total_lost,
            incidents=[inc.model_dump(mode="json") for inc in self.incidents],
            timeline=self.timeline,
            series=self.tick_series,
        )
