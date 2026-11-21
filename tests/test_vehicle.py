import unittest

from roads.vehicle import Vehicle


class VehicleTests(unittest.TestCase):
    def make_vehicle(self):
        return Vehicle(12, "A", "C", ["A", "B", "C"])

    def test_current_and_next_road(self):
        vehicle = self.make_vehicle()
        self.assertEqual(vehicle.get_current_road(), "A")
        self.assertEqual(vehicle.get_next_road(), "B")

    def test_advance_route(self):
        vehicle = self.make_vehicle()
        self.assertTrue(vehicle.advance_route())
        self.assertEqual(vehicle.get_current_road(), "B")

    def test_destination_has_no_next_road(self):
        vehicle = Vehicle(13, "A", "B", ["A", "B"], route_index=1)
        self.assertIsNone(vehicle.get_next_road())
        self.assertFalse(vehicle.advance_route())

    def test_dictionary_round_trip_uses_main_branch_id_field(self):
        vehicle = self.make_vehicle()
        restored = Vehicle.from_dictionary(vehicle.to_dictionary())
        self.assertEqual(restored.vehicle_id, 12)
        self.assertEqual(restored.route, ["A", "B", "C"])

    def test_negative_identifier_is_rejected(self):
        with self.assertRaises(ValueError):
            Vehicle(-1, "A", "B", ["A", "B"])


if __name__ == "__main__":
    unittest.main()
