import unittest
from unittest.mock import patch

from coordinator.coordinator import Coordinator


NETWORK = {
    "coordinator": {"host": "127.0.0.1", "port": 15000},
    "roads": {
        "A": {"host": "127.0.0.1", "port": 15001, "capacity": 5, "base_travel_ticks": 2, "connections": ["B"]},
        "B": {"host": "127.0.0.1", "port": 15002, "capacity": 5, "base_travel_ticks": 2, "connections": []},
    },
}


def status(road_id, current_tick=0, completed_tick=0, in_progress=False, error=None):
    return {
        "type": "STATUS",
        "road_id": road_id,
        "current_tick": current_tick,
        "completed_tick": completed_tick,
        "tick_in_progress": in_progress,
        "last_tick_error": error,
    }


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.coordinator = Coordinator(network=NETWORK)
        self.coordinator.maintain_vehicle_population = lambda: None
        self.road_by_port = {config["port"]: road_id for road_id, config in NETWORK["roads"].items()}

    def test_normal_tick_waits_for_every_road(self):
        def fake_send(host, port, message):
            road_id = self.road_by_port[port]
            if message["type"] == "TICK":
                self.coordinator.handle_tick_done({"road_id": road_id, "tick": message["tick"]})
                return {"type": "TICK_RECEIVED", "road_id": road_id, "tick": message["tick"]}
            raise AssertionError(message)

        with patch("coordinator.coordinator.send_request", side_effect=fake_send):
            result = self.coordinator.run_tick(timeout=0.1)

        self.assertTrue(result["success"])
        self.assertEqual(result["tick"], 1)
        self.assertEqual(result["completed_roads"], ["A", "B"])

    def test_lost_tick_reply_is_reconciled_without_resending(self):
        calls = {"tick": 0, "status": 0}

        def fake_send(host, port, message):
            road_id = self.road_by_port[port]
            if message["type"] == "TICK":
                calls["tick"] += 1
                raise TimeoutError("reply was lost after the road accepted it")
            if message["type"] == "GET_STATUS":
                calls["status"] += 1
                if calls["status"] == 1:
                    return status(road_id, current_tick=1, completed_tick=0, in_progress=True)
                return status(road_id, current_tick=1, completed_tick=1, in_progress=False)
            raise AssertionError(message)

        with patch("coordinator.coordinator.send_request", side_effect=fake_send):
            first = self.coordinator.run_tick(timeout=0)
            self.assertEqual(first["status"], "waiting")
            second = self.coordinator.run_tick(timeout=0)

        self.assertTrue(second["success"])
        self.assertEqual(calls["tick"], 2)  # One request for each road; no duplicate retry.
        self.assertEqual(second["completed_roads"], ["A", "B"])

    def test_tick_is_resent_only_when_status_proves_it_was_not_accepted(self):
        counts = {"A": 0, "B": 0}

        def fake_send(host, port, message):
            road_id = self.road_by_port[port]
            if message["type"] == "TICK":
                counts[road_id] += 1
                if road_id == "A" and counts[road_id] == 1:
                    raise TimeoutError("first response lost")
                return {"type": "TICK_RECEIVED", "road_id": road_id, "tick": 1}
            if message["type"] == "GET_STATUS":
                return status(road_id, current_tick=0)
            raise AssertionError(message)

        with patch("coordinator.coordinator.send_request", side_effect=fake_send):
            result = self.coordinator.run_tick(timeout=0)

        self.assertEqual(result["status"], "waiting")
        self.assertEqual(counts["A"], 2)
        self.assertEqual(counts["B"], 1)

    def test_unavailable_road_can_be_retried_without_advancing_tick(self):
        online = {"A": False, "B": True}
        accepted = {"A": False, "B": False}

        def fake_send(host, port, message):
            road_id = self.road_by_port[port]
            if message["type"] == "TICK":
                if not online[road_id]:
                    raise ConnectionError("road is offline")
                accepted[road_id] = True
                return {"type": "TICK_RECEIVED", "road_id": road_id, "tick": message["tick"]}
            if message["type"] == "GET_STATUS":
                if not online[road_id]:
                    raise ConnectionError("road is offline")
                return status(road_id, current_tick=1 if accepted[road_id] else 0, in_progress=accepted[road_id])
            raise AssertionError(message)

        with patch("coordinator.coordinator.send_request", side_effect=fake_send):
            first = self.coordinator.run_tick(timeout=0)
            self.assertEqual(first["status"], "road_unavailable")
            self.assertEqual(self.coordinator.current_tick, 1)
            online["A"] = True
            second = self.coordinator.run_tick(timeout=0)

        self.assertEqual(second["status"], "waiting")
        self.assertEqual(self.coordinator.current_tick, 1)
        self.assertEqual(self.coordinator.accepted_roads, {"A", "B"})

    def test_duplicate_tick_done_is_acknowledged(self):
        self.coordinator.current_tick = 1
        self.coordinator.tick_in_progress = True
        message = {"road_id": "A", "tick": 1}
        first = self.coordinator.handle_tick_done(message)
        second = self.coordinator.handle_tick_done(message)
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])

    def test_execution_failure_is_not_cleared_by_a_late_tick_received_reply(self):
        self.coordinator.current_tick = 1
        self.coordinator.tick_in_progress = True
        self.coordinator.handle_tick_failed({"road_id": "A", "tick": 1, "message": "vehicle transfer failed"})
        self.coordinator._mark_road_accepted("A")
        self.assertIn("A", self.coordinator.failed_roads)
        self.assertIn("A", self.coordinator.execution_failed_roads)

    def test_unknown_road_and_stale_tick_are_rejected(self):
        self.coordinator.current_tick = 4
        self.coordinator.tick_in_progress = True
        self.assertEqual(
            self.coordinator.handle_tick_done({"road_id": "Z", "tick": 4})["type"], "ERROR"
        )
        self.assertEqual(
            self.coordinator.handle_tick_done({"road_id": "A", "tick": 3})["type"], "ERROR"
        )

    def test_road_status_reports_online_and_offline_nodes(self):
        def fake_send(host, port, message):
            road_id = self.road_by_port[port]
            if road_id == "A":
                return {"type": "STATUS", "road_id": "A", "vehicle_count": 2}
            raise ConnectionError("connection refused")

        with patch("coordinator.coordinator.send_request", side_effect=fake_send):
            result = self.coordinator.get_road_status()

        self.assertEqual(result["online_roads"], ["A"])
        self.assertEqual(result["offline_roads"], ["B"])
        self.assertEqual(result["roads"]["A"]["vehicle_count"], 2)

    def test_set_tick_speed_validation(self):
        self.assertEqual(self.coordinator.set_tick_speed({"interval": 0.5})["type"], "SPEED_UPDATED")
        for invalid in (0, 0.09, 10.1, True, "1"):
            self.assertEqual(self.coordinator.set_tick_speed({"interval": invalid})["type"], "ERROR")

    def test_spawn_uses_main_branch_id_format_and_releases_reservation(self):
        vehicle = {
            "origin": "A", "destination": "B", "route": ["A", "B"],
            "route_index": 0, "remaining_ticks": 0, "created_tick": 0, "entry_tick": -1,
        }
        with patch("coordinator.coordinator.send_request", return_value={"type": "ACCEPTED", "road_id": "A"}) as send:
            response = self.coordinator.spawn_vehicle({"road_id": "A", "vehicle": vehicle})

        sent_vehicle = send.call_args.args[2]["vehicle"]
        self.assertEqual(response["vehicle_id"], 1)
        self.assertEqual(sent_vehicle["id"], 1)
        self.assertIn(1, self.coordinator.spawned_vehicle_ids)
        self.assertFalse(self.coordinator.reserved_vehicle_ids)

    def test_failed_spawn_does_not_count_vehicle_or_keep_reservation(self):
        vehicle = {
            "id": 77, "origin": "A", "destination": "B", "route": ["A", "B"],
            "route_index": 0, "remaining_ticks": 0, "created_tick": 0, "entry_tick": -1,
        }
        with patch("coordinator.coordinator.send_request", side_effect=ConnectionError("offline")):
            response = self.coordinator.spawn_vehicle({"road_id": "A", "vehicle": vehicle})
        self.assertEqual(response["type"], "ERROR")
        self.assertEqual(self.coordinator.total_vehicles_spawned, 0)
        self.assertNotIn(77, self.coordinator.reserved_vehicle_ids)

    def test_vehicle_completion_is_counted_once(self):
        self.coordinator.spawned_vehicle_ids.add(9)
        first = self.coordinator.handle_vehicle_completed({"vehicle_id": 9})
        second = self.coordinator.handle_vehicle_completed({"vehicle_id": 9})
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(len(self.coordinator.completed_vehicles), 1)

    def test_unknown_vehicle_completion_is_rejected(self):
        self.assertEqual(
            self.coordinator.handle_vehicle_completed({"vehicle_id": 999})["type"], "ERROR"
        )

    def test_get_simulation_info_includes_active_vehicle_count(self):
        self.coordinator.spawned_vehicle_ids.update({1, 2, 3})
        self.coordinator.completed_vehicles.add(2)
        info = self.coordinator.get_simulation_info()
        self.assertEqual(info["active_vehicles"], 2)
        self.assertEqual(info["total_vehicles_spawned"], 0)  # IDs added by a test are not spawn events.

    def test_retry_message_requires_an_incomplete_tick(self):
        response = self.coordinator.handle_message({"type": "RETRY_TICK"})
        self.assertEqual(response["type"], "ERROR")

    def test_advance_tick_starts_background_work(self):
        class ImmediateThread:
            def __init__(self, target, daemon=None, name=None):
                self.target = target

            def start(self):
                self.target()

        with patch("coordinator.coordinator.threading.Thread", ImmediateThread), \
             patch.object(self.coordinator, "run_tick", return_value={"success": True} ) as run_tick:
            response = self.coordinator.handle_message({"type": "ADVANCE_TICK"})

        self.assertEqual(response["type"], "TICK_STARTED")
        run_tick.assert_called_once()
        self.assertFalse(self.coordinator.tick_start_pending)

    def test_play_and_pause_controls(self):
        with patch.object(self.coordinator, "automatic_tick_loop", return_value=None):
            started = self.coordinator.play_simulation()
            self.assertEqual(started["type"], "PLAYING")
            paused = self.coordinator.pause_simulation()

        self.assertEqual(paused["type"], "PAUSED")
        self.assertFalse(self.coordinator.auto_running)

    def test_accident_control_validates_and_forwards_request(self):
        expected = {"type": "ACCIDENT_UPDATED", "road_id": "A", "accident_active": True}
        with patch("coordinator.coordinator.send_request", return_value=expected) as send:
            response = self.coordinator.set_accident({"road_id": "A", "active": True})
        self.assertEqual(response, expected)
        self.assertEqual(send.call_args.args[2], {"type": "SET_ACCIDENT", "active": True})
        self.assertEqual(self.coordinator.set_accident({"road_id": "A", "active": 1})["type"], "ERROR")


if __name__ == "__main__":
    unittest.main()
