"""Additional behavior tests for vehicle movement and road-node handling."""

import unittest
from unittest.mock import patch

from roads.road_node import RoadNode
from roads.vehicle import Vehicle


ROAD_A = {
    "host": "127.0.0.1", "port": 18001, "capacity": 1, "base_travel_ticks": 2, "connections": ["B"],
}
ROAD_B = {
    "host": "127.0.0.1", "port": 18002, "capacity": 1, "base_travel_ticks": 3, "connections": [],
}
ROADS = {"A": ROAD_A, "B": ROAD_B}
COORDINATOR = {"host": "127.0.0.1", "port": 18000}


def make_vehicle(vehicle_id=1, route=None, route_index=0):
    route = route or ["A", "B"]
    return Vehicle(
        vehicle_id, route[0], route[-1], route, route_index=route_index,
    )


class RoadNodeBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.road_a = RoadNode("A", ROAD_A, COORDINATOR, ROADS)
        self.road_b = RoadNode("B", ROAD_B, COORDINATOR, ROADS)

    def test_road_rejects_vehicle_when_at_capacity(self):
        first = self.road_a.spawn_vehicle({"vehicle": make_vehicle(1).to_dictionary(), "tick": 0})
        second = self.road_a.spawn_vehicle({"vehicle": make_vehicle(2).to_dictionary(), "tick": 0})

        self.assertEqual(first["type"], "ACCEPTED")
        self.assertEqual(second["type"], "REJECTED_FULL")
        self.assertEqual(self.road_a.get_status()["vehicle_count"], 1)

    def test_road_rejects_duplicate_vehicle(self):
        vehicle_data = make_vehicle(1).to_dictionary()
        self.road_a.spawn_vehicle({"vehicle": vehicle_data, "tick": 0})

        result = self.road_a.receive_vehicle({"vehicle": vehicle_data, "tick": 1})

        self.assertEqual(result["type"], "ERROR")
        self.assertEqual(self.road_a.get_status()["vehicle_count"], 1)

    def test_received_vehicle_advances_route_index(self):
        result = self.road_b.receive_vehicle({"vehicle": make_vehicle(7).to_dictionary(), "tick": 2})

        self.assertEqual(result["type"], "ACCEPTED")
        received = self.road_b.vehicles[7]
        self.assertEqual(received.route_index, 1)
        self.assertEqual(received.get_current_road(), "B")
        self.assertEqual(received.entry_tick, 2)
        self.assertEqual(received.remaining_ticks, ROAD_B["base_travel_ticks"])

    def test_received_vehicle_is_rejected_when_road_is_full(self):
        self.road_b.spawn_vehicle({"vehicle": make_vehicle(1).to_dictionary(), "tick": 0})

        result = self.road_b.receive_vehicle({"vehicle": make_vehicle(2).to_dictionary(), "tick": 1})

        self.assertEqual(result["type"], "REJECTED_FULL")

    def test_vehicle_does_not_move_on_tick_it_enters_road(self):
        self.road_a.spawn_vehicle({"vehicle": make_vehicle(1).to_dictionary(), "tick": 1})

        self.road_a.handle_tick(1)

        self.assertEqual(self.road_a.vehicles[1].remaining_ticks, 2)

    def test_vehicle_travel_time_decreases_on_later_tick(self):
        self.road_a.spawn_vehicle({"vehicle": make_vehicle(1).to_dictionary(), "tick": 0})

        self.road_a.handle_tick(1)

        self.assertEqual(self.road_a.vehicles[1].remaining_ticks, 1)

    @patch("roads.road_node.send_request")
    def test_vehicle_transfers_to_connected_road(self, send):
        send.return_value = {"type": "ACCEPTED", "road_id": "B"}
        self.road_a.vehicles[1] = make_vehicle(1)
        self.road_a.vehicles[1].remaining_ticks = 0

        self.road_a.attempt_sending_vehicle(1, 1)

        self.assertNotIn(1, self.road_a.vehicles)
        self.assertEqual(send.call_args.args[0], ROAD_B["host"])
        self.assertEqual(send.call_args.args[1], ROAD_B["port"])
        sent_message = send.call_args.args[2]
        self.assertEqual(sent_message["type"], "TRANSFER_VEHICLE")
        self.assertEqual(sent_message["vehicle"]["id"], 1)

    @patch("roads.road_node.send_request")
    def test_vehicle_stays_on_road_when_transfer_is_rejected(self, send):
        send.return_value = {"type": "REJECTED_FULL", "road_id": "B"}
        self.road_a.vehicles[1] = make_vehicle(1)
        self.road_a.vehicles[1].remaining_ticks = 0

        self.road_a.attempt_sending_vehicle(1, 1)

        self.assertIn(1, self.road_a.vehicles)

    @patch("roads.road_node.send_request")
    def test_vehicle_is_removed_after_coordinator_acknowledges_completion(self, send):
        send.return_value = {"type": "ACKNOWLEDGE"}
        vehicle = make_vehicle(1)
        vehicle.advance_route()
        self.road_b.vehicles[1] = vehicle
        vehicle.remaining_ticks = 0

        self.road_b.attempt_sending_vehicle(1, 3)

        self.assertNotIn(1, self.road_b.vehicles)
        self.assertEqual(send.call_args.args[2]["type"], "VEHICLE_COMPLETED")

    @patch("roads.road_node.send_request")
    def test_vehicle_is_kept_until_completion_is_acknowledged(self, send):
        send.return_value = {"type": "ERROR", "message": "unknown vehicle"}
        vehicle = make_vehicle(1)
        vehicle.advance_route()
        self.road_b.vehicles[1] = vehicle

        self.road_b.attempt_sending_vehicle(1, 3)

        self.assertIn(1, self.road_b.vehicles)

    def test_vehicle_cannot_transfer_to_unconnected_road(self):
        self.road_a.vehicles[1] = Vehicle(1, "A", "C", ["A", "C"])
        with self.assertRaises(ValueError):
            self.road_a.attempt_sending_vehicle(1, 1)

    def test_invalid_tick_values_are_rejected(self):
        for invalid_tick in (0, -1, 1.5, True, "1", None):
            with self.subTest(tick=invalid_tick):
                self.assertEqual(self.road_a.request_tick(invalid_tick)["type"], "ERROR")

    def test_invalid_transfer_tick_is_rejected(self):
        for invalid_tick in (-1, 1.5, True, "1", None):
            with self.subTest(tick=invalid_tick):
                result = self.road_b.receive_vehicle({"vehicle": make_vehicle(5).to_dictionary(),"tick": invalid_tick, })
                self.assertEqual(result["type"], "ERROR")

    def test_unknown_message_type_is_rejected(self):
        result = self.road_a.handle_message({"type": "NOT_A_REAL_COMMAND"})
        self.assertEqual(result["type"], "ERROR")

    def test_non_dictionary_message_is_rejected(self):
        self.assertEqual(self.road_a.handle_message(None)["type"], "ERROR")


if __name__ == "__main__":
    unittest.main()
