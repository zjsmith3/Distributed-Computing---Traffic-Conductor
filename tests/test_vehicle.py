import unittest
from roads.vehicle import Vehicle

class TestVehicle(unittest.TestCase): 
    def make_vehicle(self, **kwargs):
        values = dict(vehicle_id = 1, origin = "A", destination = "C", route = ["A", "B", "C" ], created_tick = 2)
        values.update(kwargs)
        return Vehicle(**values)

    def test_initial_state(self):
        vehicle = self.make_vehicle()
        self.assertEqual(vehicle.vehicle_id, 1)
        self.assertEqual(vehicle.get_current_road(), "A")
        self.assertEqual(vehicle.get_next_road(), "B")
        self.assertEqual(vehicle.route_index, 0)

    def test_advance_route_moves_one_road(self):
        vehicle = self.make_vehicle()
        self.assertTrue(vehicle.advance_route())
        self.assertEqual(vehicle.route_index, 1)
        self.assertEqual(vehicle.get_current_road(), "B")
        self.assertEqual(vehicle.get_next_road(), "C")

    def test_advance_route_stops_at_destination(self):
        vehicle = self.make_vehicle(route_index=2)
        self.assertIsNone(vehicle.get_next_road())
        self.assertFalse(vehicle.advance_route())
        self.assertEqual(vehicle.route_index, 2)

    def test_serialization_round_trip(self): 
        vehicle = self.make_vehicle(remaining_ticks = 4, entry_tick = 3, route_index = 1)
        restored = Vehicle.from_dictionary(vehicle.to_dictionary())
        self.assertEqual(restored.to_dictionary(), vehicle.to_dictionary())

    def test_to_dictionary_uses_id_key(self):
        self.assertIn("id", self.make_vehicle().to_dictionary())

    def test_string_contains_vehicle_and_location(self):
        self.assertIn("Vehicle 1", str(self.make_vehicle()))
        self.assertIn("A going to C", str(self.make_vehicle()))

    def test_rejects_invalid_values(self):
            invalid = [
                {"vehicle_id": -1},
                {"origin": ""},
                {"route": []},
                {"route": ["B", "C"]},
                {"route": ["A", "B"]},
                {"route_index": 3},
                {"remaining_ticks": -1},
                {"created_tick": -1},
                {"entry_tick": -2},
            ]
            for change in invalid:
                with self.subTest(change=change):
                    with self.assertRaises(ValueError):
                        self.make_vehicle(**change)

    if __name__ == "__main__":
        unittest.main()