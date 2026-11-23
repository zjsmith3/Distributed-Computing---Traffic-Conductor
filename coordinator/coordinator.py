"""Coordinator Node for the Traffic Conductor simulation.

The Coordinator owns the global tick number and coordinates the Road Nodes.
It never advances to a new tick until every configured road has confirmed that
its current tick finished. When a network reply is lost, it checks the road's
reported state before deciding whether a tick can safely be sent again.
"""

import random
import threading
import time

from communication.protocol import send_request
from communication.server import start_server as run_tcp_server
from config.config import load_network_file


class Coordinator:
    """Coordinate Road Nodes through the project's TCP/JSON protocol."""

    def __init__(self, network=None):
        self.network = network if network is not None else load_network_file()
        self.coordinator_config = self.network["coordinator"]
        self.roads = self.network["roads"]

        self.current_tick = 0
        self.completed_roads = set()
        self.accepted_roads = set()
        self.tick_in_progress = False
        self.tick_failed = False
        self.failed_roads = {}
        self.execution_failed_roads = set()
        self.completion_report_pending = False
        self.tick_start_pending = False

        self.auto_running = False
        self.tick_interval = 1.0
        self.auto_thread = None
        self.last_population_tick = 0
        self.simulation_running = False

        self.completed_vehicles = set()
        self.spawned_vehicle_ids = set()
        self.reserved_vehicle_ids = set()
        self.total_vehicles_spawned = 0
        self.next_vehicle_number = 1
        self.target_vehicle_count = 10

        self.condition = threading.Condition()
        self.tick_execution_lock = threading.Lock()
        self.server_thread = None

    # ------------------------------------------------------------------
    # Server and message handling
    # ------------------------------------------------------------------

    def start_server(self):
        """Start the Coordinator TCP server in a daemon thread."""
        if self.server_thread is not None and self.server_thread.is_alive():
            return self.server_thread

        host = self.coordinator_config["host"]
        port = self.coordinator_config["port"]
        self.server_thread = threading.Thread(
            target=run_tcp_server,
            args=(host, port, self.handle_message),
            daemon=True,
            name="coordinator-server",
        )
        self.server_thread.start()
        print(f"Coordinator listening on {host}:{port}")
        return self.server_thread

    def start_simulation(self):
        self.simulation_running = True
        print("Simulation started.")

    def stop_simulation(self):
        with self.condition:
            self.simulation_running = False
            self.auto_running = False
            self.condition.notify_all()
        print("Simulation stopped.")

    def handle_message(self, message):
        """Route an incoming message to the matching Coordinator method."""
        if not isinstance(message, dict) or not isinstance(message.get("type"), str):
            return {"type": "ERROR", "message": "Message must contain a string type."}

        message_type = message["type"]
        handlers = {
            "TICK_DONE": self.handle_tick_done,
            "TICK_FAILED": self.handle_tick_failed,
            "VEHICLE_COMPLETED": self.handle_vehicle_completed,
            "GET_SIMULATION_INFO": lambda _message: self.get_simulation_info(),
            "GET_ROAD_STATUS": self.get_road_status,
            "SPAWN_VEHICLE": self.spawn_vehicle,
            "SET_ACCIDENT": self.set_accident,
            "PLAY": lambda _message: self.play_simulation(),
            "PAUSE": lambda _message: self.pause_simulation(),
            "SET_TICK_SPEED": self.set_tick_speed,
        }

        if message_type == "ADVANCE_TICK":
            with self.condition:
                if self.auto_running:
                    return {"type": "ERROR", "message": "Pause the simulation before manually advancing."}
                if self.tick_in_progress:
                    return {
                        "type": "ERROR",
                        "message": "The current tick is incomplete. Send RETRY_TICK to resume it.",
                    }
            return self._launch_tick_worker(retry=False)

        if message_type == "RETRY_TICK":
            with self.condition:
                if self.auto_running:
                    return {"type": "ERROR", "message": "Pause the simulation before retrying a tick."}
                if not self.tick_in_progress:
                    return {"type": "ERROR", "message": "There is no incomplete tick to retry."}
            return self._launch_tick_worker(retry=True)

        handler = handlers.get(message_type)
        if handler is None:
            return {"type": "ERROR", "message": f"Unknown message type: {message_type}"}
        return handler(message)

    def _launch_tick_worker(self, retry=False):
        """Run a tick outside the socket handler so clients get a quick reply."""
        with self.condition:
            if self.tick_start_pending or self.tick_execution_lock.locked():
                return {"type": "ERROR", "message": "A tick operation is already running."}
            if retry and not self.tick_in_progress:
                return {"type": "ERROR", "message": "There is no incomplete tick to retry."}
            if not retry and self.tick_in_progress:
                return {"type": "ERROR", "message": "The current tick must be completed first."}
            self.tick_start_pending = True

        def worker():
            try:
                result = self.run_tick()
                if not result.get("success"):
                    print(f"Tick operation did not finish: {result.get('message', 'Unknown error')}")
            finally:
                with self.condition:
                    self.tick_start_pending = False
                    self.condition.notify_all()

        worker_thread = threading.Thread(
            target=worker,
            daemon=True,
            name="coordinator-tick",
        )
        try:
            worker_thread.start()
        except RuntimeError as error:
            with self.condition:
                self.tick_start_pending = False
                self.condition.notify_all()
            return {"type": "ERROR", "message": f"Could not start the tick worker: {error}"}

        return {"type": "TICK_STARTED", "retry": retry, "tick": self.current_tick + (0 if retry else 1)}

    # ------------------------------------------------------------------
    # Tick synchronization and recovery
    # ------------------------------------------------------------------

    def run_tick(self, timeout=30):
        """Run a new tick, or resume the existing tick if it is incomplete."""
        if not self.tick_execution_lock.acquire(blocking=False):
            return {
                "success": False,
                "status": "busy",
                "message": "Another thread is already handling a tick.",
            }

        try:
            # Fill the network before its first tick. Further population checks
            # happen after successful ticks so completed journeys are replaced.
            if self.current_tick == 0 and self.last_population_tick == 0:
                self.maintain_vehicle_population()

            result = self._run_tick(timeout=timeout)
            if result["success"] and self.last_population_tick != result["tick"]:
                self.maintain_vehicle_population()
                self.last_population_tick = result["tick"]
            return result
        finally:
            self.tick_execution_lock.release()

    def _run_tick(self, timeout=30):
        with self.condition:
            if self.completion_report_pending and not self.tick_in_progress:
                self.completion_report_pending = False
                return self._completed_tick_result()

            if not self.tick_in_progress:
                self.current_tick += 1
                self.completed_roads.clear()
                self.accepted_roads.clear()
                self.failed_roads.clear()
                self.execution_failed_roads.clear()
                self.tick_failed = False
                self.tick_in_progress = True
                self.completion_report_pending = True

            tick = self.current_tick

        print(f"Coordinating Tick {tick}...")
        self._retry_pending_roads(tick)

        with self.condition:
            if not self.tick_in_progress:
                self.completion_report_pending = False
                return self._completed_tick_result()
            if self.failed_roads:
                return self._tick_failure_result()

        finished = self.wait_for_tick(timeout=timeout)
        with self.condition:
            if finished:
                self.completion_report_pending = False
                return self._completed_tick_result()
            if self.failed_roads:
                return self._tick_failure_result()
            return {
                "success": False,
                "status": "waiting",
                "message": "The tick was accepted, but one or more Road Nodes have not finished yet.",
                **self.get_tick_status(),
            }

    def _retry_pending_roads(self, tick):
        """Contact only roads that have not completed the active tick."""
        for road_id, road_config in self.roads.items():
            with self.condition:
                if road_id in self.completed_roads:
                    continue
                already_accepted = road_id in self.accepted_roads

            if already_accepted:
                self._reconcile_accepted_road(road_id, road_config, tick)
            else:
                self._send_tick_to_road(road_id, road_config, tick)

    def _send_tick_to_road(self, road_id, road_config, tick):
        """Send a tick and recover safely if the reply is lost or invalid."""
        try:
            response = send_request(
                road_config["host"], road_config["port"],
                {"type": "TICK", "tick": tick},
            )
            if self._valid_tick_response(response, road_id, tick):
                if response["type"] == "TICK_COMPLETED":
                    self._mark_road_completed(road_id, tick)
                else:
                    self._mark_road_accepted(road_id)
                return
            reason = f"Unexpected TICK response: {response!r}"
        except Exception as error:  # Network errors vary by platform and socket state.
            reason = f"TICK request failed: {error}"

        self._recover_uncertain_delivery(road_id, road_config, tick, reason)

    @staticmethod
    def _valid_tick_response(response, road_id, tick):
        return (
            isinstance(response, dict)
            and response.get("type") in ("TICK_RECEIVED", "TICK_COMPLETED")
            and response.get("road_id") == road_id
            and response.get("tick") == tick
        )

    def _recover_uncertain_delivery(self, road_id, road_config, tick, original_reason):
        """Check the node's state before deciding whether a resend is safe."""
        try:
            status = send_request(
                road_config["host"], road_config["port"], {"type": "GET_STATUS"}
            )
        except Exception as error:
            self.record_tick_failure(road_id, f"{original_reason}; status check failed: {error}")
            return

        if not isinstance(status, dict) or status.get("road_id") != road_id:
            self.record_tick_failure(road_id, f"{original_reason}; invalid GET_STATUS response: {status!r}")
            return

        node_tick = status.get("current_tick")
        if node_tick == tick:
            self._mark_road_accepted(road_id)
            self._reconcile_status_fields(road_id, status, tick)
            return

        if node_tick != tick - 1:
            self.record_tick_failure(
                road_id,
                f"{original_reason}; Road {road_id} reports tick {node_tick}, expected {tick - 1} or {tick}.",
            )
            return

        # The road confirms that it has not accepted this tick, so one resend
        # is safe. If that response is also lost, query status one more time.
        try:
            response = send_request(
                road_config["host"], road_config["port"],
                {"type": "TICK", "tick": tick},
            )
            if self._valid_tick_response(response, road_id, tick):
                if response["type"] == "TICK_COMPLETED":
                    self._mark_road_completed(road_id, tick)
                else:
                    self._mark_road_accepted(road_id)
                return
            retry_reason = f"Retry returned an unexpected response: {response!r}"
        except Exception as error:
            retry_reason = f"Retry request failed: {error}"

        try:
            status = send_request(
                road_config["host"], road_config["port"], {"type": "GET_STATUS"}
            )
        except Exception as error:
            self.record_tick_failure(road_id, f"{retry_reason}; second status check failed: {error}")
            return

        if isinstance(status, dict) and status.get("road_id") == road_id and status.get("current_tick") == tick:
            self._mark_road_accepted(road_id)
            self._reconcile_status_fields(road_id, status, tick)
        else:
            self.record_tick_failure(road_id, f"{retry_reason}; Road status after retry: {status!r}")

    def _reconcile_accepted_road(self, road_id, road_config, tick):
        """Check whether a previously accepted road has finished its work."""
        try:
            status = send_request(
                road_config["host"], road_config["port"], {"type": "GET_STATUS"}
            )
        except Exception as error:
            self.record_tick_failure(road_id, f"Could not confirm tick progress: {error}")
            return

        if not isinstance(status, dict) or status.get("road_id") != road_id:
            self.record_tick_failure(road_id, f"Invalid status while checking tick progress: {status!r}")
            return

        if status.get("current_tick") != tick:
            self.record_tick_failure(
                road_id,
                f"Road reports current tick {status.get('current_tick')}; Coordinator is on tick {tick}.",
            )
            return
        self._reconcile_status_fields(road_id, status, tick)

    def _reconcile_status_fields(self, road_id, status, tick):
        completed_tick = status.get("completed_tick")
        if isinstance(completed_tick, int) and completed_tick >= tick:
            self._mark_road_completed(road_id, tick)
            return

        last_error = status.get("last_tick_error")
        if last_error:
            self.record_tick_failure(
                road_id,
                f"Road Node reported a tick error: {last_error}",
                execution_error=True,
            )
            return

        # Older Road Node versions do not publish completion metadata. Do not
        # guess that they finished; leave the road pending instead.
        if status.get("tick_in_progress") is False:
            self.record_tick_failure(
                road_id,
                "Road accepted the tick but did not report completion or an active tick.",
            )

    def _mark_road_accepted(self, road_id):
        with self.condition:
            self.accepted_roads.add(road_id)
            # Do not erase an execution failure that may have arrived just
            # before the original TICK_RECEIVED response.
            if road_id not in self.execution_failed_roads:
                self.failed_roads.pop(road_id, None)
            self.tick_failed = bool(self.failed_roads)
            self.condition.notify_all()

    def _mark_road_completed(self, road_id, tick):
        with self.condition:
            if tick != self.current_tick:
                return
            self.accepted_roads.add(road_id)
            self.completed_roads.add(road_id)
            self.execution_failed_roads.discard(road_id)
            self.failed_roads.pop(road_id, None)
            self.tick_failed = bool(self.failed_roads)
            if self.completed_roads == set(self.roads):
                self.tick_in_progress = False
                self.tick_failed = False
                self.failed_roads.clear()
                print(f"All roads completed Tick {tick}.")
            self.condition.notify_all()

    def handle_tick_done(self, message):
        road_id = message.get("road_id")
        tick = message.get("tick")
        if road_id not in self.roads:
            return {"type": "ERROR", "message": f"Unknown road: {road_id}"}

        with self.condition:
            if type(tick) is not int or tick != self.current_tick:
                return {
                    "type": "ERROR",
                    "message": f"Incorrect tick from Road {road_id}. Expected {self.current_tick}, received {tick}.",
                }
            if road_id in self.completed_roads:
                return {"type": "ACKNOWLEDGE", "road_id": road_id, "tick": tick, "duplicate": True}
            if not self.tick_in_progress:
                return {"type": "ERROR", "message": "There is no active tick to complete."}

            self.accepted_roads.add(road_id)
            self.completed_roads.add(road_id)
            self.execution_failed_roads.discard(road_id)
            self.failed_roads.pop(road_id, None)
            self.tick_failed = bool(self.failed_roads)
            print(f"Road {road_id} completed Tick {tick} ({len(self.completed_roads)}/{len(self.roads)}).")
            if self.completed_roads == set(self.roads):
                self.tick_in_progress = False
                self.tick_failed = False
                self.failed_roads.clear()
                print(f"All roads completed Tick {tick}.")
            self.condition.notify_all()

        return {"type": "ACKNOWLEDGE", "road_id": road_id, "tick": tick, "duplicate": False}

    def handle_tick_failed(self, message):
        road_id = message.get("road_id")
        tick = message.get("tick")
        reason = message.get("message", "Road Node reported a tick failure.")
        if road_id not in self.roads:
            return {"type": "ERROR", "message": f"Unknown road: {road_id}"}
        with self.condition:
            if type(tick) is not int or tick != self.current_tick or not self.tick_in_progress:
                return {"type": "ERROR", "message": "Tick failure does not match the active tick."}
            self.accepted_roads.add(road_id)
            self.execution_failed_roads.add(road_id)
            self.failed_roads[road_id] = str(reason)
            self.tick_failed = True
            self.condition.notify_all()
        return {"type": "ACKNOWLEDGE", "road_id": road_id, "tick": tick}

    def record_tick_failure(self, road_id, reason, execution_error=False):
        with self.condition:
            self.failed_roads[road_id] = str(reason)
            if execution_error:
                self.execution_failed_roads.add(road_id)
            self.tick_failed = True
            self.condition.notify_all()
        print(f"Road {road_id} needs attention: {reason}")

    def wait_for_tick(self, timeout=None):
        """Wait until all roads finish or the timeout/failure is reached."""
        with self.condition:
            if timeout is None:
                while self.tick_in_progress and not self.failed_roads:
                    self.condition.wait()
            else:
                deadline = time.monotonic() + max(0, timeout)
                while self.tick_in_progress and not self.failed_roads:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self.condition.wait(remaining)
            return not self.tick_in_progress

    def get_tick_status(self):
        with self.condition:
            expected = set(self.roads)
            return {
                "tick": self.current_tick,
                "tick_in_progress": self.tick_in_progress,
                "accepted_roads": sorted(self.accepted_roads),
                "completed_roads": sorted(self.completed_roads),
                "pending_roads": sorted(expected - self.completed_roads),
                "unaccepted_roads": sorted(expected - self.accepted_roads - self.completed_roads),
                "failed_roads": dict(self.failed_roads),
            }

    def _completed_tick_result(self):
        return {
            "success": True,
            "status": "completed",
            "message": f"Tick {self.current_tick} completed by every Road Node.",
            **self.get_tick_status(),
        }

    def _tick_failure_result(self):
        return {
            "success": False,
            "status": "road_unavailable",
            "message": "One or more Road Nodes need attention. Fix the issue, then retry the same tick.",
            **self.get_tick_status(),
        }

    # ------------------------------------------------------------------
    # Road health and simulation information
    # ------------------------------------------------------------------

    def get_road_status(self, message=None):
        """Query each Road Node and return its latest status and reachability."""
        message = message or {}
        requested_road = message.get("road_id")
        if requested_road is not None and requested_road not in self.roads:
            return {"type": "ERROR", "message": f"Unknown road: {requested_road}"}

        road_ids = [requested_road] if requested_road else list(self.roads)
        results = {}
        for road_id in road_ids:
            road_config = self.roads[road_id]
            try:
                response = send_request(
                    road_config["host"], road_config["port"], {"type": "GET_STATUS"}
                )
                if isinstance(response, dict) and response.get("type") == "STATUS":
                    results[road_id] = {"reachable": True, **response}
                else:
                    results[road_id] = {
                        "reachable": False,
                        "error": f"Unexpected response: {response!r}",
                    }
            except Exception as error:
                results[road_id] = {"reachable": False, "error": str(error)}

        return {
            "type": "ROAD_STATUS",
            "tick": self.current_tick,
            "roads": results,
            "online_roads": sorted(r for r, status in results.items() if status["reachable"]),
            "offline_roads": sorted(r for r, status in results.items() if not status["reachable"]),
        }

    def get_simulation_info(self):
        with self.condition:
            return {
                "type": "SIMULATION_INFO",
                "current_tick": self.current_tick,
                "total_vehicles_spawned": self.total_vehicles_spawned,
                "completed_vehicles": len(self.completed_vehicles),
                "active_vehicles": len(self.spawned_vehicle_ids - self.completed_vehicles),
                "tick_in_progress": self.tick_in_progress,
                "accepted_roads": sorted(self.accepted_roads),
                "completed_roads": sorted(self.completed_roads),
                "pending_roads": sorted(set(self.roads) - self.completed_roads),
                "failed_roads": dict(self.failed_roads),
                "auto_running": self.auto_running,
                "tick_interval": self.tick_interval,
                "target_vehicle_count": self.target_vehicle_count,
            }

    # ------------------------------------------------------------------
    # Vehicle lifecycle and road controls
    # ------------------------------------------------------------------

    def handle_vehicle_completed(self, message):
        vehicle_id = message.get("vehicle_id")
        if type(vehicle_id) is not int or vehicle_id < 0:
            return {"type": "ERROR", "message": "A nonnegative integer vehicle_id is required."}

        with self.condition:
            if vehicle_id not in self.spawned_vehicle_ids:
                return {"type": "ERROR", "message": f"Unknown vehicle ID: {vehicle_id}"}
            if vehicle_id in self.completed_vehicles:
                return {"type": "ACKNOWLEDGE", "vehicle_id": vehicle_id, "duplicate": True}
            self.completed_vehicles.add(vehicle_id)

        return {"type": "ACKNOWLEDGE", "vehicle_id": vehicle_id, "duplicate": False}

    def spawn_vehicle(self, message):
        """Send a vehicle to its starting road and reserve its ID during the call."""
        road_id = message.get("road_id") or message.get("starting_road")
        vehicle = message.get("vehicle")
        if road_id not in self.roads:
            return {"type": "ERROR", "message": f"Unknown starting road: {road_id}"}
        if not isinstance(vehicle, dict):
            return {"type": "ERROR", "message": "A vehicle dictionary is required."}

        vehicle = dict(vehicle)
        with self.condition:
            vehicle_id = vehicle.get("id")
            if vehicle_id is None:
                while (
                    self.next_vehicle_number in self.spawned_vehicle_ids
                    or self.next_vehicle_number in self.reserved_vehicle_ids
                ):
                    self.next_vehicle_number += 1
                vehicle_id = self.next_vehicle_number
                self.next_vehicle_number += 1
                vehicle["id"] = vehicle_id

            if type(vehicle_id) is not int or vehicle_id < 0:
                return {"type": "ERROR", "message": "Vehicle ID must be a nonnegative integer."}
            if vehicle_id in self.spawned_vehicle_ids or vehicle_id in self.reserved_vehicle_ids:
                return {"type": "ERROR", "message": f"Vehicle ID {vehicle_id} has already been used."}

            self.reserved_vehicle_ids.add(vehicle_id)
            tick = self.current_tick

        road_config = self.roads[road_id]
        try:
            response = send_request(
                road_config["host"], road_config["port"],
                {"type": "SPAWN_VEHICLE", "vehicle": vehicle, "tick": tick},
            )
        except Exception as error:
            with self.condition:
                self.reserved_vehicle_ids.discard(vehicle_id)
            return {"type": "ERROR", "message": f"Could not contact Road {road_id}: {error}"}

        with self.condition:
            self.reserved_vehicle_ids.discard(vehicle_id)
            if isinstance(response, dict) and response.get("type") == "ACCEPTED":
                self.spawned_vehicle_ids.add(vehicle_id)
                self.total_vehicles_spawned += 1
                response = dict(response)
                response["vehicle_id"] = vehicle_id
        return response

    def set_accident(self, message):
        road_id = message.get("road_id")
        active = message.get("active")
        if road_id not in self.roads:
            return {"type": "ERROR", "message": f"Unknown road: {road_id}"}
        if not isinstance(active, bool):
            return {"type": "ERROR", "message": "SET_ACCIDENT requires active to be True or False."}

        road_config = self.roads[road_id]
        try:
            return send_request(
                road_config["host"], road_config["port"],
                {"type": "SET_ACCIDENT", "active": active},
            )
        except Exception as error:
            return {"type": "ERROR", "message": f"Could not contact Road {road_id}: {error}"}

    # ------------------------------------------------------------------
    # Automatic play/pause and population maintenance
    # ------------------------------------------------------------------

    def play_simulation(self):
        with self.condition:
            if self.auto_running:
                return {"type": "ERROR", "message": "Simulation is already running."}
            if self.tick_start_pending or self.tick_execution_lock.locked():
                return {"type": "ERROR", "message": "A manual tick operation is still running."}
            if self.auto_thread is not None and self.auto_thread.is_alive():
                return {"type": "ERROR", "message": "The previous automatic loop is still stopping."}
            self.auto_running = True
            self.auto_thread = threading.Thread(
                target=self.automatic_tick_loop,
                daemon=True,
                name="coordinator-auto-tick",
            )
            self.auto_thread.start()
        return {"type": "PLAYING", "message": "Automatic simulation started."}

    def pause_simulation(self):
        with self.condition:
            if not self.auto_running:
                return {"type": "ERROR", "message": "Simulation is already paused."}
            self.auto_running = False
            self.condition.notify_all()
        return {"type": "PAUSED", "message": "Automatic simulation paused."}

    def set_tick_speed(self, message):
        interval = message.get("interval")
        if type(interval) not in (int, float) or not 0.1 <= interval <= 10:
            return {"type": "ERROR", "message": "Tick interval must be between 0.1 and 10 seconds."}
        with self.condition:
            self.tick_interval = float(interval)
        return {"type": "SPEED_UPDATED", "tick_interval": float(interval)}

    def automatic_tick_loop(self):
        while True:
            with self.condition:
                if not self.auto_running:
                    break
            result = self.run_tick()
            if not result["success"]:
                with self.condition:
                    self.auto_running = False
                    self.condition.notify_all()
                print(f"Automatic ticking stopped: {result['message']}")
                break
            with self.condition:
                if not self.auto_running:
                    break
                self.condition.wait(timeout=self.tick_interval)

    def maintain_vehicle_population(self):
        with self.condition:
            active_cars = len(self.spawned_vehicle_ids - self.completed_vehicles)
            cars_needed = max(0, self.target_vehicle_count - active_cars)

        print(f"Active vehicles: {active_cars}; vehicles to add: {cars_needed}")
        for _ in range(cars_needed):
            route = self.generate_temporary_route()
            if not route:
                print("Could not generate a valid route for another vehicle.")
                break

            vehicle = {
                "origin": route[0],
                "destination": route[-1],
                "route": route,
                "route_index": 0,
                "remaining_ticks": 0,
                "created_tick": self.current_tick,
                "entry_tick": -1,
            }
            response = self.spawn_vehicle({"road_id": route[0], "vehicle": vehicle})
            if not isinstance(response, dict) or response.get("type") != "ACCEPTED":
                print(f"Vehicle spawn failed: {response}")
                break
            print(f"Spawned vehicle {response['vehicle_id']} on Road {route[0]}.")

    def generate_temporary_route(self):
        """Create a temporary valid route until the User Node routing module exists."""
        starting_roads = [
            road_id for road_id, config in self.roads.items() if config.get("connections")
        ]
        if not starting_roads:
            return None

        current_road = random.choice(starting_roads)
        route = [current_road]
        while True:
            connections = self.roads[current_road].get("connections", [])
            available = [road for road in connections if road not in route]
            if not available:
                break
            current_road = random.choice(available)
            route.append(current_road)
        return route


def main():
    coordinator = Coordinator()
    coordinator.start_server()
    coordinator.start_simulation()
    print("Traffic Conductor Coordinator is ready.")
    print("Start the Road Nodes in separate terminals before running ticks.")

    try:
        while coordinator.simulation_running:
            command = input("Press Enter for the next tick, or type q to quit: ")
            if command.strip().lower() == "q":
                break
            result = coordinator.run_tick()
            print(result["message"])
            if result["status"] == "road_unavailable":
                print("The same tick is still active. Fix the Road Node, then press Enter to retry it.")
    except KeyboardInterrupt:
        print("\nCoordinator interrupted.")
    finally:
        coordinator.stop_simulation()


if __name__ == "__main__":
    main()
