"""Coordinator Node for the Traffic Conductor simulation.

The Coordinator controls the global simulation tick and collects completion
messages from each Road Node. Road Nodes remain responsible for moving vehicles.
"""

import threading
import time

from communication.protocol import send_request
from communication.server import start_server as run_tcp_server
from config.config import load_network_file


class Coordinator:
    """Coordinates Road Nodes using the project's existing TCP/JSON protocol."""

    def __init__(self, network=None):
        # Allow a custom network in tests; normal execution uses network.json.
        self.network = network if network is not None else load_network_file()
        self.coordinator_config = self.network["coordinator"]
        self.roads = self.network["roads"]

        self.current_tick = 0
        self.completed_roads = set()
        self.tick_in_progress = False
        self.tick_failed = False
        self.failed_roads = {}
        self.completion_report_pending = False

        self.completed_vehicles = set()
        self.spawned_vehicle_ids = set()
        self.reserved_vehicle_ids = set()
        self.total_vehicles_spawned = 0
        self.next_vehicle_number = 1

        # The server can receive messages from several Road Nodes at once.
        self.condition = threading.Condition()
        self.server_thread = None
        self.simulation_running = False

    def start_server(self):
        """Start the Coordinator TCP server in a background thread."""
        if self.server_thread is not None and self.server_thread.is_alive():
            return self.server_thread

        host = self.coordinator_config["host"]
        port = self.coordinator_config["port"]
        self.server_thread = threading.Thread(
            target=run_tcp_server,
            args=(host, port, self.handle_message),
            daemon=True,
        )
        self.server_thread.start()
        print(f"Coordinator listening on {host}:{port}")
        return self.server_thread

    def start_simulation(self):
        """Mark the simulation as running."""
        self.simulation_running = True
        print("Simulation started.")

    def stop_simulation(self):
        """Stop starting new simulation ticks."""
        self.simulation_running = False
        print("Simulation stopped.")

    def handle_message(self, message):
        """Handle one message received from a Road Node or User Node."""
        if not isinstance(message, dict) or "type" not in message:
            return {"type": "ERROR", "message": "Message must contain a type"}

        message_type = message["type"]
        if message_type == "TICK_DONE":
            return self.handle_tick_done(message)
        if message_type == "VEHICLE_COMPLETED":
            return self.handle_vehicle_completed(message)
        if message_type == "GET_SIMULATION_INFO":
            return self.get_simulation_info()
        if message_type == "SPAWN_VEHICLE":
            return self.spawn_vehicle(message)
        if message_type == "SET_ACCIDENT":
            return self.set_accident(message)

        return {"type": "ERROR", "message": f"Unknown message type: {message_type}"}

    def handle_tick_done(self, message):
        """Record a Road Node's completion of the current tick."""
        road_id = message.get("road_id")
        tick = message.get("tick")

        with self.condition:
            if road_id not in self.roads:
                return {"type": "ERROR", "message": f"Unknown road: {road_id}"}
            if tick != self.current_tick:
                return {
                    "type": "ERROR",
                    "message": (
                        f"Incorrect tick from Road {road_id}. "
                        f"Expected {self.current_tick}, received {tick}."
                    ),
                }

            # A repeated message from a road that already finished is harmless.
            if road_id in self.completed_roads:
                return {
                    "type": "ACKNOWLEDGE",
                    "road_id": road_id,
                    "tick": tick,
                    "duplicate": True,
                }

            if not self.tick_in_progress:
                return {"type": "ERROR", "message": "There is no active tick to complete."}

            self.completed_roads.add(road_id)
            print(
                f"Road {road_id} completed Tick {tick} "
                f"({len(self.completed_roads)}/{len(self.roads)})."
            )

            if self.completed_roads == set(self.roads):
                self.tick_in_progress = False
                self.tick_failed = False
                self.failed_roads.clear()
                print(f"All roads completed Tick {tick}.")
                self.condition.notify_all()

            return {
                "type": "ACKNOWLEDGE",
                "road_id": road_id,
                "tick": tick,
                "duplicate": False,
            }

    def run_tick(self, timeout=30):
        """Broadcast one tick and wait for all Road Nodes to report TICK_DONE.

        A timeout or unreachable Road Node never causes the Coordinator to
        advance automatically. The current tick remains incomplete until every
        configured Road Node reports completion.
        """
        with self.condition:
            # A tick can finish just after a timed wait returns. Report that
            # completion on the next call rather than immediately starting
            # another tick.
            if self.completion_report_pending and not self.tick_in_progress:
                self.completion_report_pending = False
                return {
                    "success": True,
                    "status": "completed",
                    "message": f"Tick {self.current_tick} completed by every Road Node.",
                    **self.get_tick_status(),
                }

            # If a previous call timed out while waiting, keep waiting for that
            # same tick. Never broadcast it a second time.
            resume_existing_tick = self.tick_in_progress
            if resume_existing_tick:
                tick = self.current_tick
            else:
                self.current_tick += 1
                tick = self.current_tick
                self.completed_roads.clear()
                self.failed_roads.clear()
                self.tick_failed = False
                self.tick_in_progress = True
                self.completion_report_pending = True

        if resume_existing_tick:
            finished = self.wait_for_tick(timeout=timeout)
            status = self.get_tick_status()
            if finished:
                with self.condition:
                    self.completion_report_pending = False
                return {
                    "success": True,
                    "status": "completed",
                    "message": f"Tick {tick} completed by every Road Node.",
                    **status,
                }
            if status["failed_roads"]:
                return {
                    "success": False,
                    "status": "road_unavailable",
                    "message": "A Road Node has not accepted or completed this tick.",
                    **status,
                }
            return {
                "success": False,
                "status": "waiting",
                "message": "Still waiting for the remaining Road Nodes.",
                **status,
            }

        print(f"Starting Tick {tick}...")

        # Contact each Road Node using the shared communication helper.
        for road_id, road_config in self.roads.items():
            try:
                response = send_request(
                    road_config["host"],
                    road_config["port"],
                    {"type": "TICK", "tick": tick},
                )

                if not isinstance(response, dict) or (
                    response.get("type") != "TICK_RECEIVED"
                    or response.get("road_id") != road_id
                    or response.get("tick") != tick
                ):
                    reason = f"Unexpected TICK response: {response}"
                    self.record_tick_failure(road_id, reason)
                    continue

                print(f"Road {road_id}: TICK_RECEIVED")

            except (OSError, TimeoutError, ConnectionError, ValueError) as error:
                self.record_tick_failure(road_id, str(error))

        with self.condition:
            if self.tick_failed:
                return {
                    "success": False,
                    "status": "road_unavailable",
                    "message": (
                        "At least one Road Node did not accept the tick. "
                        "The Coordinator will not advance."
                    ),
                    **self.get_tick_status(),
                }

        finished = self.wait_for_tick(timeout=timeout)
        status = self.get_tick_status()

        if finished:
            with self.condition:
                self.completion_report_pending = False
            return {
                "success": True,
                "status": "completed",
                "message": f"Tick {tick} completed by every Road Node.",
                **status,
            }

        return {
            "success": False,
            "status": "waiting",
            "message": "Not all Road Nodes have completed the tick yet.",
            **status,
        }

    def record_tick_failure(self, road_id, reason):
        """Remember a failed Road Node without treating the tick as complete."""
        with self.condition:
            self.tick_failed = True
            self.failed_roads[road_id] = reason
            self.condition.notify_all()
        print(f"Road {road_id} did not accept the tick: {reason}")

    def wait_for_tick(self, timeout=None):
        """Wait for all Road Nodes, or return False when timeout expires."""
        with self.condition:
            if timeout is None:
                while self.tick_in_progress and not self.tick_failed:
                    self.condition.wait()
            else:
                end_time = time.monotonic() + timeout
                while self.tick_in_progress and not self.tick_failed:
                    remaining = end_time - time.monotonic()
                    if remaining <= 0:
                        break
                    self.condition.wait(remaining)

            return not self.tick_in_progress

    def get_tick_status(self):
        """Return a snapshot of the current tick's synchronization state."""
        with self.condition:
            expected = set(self.roads)
            return {
                "tick": self.current_tick,
                "tick_in_progress": self.tick_in_progress,
                "completed_roads": sorted(self.completed_roads),
                "pending_roads": sorted(expected - self.completed_roads),
                "failed_roads": dict(self.failed_roads),
            }

    def handle_vehicle_completed(self, message):
        """Acknowledge and count a vehicle that reached its destination."""
        vehicle_id = message.get("vehicle_id")
        if not vehicle_id:
            return {"type": "ERROR", "message": "vehicle_id is required"}

        with self.condition:
            self.completed_vehicles.add(vehicle_id)

        return {"type": "ACKNOWLEDGE", "vehicle_id": vehicle_id}

    def spawn_vehicle(self, message):
        """Forward a vehicle insertion request to its starting Road Node.

        The vehicle dictionary is supplied by the User Node. If it does not
        include an ID, the Coordinator assigns a unique one.
        """
        road_id = message.get("road_id") or message.get("starting_road")
        vehicle = message.get("vehicle")

        if road_id not in self.roads:
            return {"type": "ERROR", "message": f"Unknown starting road: {road_id}"}
        if not isinstance(vehicle, dict):
            return {"type": "ERROR", "message": "A vehicle dictionary is required"}

        vehicle = dict(vehicle)
        with self.condition:
            vehicle_id = vehicle.get("vehicle_id")
            if not vehicle_id:
                vehicle_id = f"vehicle-{self.next_vehicle_number}"
                self.next_vehicle_number += 1
                vehicle["vehicle_id"] = vehicle_id

            if (
                vehicle_id in self.spawned_vehicle_ids
                or vehicle_id in self.reserved_vehicle_ids
            ):
                return {
                    "type": "ERROR",
                    "message": f"Vehicle ID {vehicle_id} has already been used.",
                }
            # Reserve the ID before the network call so two simultaneous spawn
            # requests cannot introduce the same ID on different roads.
            self.reserved_vehicle_ids.add(vehicle_id)
            tick = self.current_tick

        road_config = self.roads[road_id]
        try:
            response = send_request(
                road_config["host"],
                road_config["port"],
                {"type": "SPAWN_VEHICLE", "vehicle": vehicle, "tick": tick},
            )
        except (OSError, TimeoutError, ConnectionError, ValueError) as error:
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
        """Forward the Road Node's current accident format (active=True/False)."""
        road_id = message.get("road_id")
        active = message.get("active")

        if road_id not in self.roads:
            return {"type": "ERROR", "message": f"Unknown road: {road_id}"}
        if not isinstance(active, bool):
            return {
                "type": "ERROR",
                "message": "SET_ACCIDENT requires active to be True or False.",
            }

        road_config = self.roads[road_id]
        try:
            return send_request(
                road_config["host"],
                road_config["port"],
                {"type": "SET_ACCIDENT", "active": active},
            )
        except (OSError, TimeoutError, ConnectionError, ValueError) as error:
            return {"type": "ERROR", "message": f"Could not contact Road {road_id}: {error}"}

    def get_simulation_info(self):
        """Return basic statistics for the User Interface Node."""
        with self.condition:
            return {
                "type": "SIMULATION_INFO",
                "current_tick": self.current_tick,
                "total_vehicles_spawned": self.total_vehicles_spawned,
                "completed_vehicles": len(self.completed_vehicles),
                "tick_in_progress": self.tick_in_progress,
            }


def main():
    coordinator = Coordinator()
    coordinator.start_server()
    coordinator.start_simulation()

    print("Traffic Conductor Coordinator is ready.")
    print("Start the Road Nodes in separate terminals before running ticks.")

    try:
        while coordinator.simulation_running:
            command = input("Press Enter to run the next tick, or type q to quit: ")
            if command.strip().lower() == "q":
                break

            result = coordinator.run_tick()
            print(result["message"])

            if result["status"] == "road_unavailable":
                print("Fix the unavailable Road Node before trying to continue.")
                break
    except KeyboardInterrupt:
        print("\nCoordinator interrupted.")
    finally:
        coordinator.stop_simulation()


if __name__ == "__main__":
    main()
