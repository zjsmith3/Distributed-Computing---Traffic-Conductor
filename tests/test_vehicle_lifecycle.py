"""Isolated tests for the Coordinator's vehicle spawn/completion lifecycle.

These tests deliberately mock the network. They do not require a Coordinator
or Road Node process to be running on fixed local ports.
"""

import unittest
from unittest.mock import patch

from coordinator.coordinator import Coordinator


NETWORK = {
    "coordinator": {"host": "127.0.0.1", "port": 17000},
    "roads": {
        "A": {"host": "127.0.0.1", "port": 17001, "capacity": 5, "base_travel_ticks": 2, "connections": ["B"]},
        "B": {"host": "127.0.0.1", "port": 17002, "capacity": 5, "base_travel_ticks": 2, "connections": []},
    },
}


class VehicleLifecycleTests(unittest.TestCase):
    def test_spawn_and_complete_vehicle(self):
        coordinator = Coordinator(network=NETWORK)
        coordinator.maintain_vehicle_population = lambda: None
        vehicle = {
            "origin": "A", "destination": "B", "route": ["A", "B"],
            "route_index": 0, "remaining_ticks": 0, "created_tick": 0, "entry_tick": -1,
        }

        with patch("coordinator.coordinator.send_request", return_value={"type": "ACCEPTED", "road_id": "A"}):
            spawned = coordinator.spawn_vehicle({"road_id": "A", "vehicle": vehicle})

        self.assertEqual(spawned["type"], "ACCEPTED")
        vehicle_id = spawned["vehicle_id"]
        self.assertIn(vehicle_id, coordinator.spawned_vehicle_ids)

        first = coordinator.handle_vehicle_completed({"vehicle_id": vehicle_id})
        duplicate = coordinator.handle_vehicle_completed({"vehicle_id": vehicle_id})
        self.assertFalse(first["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(coordinator.get_simulation_info()["active_vehicles"], 0)


if __name__ == "__main__":
    unittest.main()
