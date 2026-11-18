
import unittest

from communication.protocol import send_request


class TestVehicleLifecycle(unittest.TestCase):

    def test_vehicle_spawn(self):
        vehicle = {
            "origin": "A",
            "destination": "C",
            "route": ["A", "C"],
            "route_index": 0,
            "remaining_ticks": 0,
            "created_tick": 0,
            "entry_tick": -1
        }

        response = send_request(
            "127.0.0.1",
            5000,
            {
                "type": "SPAWN_VEHICLE",
                "road_id": "A",
                "vehicle": vehicle
            }
        )

        self.assertEqual(response["type"], "ACCEPTED")
        self.assertEqual(response["road_id"], "A")
        self.assertIsInstance(response["vehicle_id"], int)

        road_status = send_request(
            "127.0.0.1",
            5001,
            {"type": "GET_STATUS"}
        )

        self.assertEqual(road_status["vehicle_count"], 1)


if __name__ == "__main__":
    unittest.main()
