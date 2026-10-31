#!/usr/bin/env python3
"""Command-Line Interface (CLI) for ChaosNet VPC & Auto-Failover Simulator."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chaosnet.core.engine import SimulationConfig, SimulationEngine
from chaosnet.core.topology import VPCTopology
from chaosnet.core.traffic import LoadBalancingStrategy


def command_run(args: argparse.Namespace) -> int:
    """Execute a scenario simulation run and print the event log and summary."""
    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        print(f"Error: Scenario file '{args.scenario}' not found.", file=sys.stderr)
        return 1

    strategy = LoadBalancingStrategy(args.strategy)
    config = SimulationConfig(
        requests_per_tick=args.requests_per_tick,
        strategy=strategy,
        seed=args.seed,
    )

    print(f"[*] Initializing ChaosNet simulation from: {scenario_path}")
    print(f"[*] Configuration: ticks={args.ticks}, requests/tick={args.requests_per_tick}, strategy={strategy.value}, seed={args.seed}\n")
    print("=" * 80)
    print(f"{'TICK':<10} {'SUBSYSTEM':<12} {'EVENT TYPE':<22} {'DETAILS':<34}")
    print("=" * 80)

    engine = SimulationEngine.from_scenario_file(scenario_path, config=config)

    for tick in range(1, args.ticks + 1):
        prev_events_count = len(engine.metrics.timeline)
        metric = engine.step()
        new_events = engine.metrics.timeline[prev_events_count:]

        # Print all significant events that occurred during this tick
        for ev in new_events:
            target_str = f"target={ev.target}" if ev.target else ""
            desc = f"{target_str} | {ev.description}".strip(" |")
            print(f"[Tick {ev.tick:04d}] [{ev.category:<9}] {ev.event_type:<22} {desc[:50]}")

        # If verbose, print traffic status for each tick
        if args.verbose:
            status_str = f"{metric.requests_succeeded}/{metric.requests_sent} ok"
            print(f"[Tick {metric.tick:04d}] [TRAFFIC  ] BATCH_RESULT            {status_str} | avg={metric.avg_latency_ms}ms | p95={metric.p95_latency_ms}ms")

    summary = engine.get_summary()

    print("\n" + summary.format_table())

    if args.output_json:
        out_path = Path(args.output_json)
        out_path.write_text(summary.to_json(indent=2), encoding="utf-8")
        print(f"\n[+] Saved full JSON metrics report to: {out_path.resolve()}")

    return 0


def command_inspect(args: argparse.Namespace) -> int:
    """Inspect and display the ASCII topology of a scenario file."""
    scenario_path = Path(args.scenario)
    if not scenario_path.exists():
        print(f"Error: Scenario file '{args.scenario}' not found.", file=sys.stderr)
        return 1

    topo = VPCTopology.from_json_file(scenario_path)
    print(topo.format_summary())
    return 0


def command_serve(args: argparse.Namespace) -> int:
    """Start the FastAPI REST and WebSocket server with Uvicorn."""
    try:
        import uvicorn
    except ImportError:
        print("Error: 'uvicorn' is required to run the API server. Install with `pip install uvicorn`.", file=sys.stderr)
        return 1

    print(f"[*] Starting ChaosNet API server on http://{args.host}:{args.port}")
    uvicorn.run(
        "chaosnet.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="chaosnet",
        description="ChaosNet — Interactive Cloud VPC & Auto-Failover Simulator CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Command: run
    run_parser = subparsers.add_parser("run", help="Run a simulation scenario")
    run_parser.add_argument("scenario", help="Path to scenario JSON file (e.g. scenarios/az_failure.json)")
    run_parser.add_argument("--ticks", type=int, default=150, help="Number of ticks to simulate (default: 150)")
    run_parser.add_argument("--requests-per-tick", type=int, default=5, help="Requests per tick (default: 5)")
    run_parser.add_argument(
        "--strategy",
        choices=["ROUND_ROBIN", "LEAST_CONNECTIONS"],
        default="ROUND_ROBIN",
        help="Load balancing strategy (default: ROUND_ROBIN)",
    )
    run_parser.add_argument("--seed", type=int, default=42, help="RNG seed (default: 42)")
    run_parser.add_argument("-v", "--verbose", action="store_true", help="Print per-tick traffic logs")
    run_parser.add_argument("--output-json", help="Optional path to write full JSON summary report")

    # Command: inspect
    inspect_parser = subparsers.add_parser("inspect", help="Display ASCII topology of a scenario")
    inspect_parser.add_argument("scenario", help="Path to scenario JSON file")

    # Command: serve
    serve_parser = subparsers.add_parser("serve", help="Launch FastAPI REST & WebSocket server")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1)")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    serve_parser.add_argument("--reload", action="store_true", help="Enable auto-reload on code change")

    return parser


def main() -> None:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run":
        sys.exit(command_run(args))
    elif args.command == "inspect":
        sys.exit(command_inspect(args))
    elif args.command == "serve":
        sys.exit(command_serve(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
