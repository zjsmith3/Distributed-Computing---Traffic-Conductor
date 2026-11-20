# Coordinator API notes

Messages use the same TCP/JSON framing already used by the project. Send one
JSON object followed by a newline and read one JSON response followed by a
newline.

## Tick control

| Request | Successful response | Purpose |
|---|---|---|
| `ADVANCE_TICK` | `TICK_STARTED` | Start the next global tick asynchronously |
| `RETRY_TICK` | `TICK_STARTED` | Resume the currently incomplete tick |
| `PLAY` | `PLAYING` | Start automatic ticking |
| `PAUSE` | `PAUSED` | Stop automatic ticking after the current operation |
| `SET_TICK_SPEED` with `interval` | `SPEED_UPDATED` | Set automatic tick delay to 0.1–10 seconds |

A direct call to `Coordinator.run_tick()` returns a result dictionary with a
`status` of `completed`, `waiting`, `road_unavailable`, or `busy`. A failed tick
is not skipped: fix the relevant node and call `run_tick()` again, or send
`RETRY_TICK`. The Coordinator retains the same global tick number until every
road has confirmed completion.

## Monitoring

`GET_SIMULATION_INFO` returns the global tick, vehicle totals, active/completed
vehicle counts, auto-run state, accepted/completed/pending roads, and failed
road details.

`GET_ROAD_STATUS` queries each configured Road Node. Its `roads` object contains
one entry per road with `reachable` plus the Road Node's status fields. An
optional `road_id` limits the query to one node. `online_roads` and
`offline_roads` make it easy for a UI to show a compact health summary.

## Road Node tick fields

`GET_STATUS` returns:

- `current_tick`: most recently accepted global tick.
- `completed_tick`: most recently completed tick operation.
- `tick_in_progress`: whether vehicle processing is still running.
- `last_tick_error`: an execution error for the current/most recent tick, if any.
- `last_notification_error`: an error sending the completion acknowledgement, if any.

A Road Node treats a duplicate `TICK` for the active tick as an acknowledgement,
not as permission to execute the tick again. A duplicate for a completed tick
returns `TICK_COMPLETED`.

## Recovery boundary

A transient connection problem can be recovered when the Road Node process is
still running and its in-memory tick state is intact. A Road Node execution
error is surfaced instead of replayed: a failed handler may already have
transferred some vehicles, so blindly running that tick again could duplicate
work. Restarting a Road Node also resets its in-memory vehicles and tick history;
this version does not persist simulation state to disk.
