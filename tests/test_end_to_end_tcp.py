"""A small real-TCP test covering Coordinator and Road Node tick sync."""

import socket
import socketserver
import threading
import unittest

from communication.server import handle_connection
from communication.protocol import send_request
from coordinator.coordinator import Coordinator
from roads.road_node import RoadNode


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class NodeServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, message_handler):
        self.message_handler = message_handler
        super().__init__(address, NodeRequestHandler)


class NodeRequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        handle_connection(self.request, self.server.message_handler)


class TcpIntegrationTests(unittest.TestCase):
    def setUp(self):
        coordinator_port = free_port()
        road_a_port = free_port()
        road_b_port = free_port()
        self.network = {
            "coordinator": {"host": "127.0.0.1", "port": coordinator_port},
            "roads": {
                "A": {"host": "127.0.0.1", "port": road_a_port, "capacity": 5, "base_travel_ticks": 2, "connections": ["B"]},
                "B": {"host": "127.0.0.1", "port": road_b_port, "capacity": 5, "base_travel_ticks": 2, "connections": []},
            },
        }
        self.coordinator = Coordinator(network=self.network)
        self.coordinator.maintain_vehicle_population = lambda: None
        self.roads = {
            road_id: RoadNode(road_id, config, self.network["coordinator"], self.network["roads"])
            for road_id, config in self.network["roads"].items()
        }
        self.servers = [NodeServer(("127.0.0.1", coordinator_port), self.coordinator.handle_message)]
        self.servers.extend(
            NodeServer(("127.0.0.1", config["port"]), self.roads[road_id].handle_message)
            for road_id, config in self.network["roads"].items()
        )
        self.threads = []
        for server in self.servers:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.threads.append(thread)

    def tearDown(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=1)

    def test_real_tcp_tick_finishes_on_every_road(self):
        result = self.coordinator.run_tick(timeout=2)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["tick"], 1)
        self.assertEqual(result["completed_roads"], ["A", "B"])

        duplicate = send_request(
            "127.0.0.1", self.network["roads"]["A"]["port"],
            {"type": "TICK", "tick": 1},
        )
        self.assertEqual(duplicate["type"], "TICK_COMPLETED")

    def test_status_query_reaches_both_road_nodes(self):
        result = self.coordinator.get_road_status()
        self.assertEqual(result["online_roads"], ["A", "B"])
        self.assertFalse(result["offline_roads"])
        self.assertEqual(result["roads"]["A"]["current_tick"], 0)

    def test_vehicle_moves_across_roads_and_completes(self):
        vehicle = {
            "origin": "A", "destination": "B", "route": ["A", "B"],
            "route_index": 0, "remaining_ticks": 0, "created_tick": 0, "entry_tick": -1,
        }
        spawned = self.coordinator.spawn_vehicle({"road_id": "A", "vehicle": vehicle})
        self.assertEqual(spawned["type"], "ACCEPTED")
        vehicle_id = spawned["vehicle_id"]

        for _ in range(4):
            result = self.coordinator.run_tick(timeout=2)
            self.assertTrue(result["success"], result)

        self.assertIn(vehicle_id, self.coordinator.completed_vehicles)
        self.assertEqual(self.roads["A"].get_status()["vehicle_count"], 0)
        self.assertEqual(self.roads["B"].get_status()["vehicle_count"], 0)


if __name__ == "__main__":
    unittest.main()
