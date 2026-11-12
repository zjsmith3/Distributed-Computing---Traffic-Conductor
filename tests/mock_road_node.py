"""A lightweight TCP Road Node used to test Coordinator tick synchronization.

Run one copy per terminal:
    python tests/mock_road_node.py A
    python tests/mock_road_node.py B
    python tests/mock_road_node.py C
"""

import sys
import threading
import time
from pathlib import Path

# Make imports work when this file is launched directly from the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from communication.protocol import send_request
from communication.server import start_server
from config.config import load_network_file


class MockRoadNode:
    def __init__(self, road_id, road_config, coordinator_config):
        self.road_id = road_id
        self.host = road_config["host"]
        self.port = road_config["port"]
        self.coordinator_host = coordinator_config["host"]
        self.coordinator_port = coordinator_config["port"]
        self.current_tick = 0
        self.lock = threading.Lock()

    def handle_message(self, message):
        if not isinstance(message, dict) or message.get("type") != "TICK":
            return {"type": "ERROR", "message": "Expected a TICK message."}

        tick = message.get("tick")
        with self.lock:
            if tick != self.current_tick + 1:
                return {
                    "type": "ERROR",
                    "message": f"Expected tick {self.current_tick + 1}.",
                }
            self.current_tick = tick

        # Simulate the Road Node accepting the tick and processing it separately.
        worker = threading.Thread(
            target=self.finish_tick,
            args=(tick,),
            daemon=True,
        )
        worker.start()

        return {"type": "TICK_RECEIVED", "road_id": self.road_id, "tick": tick}

    def finish_tick(self, tick):
        time.sleep(0.5)
        try:
            response = send_request(
                self.coordinator_host,
                self.coordinator_port,
                {"type": "TICK_DONE", "road_id": self.road_id, "tick": tick},
            )
            print(
                f"Road {self.road_id} completed Tick {tick}: "
                f"{response.get('type', 'UNKNOWN')}"
            )
        except (OSError, TimeoutError, ConnectionError, ValueError) as error:
            print(f"Road {self.road_id} could not contact Coordinator: {error}")


def main():
    if len(sys.argv) != 2:
        print("Usage: python tests/mock_road_node.py A")
        raise SystemExit(1)

    network = load_network_file()
    road_id = sys.argv[1].upper()
    roads = network["roads"]

    if road_id not in roads:
        print(f"Road {road_id} does not exist in config/network.json.")
        raise SystemExit(1)

    road = MockRoadNode(road_id, roads[road_id], network["coordinator"])
    print(f"Mock Road {road_id} started on port {road.port}")
    start_server(road.host, road.port, road.handle_message)


if __name__ == "__main__":
    main()
