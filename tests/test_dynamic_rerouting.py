"""Test accident rerouting during the actual Road Node transfer operation."""

import unittest
from unittest.mock import patch

from roads.road_node import RoadNode
from roads.vehicle import Vehicle


class DynamicReroutingTests(unittest.TestCase):
    def setUp(self):
        # Small network with two possible routes to D
        self.roads = {
            "A": {"host": "127.0.0.1", "port": 18001, "capacity": 10,
                  "base_travel_ticks": 2, "connections": ["B", "C"]},
            "B": {"host": "127.0.0.1", "port": 18002, "capacity": 10,
                  "base_travel_ticks": 2, "connections": ["D"]},
            "C": {"host": "127.0.0.1", "port": 18003, "capacity": 10,
                  "base_travel_ticks": 3, "connections": ["D"]},
            "D": {"host": "127.0.0.1", "port": 18004, "capacity": 10,
                  "base_travel_ticks": 2, "connections": []},
        }
        self.road_a = RoadNode(
            "A", self.roads["A"], {"host": "127.0.0.1", "port": 18000}, self.roads
        )
        self.road_a.vehicles[1] = Vehicle(1, "A", "D", ["A", "B", "D"])
        self.road_a.vehicles[1].remaining_ticks = 0

    def make_traffic(self, accident=False):
        traffic = {
            name: {"type": "STATUS", "road_id": name,
                   "travel_ticks": info["base_travel_ticks"],
                   "vehicle_count": 0, "capacity": info["capacity"],
                   "accident_active": False}
            for name, info in self.roads.items()
        }
        if accident:
            traffic["B"]["accident_active"] = True
            traffic["B"]["travel_ticks"] = 4
        return traffic

    @patch("roads.road_node.get_live_traffic")
    @patch("roads.road_node.send_request")
    def test_vehicle_changes_next_road_when_accident_occurs(self, send, get_traffic):
        traffic = self.make_traffic(accident=True)
        get_traffic.return_value = traffic
        transferred = []

        def fake_send(host, port, message):
            if message["type"] == "GET_STATUS":
                road = next(name for name, info in self.roads.items()
                            if info["port"] == port)
                return traffic[road]
            if message["type"] == "TRANSFER_VEHICLE":
                transferred.append((port, message["vehicle"]))
                return {"type": "ACCEPTED"}
            raise AssertionError("Unexpected request")

        send.side_effect = fake_send
        self.road_a.attempt_sending_vehicle(1, 3)

        self.assertEqual(len(transferred), 1)
        self.assertEqual(transferred[0][0], self.roads["C"]["port"])
        self.assertEqual(transferred[0][1]["route"], ["A", "C", "D"])
        self.assertEqual(transferred[0][1]["route_index"], 0)
        self.assertNotIn(1, self.road_a.vehicles)

    @patch("roads.road_node.get_live_traffic")
    @patch("roads.road_node.send_request")
    def test_full_road_keeps_route_and_waits(self, send, get_traffic):
        traffic = self.make_traffic()
        traffic["B"]["vehicle_count"] = traffic["B"]["capacity"]
        get_traffic.return_value = traffic
        transferred = []

        def fake_send(host, port, message):
            if message["type"] == "GET_STATUS":
                road = next(name for name, info in self.roads.items()
                            if info["port"] == port)
                return traffic[road]
            if message["type"] == "TRANSFER_VEHICLE":
                transferred.append((port, message["vehicle"]))
                return {"type": "REJECTED_FULL", "road_id": "B"}
            raise AssertionError("Unexpected request")

        send.side_effect = fake_send
        self.road_a.attempt_sending_vehicle(1, 3)

        self.assertEqual(len(transferred), 1)
        self.assertEqual(transferred[0][0], self.roads["B"]["port"])
        self.assertEqual(transferred[0][1]["route"], ["A", "B", "D"])
        self.assertIn(1, self.road_a.vehicles)
        get_traffic.assert_not_called()


if __name__ == "__main__":
    unittest.main()
