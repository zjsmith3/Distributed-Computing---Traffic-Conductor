"""Road Node implementation for the Traffic Conductor simulation."""

import threading

from communication.protocol import send_request
from communication.server import start_server
from roads.vehicle import Vehicle
from user.routing import get_live_traffic, reroute_for_accident

#Originally created by Zachary Smith 11/10. 
#Code Edited by Het Patel 11/19

class RoadNode:
    """Own the vehicles on one road and advance them once per global tick."""

    def __init__(self, road_id, road_config, coordinator_config, road_config_list):
        #Road node variables:
        self.road_id = road_id
        self.host = road_config["host"]
        self.port = road_config["port"]
        self.capacity = road_config["capacity"]
        self.base_travel_ticks = road_config["base_travel_ticks"]
        self.accident_active = False
        self.accident_multiplier = 2
        self.connections = list(road_config["connections"])

        #Variables for Coordinator address. 
        self.coordinator_host = coordinator_config["host"]
        self.coordinator_port = coordinator_config["port"]
        self.road_config_list = road_config_list

        #more Variables for functions. 
        self.current_tick = 0
        self.completed_tick = 0
        self.tick_in_progress = False
        self.last_tick_error = None
        self.last_notification_error = None
        self.vehicles = {}
        self.lock = threading.RLock()
        self.tick_thread = None

    def handle_message(self, message):
    #This function's job is where incoming messages are handled. 
        if not isinstance(message, dict) or not isinstance(message.get("type"), str):
            return {"type": "ERROR", "message": "Message must contain a string type."}

        message_type = message["type"]
        if message_type == "GET_STATUS": #Road sends information about it's current state.
            return self.get_status()
        if message_type == "TICK": #The road handles the tick. 
            return self.request_tick(message.get("tick"))
        if message_type == "TRANSFER_VEHICLE": #The road is recieving a vehicle. 
            return self.receive_vehicle(message)
        if message_type == "SPAWN_VEHICLE": #The coordinator is spawning a vehicle in the road. 
            return self.spawn_vehicle(message)
        if message_type == "SET_ACCIDENT": #An accident is being set upon this road. 
            return self.set_accident(message)
        return {"type": "ERROR", "message": f"Unknown message type: {message_type}"} 
        #If the message doesn't fit under any of these categories, this is replied.

    def request_tick(self, tick): #A validation function to make sure the tick request is a valid one. 
        """Accept a tick only once; duplicate requests never run vehicle logic twice."""
        if type(tick) is not int or tick < 1:
            return {"type": "ERROR", "message": "Tick must be a positive integer."}

        with self.lock: #grabbing the lock to eliminate race conditions
            if tick == self.current_tick:
                if self.completed_tick >= tick: #Send tick completed if it's tick is done. 
                    return {"type": "TICK_COMPLETED", "road_id": self.road_id, "tick": tick}
                if self.tick_in_progress:  #Reply saying it's already mid tick. 
                    return {
                        "type": "TICK_RECEIVED",
                        "road_id": self.road_id,
                        "tick": tick,
                        "duplicate": True,
                    }
                if self.last_tick_error: #Send a message saying it's last tick had an error occur. 
                    return {
                        "type": "ERROR",
                        "message": f"Tick {tick} previously failed: {self.last_tick_error}",
                    }
                return {"type": "ERROR", "message": "Tick state is incomplete and cannot be replayed safely."}

            if tick != self.current_tick + 1: #making sure the message is sending the correct tick. 
                return {
                    "type": "ERROR",
                    "message": f"Expected tick {self.current_tick + 1}, received {tick}.",
                }

            #updating variables. 
            self.current_tick = tick
            self.tick_in_progress = True
            self.last_tick_error = None
            self.last_notification_error = None
            #creating thread to handle the tick. 
            self.tick_thread = threading.Thread(
                target=self._run_tick_worker,
                args=(tick,),
                daemon=True,
                name=f"road-{self.road_id}-tick-{tick}",
            )
            try: #running thread that handles tick. 
                self.tick_thread.start()
            except RuntimeError as error:
                self.last_tick_error = str(error)
                self.tick_in_progress = False
                return {"type": "ERROR", "message": f"Could not start tick worker: {error}"}

        return {"type": "TICK_RECEIVED", "road_id": self.road_id, "tick": tick} #sending acknolagement. 

    def _run_tick_worker(self, tick): #Handle tick wrapper that handles errors. 
        try:#attempt to run tick. 
            self.handle_tick(tick)
        except Exception as error: #if fails, print exception
            with self.lock:
                self.last_tick_error = str(error)
                self.tick_in_progress = False
            try: #sending message out that it failed to the coordinator. 
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
        #temp variable to handle vehicles ready to go (RTG)
        ready_vehicles = []
        with self.lock: #we use the lock because it's changing things about the vehicles.
            for vehicle_id, vehicle in self.vehicles.items():
                # A vehicle cannot move during the tick on which it entered.
                if vehicle.entry_tick >= tick:
                    continue
                #decreasing travel time
                if vehicle.remaining_ticks > 0:
                    vehicle.remaining_ticks -= 1
                if vehicle.remaining_ticks == 0:
                    #if vehicle is RTG, add to list. 
                    ready_vehicles.append(vehicle_id)

        for vehicle_id in ready_vehicles:
            self.attempt_sending_vehicle(vehicle_id, tick)

    def attempt_sending_vehicle(self, vehicle_id, tick):
        with self.lock: #using lock because modyfing things about itself, specifically vehicles in it. 
            sending_vehicle = self.vehicles.get(vehicle_id)
            if sending_vehicle is None: #null protection.
                return
            next_road_id = sending_vehicle.get_next_road() # get the id the vehicle will be going to. 
            vehicle_data = sending_vehicle.to_dictionary() # get the data of the vehicle that's going. 

        if next_road_id is None:  #essentially, if next road id is None, the vehicle is at it's destination. So the coord is notified.
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
            if isinstance(response, dict) and response.get("type") == "ACKNOWLEDGE": #remove vehicle when it's done.
                with self.lock:
                    self.vehicles.pop(vehicle_id, None)
            return

        # Check for accidents before moving the vehicle
        remaining_roads = vehicle_data["route"][vehicle_data["route_index"] + 1:]
        accident_found = False

        for road_id in remaining_roads:
            road_info = self.road_config_list.get(road_id)

            # Skip roads that are not in config
            if road_info is None:
                continue


            try:
                status = send_request(
                    road_info["host"],
                    road_info["port"],
                    {"type": "GET_STATUS"}
                )

                if status.get("type") == "STATUS" and status.get("accident_active"):
                    accident_found = True
                    break

            except (OSError, ConnectionError) as error:
                print(f"Could not check accident on {road_id}: {error}")

        # Check if other route is faster
        if accident_found:
            traffic = get_live_traffic(self.road_config_list)

            new_route = reroute_for_accident(
                vehicle_data["route"],
                vehicle_data["route_index"],
                self.road_config_list,
                traffic
            )

            # Update the vehicle route
            if new_route != vehicle_data["route"]:
                rerouted = False

                with self.lock:
                    vehicle = self.vehicles.get(vehicle_id)

                    if (vehicle is not None
                            and vehicle.route == vehicle_data["route"]
                            and vehicle.route_index == vehicle_data["route_index"]):
                        vehicle.route = new_route
                        vehicle_data = vehicle.to_dictionary()
                        next_road_id = vehicle.get_next_road()
                        rerouted = True

                if rerouted:
                    print(
                        f"Vehicle {vehicle_id} rerouted on {self.road_id}: "
                        f"{new_route}"
                    )

        # Get the latest vehicle data before transferring
        with self.lock:
            vehicle = self.vehicles.get(vehicle_id)

            if vehicle is None:
                return

            vehicle_data = vehicle.to_dictionary()
            next_road_id = vehicle.get_next_road()

        if next_road_id not in self.connections: #catching an error if the vehicle's next destination isn't an option.
            raise ValueError(
                f"Vehicle {vehicle_id} route requests Road {next_road_id}, "
                f"which is not connected to Road {self.road_id}."
            )

        next_road_config = self.road_config_list[next_road_id] #gets the config for address of road vehicle going to. 
        response = send_request( #sending the destination road the vehicle. 
            next_road_config["host"],
            next_road_config["port"],
            {"type": "TRANSFER_VEHICLE", "vehicle": vehicle_data, "tick": tick},
        )
        if isinstance(response, dict) and response.get("type") == "ACCEPTED":
            with self.lock:
                self.vehicles.pop(vehicle_id, None)

    def receive_vehicle(self, message): #Function for when the road recieves a message of another road that it's sending a vehicle.
        try:
            vehicle_data = message["vehicle"] #Get's the recieving vehicle's information.
            tick = message["tick"] #Grabs the tick the message was sent on., 
            if type(tick) is not int or tick < 0: #validate's tick. 
                raise ValueError("tick must be a nonnegative integer")
            vehicle = Vehicle.from_dictionary(vehicle_data) #creating vehicle object.
        except (KeyError, TypeError, ValueError) as error: #validating vehicle. 
            return {"type": "ERROR", "message": f"Invalid vehicle transfer: {error}"} 

        with self.lock: #grabbing it's lock. 
            if vehicle.vehicle_id in self.vehicles: #duplicate vehicle protection.
                return {"type": "ERROR", "message": "Vehicle already exists on this road."} 
            if len(self.vehicles) >= self.capacity: #capacity check. 
                return {"type": "REJECTED_FULL", "road_id": self.road_id}

            #vehicle data upkeep when accepted. 
            vehicle.advance_route() #tell's the vehicle to advance it's route index. 
            vehicle.entry_tick = tick #puts the entry tick of the vehicle on it. 
            vehicle.remaining_ticks = self.get_travel_ticks() #sets the travel time on the vehicle. 
            self.vehicles[vehicle.vehicle_id] = vehicle #adds vehicle to it's dictionary of vehicles. 

        return {"type": "ACCEPTED", "road_id": self.road_id} #send accept reply. 

    def spawn_vehicle(self, message): #For when coord spawns a vehicle on the road. 
        try:
            #getting message data
            vehicle_data = message["vehicle"] 
            tick = message["tick"]
            if type(tick) is not int or tick < 0: #validating tick 
                raise ValueError("tick must be a nonnegative integer")
            vehicle = Vehicle.from_dictionary(vehicle_data) #creating vehicle object.
        except (KeyError, TypeError, ValueError) as error: #vehicle validation. 
            return {"type": "ERROR", "message": f"Invalid vehicle: {error}"}

        with self.lock: #grabbing lock, 
            if vehicle.vehicle_id in self.vehicles: #duplication check.
                return {"type": "ERROR", "message": "Vehicle already exists on this road."}
            if len(self.vehicles) >= self.capacity: #capacity check.
                return {"type": "REJECTED_FULL", "road_id": self.road_id}
            #setting data of vehicle. 
            vehicle.entry_tick = tick 
            vehicle.remaining_ticks = self.get_travel_ticks()
            self.vehicles[vehicle.vehicle_id] = vehicle

        return {"type": "ACCEPTED", "road_id": self.road_id} #send accept msg. 

    def get_travel_ticks(self): #travel ticks getter. 
        if self.accident_active:
            return self.base_travel_ticks * self.accident_multiplier
        return self.base_travel_ticks

    def set_accident(self, message): #quick function that just sets accident mode on the road node. 
        active = message.get("active")
        if not isinstance(active, bool):
            return {"type": "ERROR", "message": "active must be True or False."}
        with self.lock:
            self.accident_active = active
        return {"type": "ACCIDENT_UPDATED", "road_id": self.road_id, "accident_active": active}

    def start(self): #start function for the road. 
        print(f"Road {self.road_id} listening on port {self.port}")
        start_server(self.host, self.port, self.handle_message)
