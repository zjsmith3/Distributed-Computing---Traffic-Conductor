"""Tests for the team's Dijkstra routing module.

Run from the project root:
    python -m unittest discover -s tests -p "test_routing.py" -v

These tests do not require any Road Node servers to be running.
"""

import unittest
from unittest.mock import patch

from config.config import load_network_file
from user.routing import (
    calculate_travel_time,
    find_best_route,
    get_live_traffic,
    reroute_for_accident,
)


class TestRouting(unittest.TestCase):
    def setUp(self):
        # Use the real 30-road configuration from config/network.json.
        self.roads = load_network_file()["roads"]

    def make_traffic(self):
        # Fake live status for every road, initially empty and without accidents.
        return {
            road_id: {
                "type": "STATUS",
                "road_id": road_id,
                "travel_ticks": info["base_travel_ticks"],
                "vehicle_count": 0,
                "capacity": info["capacity"],
            }
            for road_id, info in self.roads.items()
        }

    def test_network_has_30_roads(self):
        self.assertEqual(len(self.roads), 30)

    def test_shortest_route(self):
        self.assertEqual(
            find_best_route("R01", "R08", self.roads),
            (["R01", "R06", "R08"], 7.0),
        )

    def test_route_across_30_road_network(self):
        route, time = find_best_route("R01", "R30", self.roads)
        self.assertEqual(route, ["R01", "R06", "R11", "R16", "R21", "R26", "R28", "R30"])
        self.assertEqual(time, 19.0)

    def test_invalid_and_unreachable_destinations(self):
        self.assertIsNone(find_best_route("R01", "R99", self.roads))
        self.assertIsNone(find_best_route("R99", "R01", self.roads))
        self.assertIsNone(find_best_route("R30", "R01", self.roads))

    def test_accident_changes_route(self):
        traffic = self.make_traffic()
        self.assertEqual(
            find_best_route("R01", "R08", self.roads, traffic),
            (["R01", "R06", "R08"], 7.0),
        )

        # Simulate R06's accident doubling its travel time from 2 to 4 ticks.
        traffic["R06"]["travel_ticks"] = 4
        self.assertEqual(
            find_best_route("R01", "R08", self.roads, traffic),
            (["R01", "R03", "R08"], 8.0),
        )

    def test_missing_live_status_is_avoided(self):
        # Missing data means we do not know whether that road is available.
        traffic = self.make_traffic()
        del traffic["R06"]
        self.assertEqual(
            find_best_route("R01", "R08", self.roads, traffic),
            (["R01", "R03", "R08"], 8.0),
        )
        self.assertIsNone(find_best_route("R01", "R08", self.roads, {}))

    def test_congestion_changes_route(self):
        # Small controlled network to isolate congestion from the 30-road layout.
        roads = {
            "A": {"base_travel_ticks": 1, "capacity": 10, "connections": ["B", "C"]},
            "B": {"base_travel_ticks": 2, "capacity": 10, "connections": ["D"]},
            "C": {"base_travel_ticks": 2.1, "capacity": 10, "connections": ["D"]},
            "D": {"base_travel_ticks": 1, "capacity": 10, "connections": []},
        }
        traffic = {
            road_id: {
                "travel_ticks": info["base_travel_ticks"],
                "vehicle_count": 0,
                "capacity": info["capacity"],
            }
            for road_id, info in roads.items()
        }
        self.assertEqual(find_best_route("A", "D", roads, traffic)[0], ["A", "B", "D"])

        # A full B has a 15% BPR cost increase, making the C route cheaper.
        traffic["B"]["vehicle_count"] = 10
        self.assertEqual(find_best_route("A", "D", roads, traffic)[0], ["A", "C", "D"])

    def test_bpr_calculation(self):
        self.assertEqual(calculate_travel_time(2, 0, 6), 2.0)
        self.assertAlmostEqual(calculate_travel_time(2, 6, 6), 2.3)
        self.assertEqual(calculate_travel_time(2, 3, 0), float("inf"))

    def test_reroute_only_for_accident(self):
        traffic = self.make_traffic()
        original = ["R01", "R06", "R08"]

        # With no accident, do not reroute.
        self.assertEqual(
            reroute_for_accident(original, 0, self.roads, traffic), original
        )

        # Accident on R06 makes R03 the faster path.
        traffic["R06"]["travel_ticks"] = 4
        traffic["R06"]["accident_active"] = True
        self.assertEqual(
            reroute_for_accident(original, 0, self.roads, traffic),
            ["R01", "R03", "R08"],
        )

        # Clearing the accident stops further accident-based rerouting.
        traffic["R06"]["travel_ticks"] = 2
        traffic["R06"]["accident_active"] = False
        self.assertEqual(
            reroute_for_accident(original, 0, self.roads, traffic), original
        )

    def test_reroute_preserves_visited_roads(self):
        traffic = self.make_traffic()
        route = ["R01", "R06", "R07", "R12"]
        traffic["R07"]["accident_active"] = True
        traffic["R07"]["travel_ticks"] = 10
        updated = reroute_for_accident(route, 1, self.roads, traffic)
        self.assertEqual(updated[0:2], ["R01", "R06"])
        self.assertEqual(updated[-1], "R12")
        self.assertNotIn("R07", updated[2:])

    def test_full_road_is_not_automatically_blocked(self):
        traffic = self.make_traffic()
        original = ["R01", "R06", "R08"]
        traffic["R06"]["vehicle_count"] = traffic["R06"]["capacity"]
        self.assertEqual(
            reroute_for_accident(original, 0, self.roads, traffic), original
        )

    @patch("user.routing.send_request")
    def test_get_live_traffic_skips_offline_road(self, mock_request):
        # A real TCP server is not needed: patch the network request function.
        def fake_request(host, port, message):
            self.assertEqual(message, {"type": "GET_STATUS"})
            if port == 5002:
                raise ConnectionError("Road offline")
            return {"type": "STATUS", "road_id": "R01", "travel_ticks": 2,
                    "vehicle_count": 0, "capacity": 6}

        mock_request.side_effect = fake_request
        roads = {road: self.roads[road] for road in ("R01", "R02")}
        result = get_live_traffic(roads)
        self.assertIn("R01", result)
        self.assertNotIn("R02", result)
        self.assertEqual(mock_request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
