import unittest

from roads.road_node import RoadNode


ROAD_CONFIG = {"host": "127.0.0.1", "port": 16001, "capacity": 4, "base_travel_ticks": 3, "connections": ["B"]}
COORDINATOR_CONFIG = {"host": "127.0.0.1", "port": 16000}
ROAD_CONFIGS = {
    "A": ROAD_CONFIG,
    "B": {"host": "127.0.0.1", "port": 16002, "capacity": 4, "base_travel_ticks": 2, "connections": []},
}


class RoadNodeTests(unittest.TestCase):
    def setUp(self):
        self.road = RoadNode("A", ROAD_CONFIG, COORDINATOR_CONFIG, ROAD_CONFIGS)

    def test_status_includes_tick_recovery_fields(self):
        result = self.road.get_status()
        self.assertEqual(result["current_tick"], 0)
        self.assertEqual(result["completed_tick"], 0)
        self.assertFalse(result["tick_in_progress"])
        self.assertIsNone(result["last_tick_error"])

    def test_duplicate_request_does_not_start_a_second_tick(self):
        self.road.current_tick = 1
        self.road.tick_in_progress = True
        result = self.road.request_tick(1)
        self.assertEqual(result["type"], "TICK_RECEIVED")
        self.assertTrue(result["duplicate"])

    def test_completed_duplicate_returns_completed_response(self):
        self.road.current_tick = 1
        self.road.completed_tick = 1
        result = self.road.request_tick(1)
        self.assertEqual(result["type"], "TICK_COMPLETED")

    def test_out_of_order_tick_is_rejected(self):
        result = self.road.request_tick(2)
        self.assertEqual(result["type"], "ERROR")

    def test_failed_tick_is_not_silently_replayed(self):
        self.road.current_tick = 1
        self.road.last_tick_error = "test failure"
        result = self.road.request_tick(1)
        self.assertEqual(result["type"], "ERROR")

    def test_accident_changes_travel_time(self):
        self.assertEqual(self.road.get_travel_ticks(), 3)
        result = self.road.set_accident({"active": True})
        self.assertEqual(result["type"], "ACCIDENT_UPDATED")
        self.assertEqual(self.road.get_travel_ticks(), 6)

    def test_invalid_accident_value_is_rejected(self):
        self.assertEqual(self.road.set_accident({"active": "yes"})["type"], "ERROR")

    def test_malformed_vehicle_message_returns_error(self):
        self.assertEqual(self.road.spawn_vehicle({"vehicle": {}, "tick": 0})["type"], "ERROR")


if __name__ == "__main__":
    unittest.main()
