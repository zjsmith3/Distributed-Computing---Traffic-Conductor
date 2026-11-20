# Pull request: Improve Coordinator reliability and road monitoring

## Summary

This change strengthens the Coordinator/Road Node interaction without changing
the existing integer vehicle ID format or the project's TCP/JSON message style.

## What changed

- Track tick acceptance separately from tick completion.
- Recover from uncertain TCP replies by checking `GET_STATUS` before resending a tick.
- Add an explicit `RETRY_TICK` message and keep the same global tick active until all roads finish.
- Add `TICK_FAILED` reporting and Road Node status fields for accepted, running, and completed ticks.
- Make duplicate Road Node tick requests idempotent so they do not process vehicle movement twice.
- Add `GET_ROAD_STATUS` for per-road reachability and live status.
- Expand simulation statistics for active vehicles and tick synchronization.
- Harden the shared TCP server so malformed requests or handler errors do not terminate a client thread without a response.
- Replace fixed-port lifecycle tests with isolated mocked tests and add Coordinator/Road Node/Vehicle coverage.
- Add setup, test, API, and recovery documentation plus a GitHub Actions test workflow.

## Validation

Run `python -m unittest discover -s tests -v` from the repository root.

All tests use mocked network calls, so no background Coordinator/Road Node
processes need to be running during the test suite.

## Scope note

The current Tkinter UI is still a local visual demo, and `user/routing.py` plus
`user/user_node.py` remain separate work. This PR adds the Coordinator API that
those parts can use; it does not claim that the UI is already connected to the
live simulation.
