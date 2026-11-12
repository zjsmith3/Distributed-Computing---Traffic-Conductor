import json
import unittest

from roads.vehicle import Vehicle


class VehicleTests(unittest.TestCase):
    def make_vehicle(self):
        return Vehicle(
            vehicle_id="vehicle-1",
            origin="A",
            destination="C",
            route=["A", "B", "C"],
            created_tick=0,
        )

    def test_get_next_road_returns_the_next_route_entry(self):
        vehicle = self.make_vehicle()
        self.assertEqual(vehicle.get_current_road(), "A")
        self.assertEqual(vehicle.get_next_road(), "B")

    def test_advance_route_moves_to_the_next_road(self):
        vehicle = self.make_vehicle()
        self.assertTrue(vehicle.advance_route())
        self.assertEqual(vehicle.get_current_road(), "B")
        self.assertEqual(vehicle.get_next_road(), "C")

    def test_vehicle_at_destination_has_no_next_road(self):
        vehicle = self.make_vehicle()
        vehicle.advance_route()
        vehicle.advance_route()
        self.assertEqual(vehicle.get_current_road(), "C")
        self.assertIsNone(vehicle.get_next_road())
        self.assertFalse(vehicle.advance_route())

    def test_dictionary_round_trip_preserves_vehicle_state(self):
        vehicle = self.make_vehicle()
        vehicle.advance_route()
        vehicle.entry_tick = 3
        vehicle.remaining_ticks = 2

        restored = Vehicle.from_dictionary(vehicle.to_dictionary())
        self.assertEqual(restored.vehicle_id, "vehicle-1")
        self.assertEqual(restored.id, "vehicle-1")
        self.assertEqual(restored.route, ["A", "B", "C"])
        self.assertEqual(restored.route_index, 1)
        self.assertEqual(restored.entry_tick, 3)
        self.assertEqual(restored.remaining_ticks, 2)
        self.assertEqual(restored.get_next_road(), "C")

    def test_legacy_id_key_is_supported(self):
        data = {
            "id": 25,
            "origin": "A",
            "destination": "B",
            "route": ["A", "B"],
        }
        vehicle = Vehicle.from_dictionary(data)
        self.assertEqual(vehicle.vehicle_id, 25)

    def test_invalid_route_origin_is_rejected(self):
        with self.assertRaises(ValueError):
            Vehicle("V1", "A", "C", ["B", "C"])

    def test_invalid_route_destination_is_rejected(self):
        with self.assertRaises(ValueError):
            Vehicle("V1", "A", "C", ["A", "B"])

    def test_invalid_route_index_is_rejected(self):
        with self.assertRaises(ValueError):
            Vehicle("V1", "A", "B", ["A", "B"], route_index=2)


    def test_dictionary_is_json_serializable(self):
        vehicle = self.make_vehicle()
        encoded = json.dumps(vehicle.to_dictionary())
        restored = Vehicle.from_dictionary(json.loads(encoded))
        self.assertEqual(restored.vehicle_id, vehicle.vehicle_id)
        self.assertEqual(restored.route, vehicle.route)

    def test_single_road_route_is_already_at_destination(self):
        vehicle = Vehicle("V-single", "A", "A", ["A"])
        self.assertEqual(vehicle.get_current_road(), "A")
        self.assertIsNone(vehicle.get_next_road())

    def test_invalid_vehicle_identifier_is_rejected(self):
        with self.assertRaises(ValueError):
            Vehicle("", "A", "B", ["A", "B"])


if __name__ == "__main__":
    unittest.main()
