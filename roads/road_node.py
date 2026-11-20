"""Road Node implementation for the Traffic Conductor simulation."""

import threading

from communication.protocol import send_request
from communication.server import start_server
from roads.vehicle import Vehicle


class RoadNode:
    """Own the vehicles on one road and advance them once per global tick."""

    def __init__(self, road_id, road_config, coordinator_config, road_config_list):
        self.road_id = road_id
        self.host = road_config["host"]
        self.port = road_config["port"]
        self.capacity = road_config["capacity"]
        self.base_travel_ticks = road_config["base_travel_ticks"]
        self.accident_active = False
        self.accident_multiplier = 2
        self.connections = list(road_config["connections"])

        self.coordinator_host = coordinator_config["host"]
        self.coordinator_port = coordinator_config["port"]
        self.road_config_list = road_config_list

        self.current_tick = 0
        self.completed_tick = 0
        self.tick_in_progress = False
        self.last_tick_error = None
        self.last_notification_error = None
        self.vehicles = {}
        self.lock = threading.RLock()
        self.tick_thread = None

    def handle_message(self, message):
        if not isinstance(message, dict) or not isinstance(message.get("type"), str):
            return {"type": "ERROR", "message": "Message must contain a string type."}

        message_type = message["type"]
        if message_type == "GET_STATUS":
            return self.get_status()
        if message_type == "TICK":
            return self.request_tick(message.get("tick"))
        if message_type == "TRANSFER_VEHICLE":
            return self.receive_vehicle(message)
        if message_type == "SPAWN_VEHICLE":
            return self.spawn_vehicle(message)
        if message_type == "SET_ACCIDENT":
            return self.set_accident(message)
        return {"type": "ERROR", "message": f"Unknown message type: {message_type}"}

    def request_tick(self, tick):
        """Accept a tick only once; duplicate requests never run vehicle logic twice."""
        if type(tick) is not int or tick < 1:
            return {"type": "ERROR", "message": "Tick must be a positive integer."}

        with self.lock:
            if tick == self.current_tick:
                if self.completed_tick >= tick:
                    return {"type": "TICK_COMPLETED", "road_id": self.road_id, "tick": tick}
                if self.tick_in_progress:
                    return {
                        "type": "TICK_RECEIVED",
                        "road_id": self.road_id,
                        "tick": tick,
                        "duplicate": True,
                    }
                if self.last_tick_error:
                    return {
                        "type": "ERROR",
                        "message": f"Tick {tick} previously failed: {self.last_tick_error}",
                    }
                return {"type": "ERROR", "message": "Tick state is incomplete and cannot be replayed safely."}

            if tick != self.current_tick + 1:
                return {
                    "type": "ERROR",
                    "message": f"Expected tick {self.current_tick + 1}, received {tick}.",
                }

            self.current_tick = tick
            self.tick_in_progress = True
            self.last_tick_error = None
            self.last_notification_error = None
            self.tick_thread = threading.Thread(
                target=self._run_tick_worker,
                args=(tick,),
                daemon=True,
                name=f"road-{self.road_id}-tick-{tick}",
            )
            try:
                self.tick_thread.start()
            except RuntimeError as error:
                self.last_tick_error = str(error)
                self.tick_in_progress = False
                return {"type": "ERROR", "message": f"Could not start tick worker: {error}"}

        return {"type": "TICK_RECEIVED", "road_id": self.road_id, "tick": tick}

    def _run_tick_worker(self, tick):
        try:
            self.handle_tick(tick)
        except Exception as error:
            with self.lock:
                self.last_tick_error = str(error)
                self.tick_in_progress = False
            try:
                send_request(
                    self.coordinator_host,
                    self.coordinator_port,
                    {
                        "type": "TICK_FAILED",
                        "road_id": self.road_id,
                        "tick": tick,
                        "message": str(error),
                    },
                )
            except Exception as notify_error:
                with self.lock:
                    self.last_notification_error = str(notify_error)
            return

        # Mark the tick complete before sending the acknowledgement. If the
        # acknowledgement packet is lost, GET_STATUS still lets the Coordinator
        # recover without replaying this road's vehicle updates.
        with self.lock:
            self.completed_tick = tick
            self.tick_in_progress = False

        try:
            send_request(
                self.coordinator_host,
                self.coordinator_port,
                {"type": "TICK_DONE", "road_id": self.road_id, "tick": tick},
            )
        except Exception as error:
            with self.lock:
                self.last_notification_error = str(error)

    def get_status(self):
        with self.lock:
            return {
                "type": "STATUS",
                "road_id": self.road_id,
                "capacity": self.capacity,
                "base_travel_ticks": self.base_travel_ticks,
                "connections": list(self.connections),
                "current_tick": self.current_tick,
                "completed_tick": self.completed_tick,
                "tick_in_progress": self.tick_in_progress,
                "last_tick_error": self.last_tick_error,
                "last_notification_error": self.last_notification_error,
                "vehicle_count": len(self.vehicles),
                "accident_active": self.accident_active,
                "travel_ticks": self.get_travel_ticks(),
            }

    def handle_tick(self, tick):
        ready_vehicles = []
        with self.lock:
            for vehicle_id, vehicle in self.vehicles.items():
                # A vehicle cannot move during the tick on which it entered.
                if vehicle.entry_tick >= tick:
                    continue
                if vehicle.remaining_ticks > 0:
                    vehicle.remaining_ticks -= 1
                if vehicle.remaining_ticks == 0:
                    ready_vehicles.append(vehicle_id)

        for vehicle_id in ready_vehicles:
            self.attempt_sending_vehicle(vehicle_id, tick)

    def attempt_sending_vehicle(self, vehicle_id, tick):
        with self.lock:
            sending_vehicle = self.vehicles.get(vehicle_id)
            if sending_vehicle is None:
                return
            next_road_id = sending_vehicle.get_next_road()
            vehicle_data = sending_vehicle.to_dictionary()

        if next_road_id is None:
            response = send_request(
                self.coordinator_host,
                self.coordinator_port,
                {
                    "type": "VEHICLE_COMPLETED",
                    "vehicle_id": vehicle_id,
                    "road_id": self.road_id,
                    "tick": tick,
                },
            )
            if isinstance(response, dict) and response.get("type") == "ACKNOWLEDGE":
                with self.lock:
                    self.vehicles.pop(vehicle_id, None)
            return

        if next_road_id not in self.connections:
            raise ValueError(
                f"Vehicle {vehicle_id} route requests Road {next_road_id}, "
                f"which is not connected to Road {self.road_id}."
            )

        next_road_config = self.road_config_list[next_road_id]
        response = send_request(
            next_road_config["host"],
            next_road_config["port"],
            {"type": "TRANSFER_VEHICLE", "vehicle": vehicle_data, "tick": tick},
        )
        if isinstance(response, dict) and response.get("type") == "ACCEPTED":
            with self.lock:
                self.vehicles.pop(vehicle_id, None)

    def receive_vehicle(self, message):
        try:
            vehicle_data = message["vehicle"]
            tick = message["tick"]
            if type(tick) is not int or tick < 0:
                raise ValueError("tick must be a nonnegative integer")
            vehicle = Vehicle.from_dictionary(vehicle_data)
        except (KeyError, TypeError, ValueError) as error:
            return {"type": "ERROR", "message": f"Invalid vehicle transfer: {error}"}

        with self.lock:
            if vehicle.vehicle_id in self.vehicles:
                return {"type": "ERROR", "message": "Vehicle already exists on this road."}
            if len(self.vehicles) >= self.capacity:
                return {"type": "REJECTED_FULL", "road_id": self.road_id}

            vehicle.advance_route()
            vehicle.entry_tick = tick
            vehicle.remaining_ticks = self.get_travel_ticks()
            self.vehicles[vehicle.vehicle_id] = vehicle

        return {"type": "ACCEPTED", "road_id": self.road_id}

    def spawn_vehicle(self, message):
        try:
            vehicle_data = message["vehicle"]
            tick = message["tick"]
            if type(tick) is not int or tick < 0:
                raise ValueError("tick must be a nonnegative integer")
            vehicle = Vehicle.from_dictionary(vehicle_data)
        except (KeyError, TypeError, ValueError) as error:
            return {"type": "ERROR", "message": f"Invalid vehicle: {error}"}

        with self.lock:
            if vehicle.vehicle_id in self.vehicles:
                return {"type": "ERROR", "message": "Vehicle already exists on this road."}
            if len(self.vehicles) >= self.capacity:
                return {"type": "REJECTED_FULL", "road_id": self.road_id}
            vehicle.entry_tick = tick
            vehicle.remaining_ticks = self.get_travel_ticks()
            self.vehicles[vehicle.vehicle_id] = vehicle

        return {"type": "ACCEPTED", "road_id": self.road_id}

    def get_travel_ticks(self):
        if self.accident_active:
            return self.base_travel_ticks * self.accident_multiplier
        return self.base_travel_ticks

    def set_accident(self, message):
        active = message.get("active")
        if not isinstance(active, bool):
            return {"type": "ERROR", "message": "active must be True or False."}
        with self.lock:
            self.accident_active = active
        return {"type": "ACCIDENT_UPDATED", "road_id": self.road_id, "accident_active": active}

    def start(self):
        print(f"Road {self.road_id} listening on port {self.port}")
        start_server(self.host, self.port, self.handle_message)
