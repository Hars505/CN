# Task 1 Report

## Status

Completed.

## Files Changed

- `/home/harshil/STUDY/ChaosNet/tests/test_phase7_api_cli.py`
  - Added a parametrized `TestClient` test for all eight frontend chaos-injection payloads.
  - Added a build-conditional SPA route test for `/` and `/simulator` that checks for HTTP 200 and `ChaosNet` content.
- `/home/harshil/STUDY/ChaosNet/chaosnet/api/main.py`
  - No change required: it already imports `FileResponse` from `fastapi.responses` and `StaticFiles` from `fastapi.staticfiles`.

## Tests and Output

Command run:

```text
pytest tests/test_phase7_api_cli.py -v
```

Exact result:

```text
============================= test session starts ==============================
platform linux -- Python 3.14.4, pytest-9.2.0, pluggy-1.7.0 -- /home/harshil/STUDY/ChaosNet/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /home/harshil/STUDY/ChaosNet
configfile: pyproject.toml
plugins: anyio-4.15.1
collecting ... collected 15 items

tests/test_phase7_api_cli.py::test_get_topology_endpoint PASSED          [  6%]
tests/test_phase7_api_cli.py::test_simulation_step_pause_and_reset_endpoints PASSED [ 13%]
tests/test_phase7_api_cli.py::test_chaos_inject_endpoint PASSED          [ 20%]
tests/test_phase7_api_cli.py::test_chaos_injection_payloads[kill_node-payload0] PASSED [ 26%]
tests/test_phase7_api_cli.py::test_chaos_injection_payloads[kill_az-payload1] PASSED [ 33%]
tests/test_phase7_api_cli.py::test_chaos_injection_payloads[drop_link-payload2] PASSED [ 40%]
tests/test_phase7_api_cli.py::test_chaos_injection_payloads[latency_spike-payload3] PASSED [ 46%]
tests/test_phase7_api_cli.py::test_chaos_injection_payloads[packet_loss-payload4] PASSED [ 53%]
tests/test_phase7_api_cli.py::test_chaos_injection_payloads[network_partition-payload5] PASSED [ 60%]
tests/test_phase7_api_cli.py::test_chaos_injection_payloads[db_primary_failure-payload6] PASSED [ 66%]
tests/test_phase7_api_cli.py::test_chaos_injection_payloads[recover-payload7] PASSED [ 73%]
tests/test_phase7_api_cli.py::test_frontend_routes_serve_spa PASSED      [ 80%]
tests/test_phase7_api_cli.py::test_get_metrics_endpoint PASSED           [ 86%]
tests/test_phase7_api_cli.py::test_websocket_streaming_and_control PASSED [ 93%]
tests/test_phase7_api_cli.py::test_cli_runner_execution PASSED           [100%]

=============================== warnings summary ===============================
.venv/lib/python3.14/site-packages/fastapi/testclient.py:1
  /home/harshil/STUDY/ChaosNet/.venv/lib/python3.14/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 15 passed, 1 warning in 0.75s =========================
```

## Concerns

- Test suite passes. The only warning is an existing Starlette `TestClient` deprecation warning about `httpx`; no task-specific failures or skips occurred because `Frontend/dist/index.html` is present.

## Follow-up Fix

Updated `/home/harshil/STUDY/ChaosNet/tests/test_phase7_api_cli.py` so the `drop_link` and `packet_loss` parametrized cases each assert that the API normalizes `router-a|router-b` to `router-a->router-b` in `response.json()["event"]["target"]`.

Command run:

```text
pytest tests/test_phase7_api_cli.py -v
```

Exact result:

```text
============================= test session starts ==============================
platform linux -- Python 3.14.4, pytest-9.2.0, pluggy-1.7.0 -- /home/harshil/STUDY/ChaosNet/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /home/harshil/STUDY/ChaosNet
configfile: pyproject.toml
plugins: anyio-4.15.1
collecting ... collected 15 items

tests/test_phase7_api_cli.py::test_get_topology_endpoint PASSED          [  6%]
tests/test_phase7_api_cli.py::test_simulation_step_pause_and_reset_endpoints PASSED [ 13%]
tests/test_phase7_api_cli.py::test_chaos_inject_endpoint PASSED          [ 20%]
tests/test_phase7_api_cli.py::test_chaos_injection_payloads[kill_node-payload0-None] PASSED [ 26%]
tests/test_phase7_api_cli.py::test_chaos_injection_payloads[kill_az-payload1-None] PASSED [ 33%]
tests/test_phase7_api_cli.py::test_chaos_injection_payloads[drop_link-payload2-router-a->router-b] PASSED [ 40%]
tests/test_phase7_api_cli.py::test_chaos_injection_payloads[latency_spike-payload3-None] PASSED [ 46%]
tests/test_phase7_api_cli.py::test_chaos_injection_payloads[packet_loss-payload4-router-a->router-b] PASSED [ 53%]
tests/test_phase7_api_cli.py::test_chaos_injection_payloads[network_partition-payload5-None] PASSED [ 60%]
tests/test_phase7_api_cli.py::test_chaos_injection_payloads[db_primary_failure-payload6-None] PASSED [ 66%]
tests/test_phase7_api_cli.py::test_chaos_injection_payloads[recover-payload7-None] PASSED [ 73%]
tests/test_phase7_api_cli.py::test_frontend_routes_serve_spa PASSED      [ 80%]
tests/test_phase7_api_cli.py::test_get_metrics_endpoint PASSED           [ 86%]
tests/test_phase7_api_cli.py::test_websocket_streaming_and_control PASSED [ 93%]
tests/test_phase7_api_cli.py::test_cli_runner_execution PASSED           [100%]

=============================== warnings summary ===============================
.venv/lib/python3.14/site-packages/fastapi/testclient.py:1
  /home/harshil/STUDY/ChaosNet/.venv/lib/python3.14/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 15 passed, 1 warning in 0.66s =========================
```
