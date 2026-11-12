import threading
import unittest
from unittest.mock import patch

from coordinator.coordinator import Coordinator


def make_network():
    return {
        "coordinator": {"host": "127.0.0.1", "port": 5000},
        "roads": {
            "A": {"host": "127.0.0.1", "port": 5001},
            "B": {"host": "127.0.0.1", "port": 5002},
            "C": {"host": "127.0.0.1", "port": 5003},
        },
    }


class CoordinatorTickTests(unittest.TestCase):
    def setUp(self):
        self.coordinator = Coordinator(network=make_network())

    def test_unknown_road_is_rejected(self):
        response = self.coordinator.handle_tick_done(
            {"type": "TICK_DONE", "road_id": "Z", "tick": 1}
        )
        self.assertEqual(response["type"], "ERROR")

    def test_wrong_tick_is_rejected(self):
        self.coordinator.current_tick = 1
        self.coordinator.tick_in_progress = True

        response = self.coordinator.handle_tick_done(
            {"type": "TICK_DONE", "road_id": "A", "tick": 2}
        )
        self.assertEqual(response["type"], "ERROR")
        self.assertEqual(self.coordinator.completed_roads, set())

    def test_duplicate_completion_is_only_counted_once(self):
        self.coordinator.current_tick = 1
        self.coordinator.tick_in_progress = True

        first = self.coordinator.handle_tick_done(
            {"type": "TICK_DONE", "road_id": "A", "tick": 1}
        )
        second = self.coordinator.handle_tick_done(
            {"type": "TICK_DONE", "road_id": "A", "tick": 1}
        )

        self.assertEqual(first["type"], "ACKNOWLEDGE")
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(self.coordinator.completed_roads, {"A"})

    def test_tick_waits_until_all_three_roads_finish(self):
        all_ticks_sent = threading.Event()
        sent_count = {"value": 0}
        sent_lock = threading.Lock()

        def fake_send_request(host, port, message):
            if message["type"] == "TICK":
                with sent_lock:
                    sent_count["value"] += 1
                    if sent_count["value"] == 3:
                        all_ticks_sent.set()

                road_id = next(
                    road for road, config in self.coordinator.roads.items()
                    if config["port"] == port
                )
                return {
                    "type": "TICK_RECEIVED",
                    "road_id": road_id,
                    "tick": message["tick"],
                }

            raise AssertionError("Unexpected request in this test")

        result = {}
        with patch("coordinator.coordinator.send_request", side_effect=fake_send_request):
            worker = threading.Thread(
                target=lambda: result.update(self.coordinator.run_tick(timeout=2))
            )
            worker.start()

            self.assertTrue(all_ticks_sent.wait(timeout=1))

            # Two roads finish, but the Coordinator must still be waiting.
            self.coordinator.handle_message(
                {"type": "TICK_DONE", "road_id": "A", "tick": 1}
            )
            self.coordinator.handle_message(
                {"type": "TICK_DONE", "road_id": "B", "tick": 1}
            )
            self.assertTrue(self.coordinator.tick_in_progress)

            # Only the third completion allows the tick to finish.
            self.coordinator.handle_message(
                {"type": "TICK_DONE", "road_id": "C", "tick": 1}
            )
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.coordinator.current_tick, 1)
        self.assertFalse(self.coordinator.tick_in_progress)

    def test_run_tick_can_resume_waiting_without_rebroadcasting(self):
        sent_ticks = []

        def fake_send_request(host, port, message):
            sent_ticks.append((port, message["tick"]))
            road_id = next(
                road for road, config in self.coordinator.roads.items()
                if config["port"] == port
            )
            return {
                "type": "TICK_RECEIVED",
                "road_id": road_id,
                "tick": message["tick"],
            }

        with patch("coordinator.coordinator.send_request", side_effect=fake_send_request):
            first_result = self.coordinator.run_tick(timeout=0.001)
            self.assertEqual(first_result["status"], "waiting")
            self.coordinator.handle_tick_done(
                {"type": "TICK_DONE", "road_id": "A", "tick": 1}
            )
            self.coordinator.handle_tick_done(
                {"type": "TICK_DONE", "road_id": "B", "tick": 1}
            )
            self.coordinator.handle_tick_done(
                {"type": "TICK_DONE", "road_id": "C", "tick": 1}
            )
            second_result = self.coordinator.run_tick(timeout=0.1)

        self.assertEqual(second_result["status"], "completed")
        self.assertEqual(self.coordinator.current_tick, 1)
        self.assertEqual(len(sent_ticks), 3)

    def test_unreachable_road_does_not_advance_tick(self):
        def fake_send_request(host, port, message):
            if port == 5002:
                raise ConnectionError("Road B is unavailable")
            road_id = "A" if port == 5001 else "C"
            return {
                "type": "TICK_RECEIVED",
                "road_id": road_id,
                "tick": message["tick"],
            }

        with patch("coordinator.coordinator.send_request", side_effect=fake_send_request):
            result = self.coordinator.run_tick(timeout=0.1)

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "road_unavailable")
        self.assertEqual(self.coordinator.current_tick, 1)
        self.assertTrue(self.coordinator.tick_in_progress)
        self.assertIn("B", self.coordinator.failed_roads)

    def test_spawn_vehicle_assigns_id_and_tracks_acceptance(self):
        with patch(
            "coordinator.coordinator.send_request",
            return_value={"type": "ACCEPTED", "road_id": "A"},
        ) as request:
            response = self.coordinator.spawn_vehicle(
                {"type": "SPAWN_VEHICLE", "road_id": "A", "vehicle": {"route": ["A", "B"]}}
            )

        self.assertEqual(response["type"], "ACCEPTED")
        self.assertTrue(response["vehicle_id"].startswith("vehicle-"))
        self.assertEqual(self.coordinator.total_vehicles_spawned, 1)
        sent = request.call_args.args[2]
        self.assertEqual(sent["type"], "SPAWN_VEHICLE")
        self.assertEqual(sent["vehicle"]["vehicle_id"], response["vehicle_id"])

    def test_duplicate_vehicle_id_is_rejected(self):
        with patch(
            "coordinator.coordinator.send_request",
            return_value={"type": "ACCEPTED", "road_id": "A"},
        ) as request:
            first = self.coordinator.spawn_vehicle(
                {"road_id": "A", "vehicle": {"vehicle_id": "V100"}}
            )
            second = self.coordinator.spawn_vehicle(
                {"road_id": "B", "vehicle": {"vehicle_id": "V100"}}
            )

        self.assertEqual(first["type"], "ACCEPTED")
        self.assertEqual(second["type"], "ERROR")
        self.assertEqual(request.call_count, 1)

    def test_completed_vehicle_is_counted_once(self):
        first = self.coordinator.handle_vehicle_completed(
            {"type": "VEHICLE_COMPLETED", "vehicle_id": "V1"}
        )
        second = self.coordinator.handle_vehicle_completed(
            {"type": "VEHICLE_COMPLETED", "vehicle_id": "V1"}
        )
        self.assertEqual(first["type"], "ACKNOWLEDGE")
        self.assertEqual(second["type"], "ACKNOWLEDGE")
        self.assertEqual(self.coordinator.get_simulation_info()["completed_vehicles"], 1)


if __name__ == "__main__":
    unittest.main()
