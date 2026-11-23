# Traffic Conductor

Traffic Conductor is a Python distributed-computing simulation. A Coordinator
controls the global simulation tick, while each Road Node manages the vehicles
currently on its own road. Nodes communicate over TCP using newline-delimited
JSON messages.

## Requirements

- Python 3.10 or newer
- Windows Terminal (only needed for the `start_simulation.py` convenience script)
- No third-party Python packages are required for the simulation or tests

## Run the project

Open a terminal in the repository's top-level folder. Start all nodes using
Windows Terminal:

```powershell
python start_simulation.py
```

You can also start the processes in separate terminals:

```powershell
python -m coordinator.coordinator
python run_road.py A
python run_road.py B
python run_road.py C
```

Start the UI in another terminal:

```powershell
python main.py
```

The current UI is still a visual demonstration; its Play/Pause controls animate
local demo data rather than controlling the live Coordinator. The Coordinator
network API can be exercised independently while the UI integration is being
worked on.

## Run the automated tests

From the repository root:

```powershell
python -m unittest discover -s tests -v
```

The tests mock TCP requests, so they do not need live services or reserved local
ports. The old live-network vehicle test has been converted to an isolated test.

## Useful Coordinator messages

Every request is a JSON object with a `type` field. Examples:

- `{"type":"GET_SIMULATION_INFO"}` — simulation counters and tick state.
- `{"type":"GET_ROAD_STATUS"}` — query all Road Nodes; add `"road_id":"A"` to query one road.
- `{"type":"ADVANCE_TICK"}` — start a new tick in the background.
- `{"type":"RETRY_TICK"}` — retry/reconcile an incomplete tick without incrementing the global tick.
- `{"type":"PLAY"}` and `{"type":"PAUSE"}` — start or stop automatic ticking.
- `{"type":"SET_TICK_SPEED","interval":1.0}` — set the delay between automatic ticks (0.1–10 seconds).
- `{"type":"SET_ACCIDENT","road_id":"A","active":true}` — update a road's accident state.

## Tick recovery

The Coordinator records which roads accepted and completed the active tick. If a
TCP reply is missing, it first asks the Road Node for `GET_STATUS`. It only sends
the tick again when the node confirms that it is still on the previous tick.
Road Nodes report `current_tick`, `completed_tick`, and whether a tick is still
running. That lets the Coordinator recognize a completed tick even when the
`TICK_DONE` acknowledgement was lost. It will not start the next tick until all
roads have completed the current one.

The automatic route generator remains temporary. It is used to keep the current
simulation usable until the User Node routing module is implemented.

A Road Node execution error is reported rather than replayed automatically,
because some vehicle transfers may already have happened before the error. A
Road Node process restart also clears its in-memory vehicles and tick history;
this Coordinator change does not add durable state storage. In either case, the
status response makes the problem visible, but the simulation may need a clean
restart rather than an automatic retry.
