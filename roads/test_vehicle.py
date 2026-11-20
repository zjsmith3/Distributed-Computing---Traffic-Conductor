"""Small standalone compatibility test for the Vehicle model."""

import unittest

try:
    from roads.vehicle import Vehicle
except ModuleNotFoundError:
    from vehicle import Vehicle


class VehicleModelTests(unittest.TestCase):
    def test_json_style_dictionary_round_trip(self):
        vehicle = Vehicle(11037, "A", "C", ["A", "B", "C"])
        restored = Vehicle.from_dictionary(vehicle.to_dictionary())
        self.assertEqual(restored.vehicle_id, 11037)
        self.assertEqual(restored.get_current_road(), "A")


if __name__ == "__main__":
    unittest.main()
