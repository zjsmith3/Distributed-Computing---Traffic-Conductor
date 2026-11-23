import unittest
from unittest.mock import patch
from roads.road_node import RoadNode
from roads.vehicle import Vehicle

class TestRoadNode(unittest.TestCase): 
    def setUp(self):
        self.road_configs = {
            "A": {"host": "127.0.0.1", "port": 5001, "capacity": 2, "base_travel_ticks": 3, "connections": ["B"]},
            "B": {"host": "127.0.0.1", "port": 5002, "capacity": 1, "base_travel_ticks": 4, "connections": []},
        }
        self.node = RoadNode("B", self.road_configs["B"], {"host": "127.0.0.1", "port": 5000}, self.road_configs)

    def vehicle_data(self, vehicle_id = 1, route = None, route_index = 0):
        route = route or ["A", "B"]
        return Vehicle(vehicle_id, route[0], route[-1], route, route_index = route_index).to_dictionary()

    def test_initial_status(self):
        status = self.node.get_status()
        self.assertEqual(status["type"], "STATUS")
        self.assertEqual(status["road_id"], "B")
        self.assertEqual(status["vehicle_count"], 0)
        self.assertEqual(status["travel_ticks"], 4)

    def test_spawn_vehicle_accepts_vehicle_and_sets_travel_time(self):
        response = self.node.spawn_vehicle({"vehicle": self.vehicle_data(), "tick": 5})
        self.assertEqual(response["type"], "ACCEPTED")
        vehicle = self.node.vehicles[1]
        self.assertEqual(vehicle.get_current_road(), "A")
        self.assertEqual(vehicle.entry_tick, 5)
        self.assertEqual(vehicle.remaining_ticks, 4)

    def test_receive_vehicle_advances_route(self): 
        response = self.node.receive_vehicle({"vehicle": self.vehicle_data(), "tick": 7})
        self.assertEqual(response["type"], "ACCEPTED")
        vehicle = self.node.vehicles[1]
        self.assertEqual(vehicle.get_current_road(), "B")
        self.assertEqual(vehicle.route_index, 1)
        self.assertEqual(vehicle.entry_tick, 7)

    def test_capacity_rejects_additional_vehicle(self):
        self.node.spawn_vehicle({"vehicle": self.vehicle_data(), "tick": 0})
        response = self.node.spawn_vehicle({"vehicle": self.vehicle_data(), "tick": 1})
        self.assertEqual(response["type"], "ERROR")
        self.assertEqual(len(self.node.vehicles), 1)

    def test_duplicate_vehicle_is_rejected(self):
        self.node.spawn_vehicle({"vehicle": self.vehicle_data(), "tick": 0})
        response = self.node.spawn_vehicle({"vehicle": self.vehicle_data(), "tick": 1})
        self.assertEqual(response["type"], "ERROR")
        self.assertEqual(len(self.node.vehicles), 1)

    def test_accident_doubles_travel_time(self): 
        response = self.node.set_accident({"active": True})
        self.assertEqual(response["type"], "ACCIDENT_UPDATED")
        self.assertEqual(self.node.get_travel_ticks(), 8)
        self.node.set_accident({"active": False})
        self.assertEqual(self.node.get_travel_ticks(), 4)

    def test_message_dispatch(self):
        self.assertEqual(self.node.handle_message({"type": "GET_STATUS"})["type"], "STATUS")
        self.assertEqual(self.node.handle_message({"type": "UNKOWN"})["type"], "ERROR")

    def test_tick_rejects_out_of_order_tick(self):
        response = self.node.handle_message({"type": "TICK", "tick": 2})
        self.assertEqual(response["type"], "ERROR")
        self.assertEqual(self.node.current_tick, 0)

    @patch("roads.road_node.send_request")
    def test_completed_vehicle_removed_after_coordinator_ack(self, send_request):
        vehicle = Vehicle(3, "B", "B", ["B"], route_index = 0)
        self.node.vehicles[3] = vehicle
        send_request.return_value = {"type": "ACKNOWLEDGE"}
        self.node.attempt_sending_vehicle(3, 10)
        self.assertNotIn(3, self.node.vehicles)
        self.assertEqual(send_request.call_args.args[2]["type"], "VEHICLE_COMPLETED")

    @patch("roads.road_node.send_request")
    def test_vehicle_transfer_removed_only_when_accepted(self, send_request):
        source = RoadNode("A", self.road_configs["A"], {"host": "127.0.0.1", "port": 5000}, self.road_configs)
        vehicle = Vehicle(4, "A", "B", ["A", "B"])
        source.vehicles[4] = vehicle
        send_request.return_value = {"type": "ACCEPTED"}
        source.attempt_sending_vehicle(4,2)
        self.assertNotIn(4, source.vehicles)

    @patch("roads.road_node.send_request")
    def test_vehicle_kept_when_transfer_is_rejected(self, send_request):
        source = RoadNode("A", self.road_configs["A"], {"host": "127.0.0.1", "port": 5000}, self.road_configs)
        source.vehicles[5] = Vehicle(5, "A", "B", ["A", "B"])
        send_request.return_value = {"type": "REJECTED_FULL"}
        source.attempt_sending_vehicle(5,2)
        self.assertIn(5, source.vehicles)

if __name__ == "__main__":
    unittest.main()
