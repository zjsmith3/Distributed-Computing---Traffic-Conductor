import threading
from communication.protocol import send_request

class RoadNode:

    def __init__(self, road_id, road_config, coordinator_config, road_config_list):
        #Information below is what defines the road node.
        self.road_id = road_id
        self.port = road_config["port"]
        self.capacity = road_config["capacity"]
        self.base_travel_ticks = road_config["base_travel_ticks"]
        self.connections = road_config["connections"]

        #coordinator contact info
        self.coordinator_host = coordinator_config["host"]
        self.coordinator_port = coordinator_config["port"]

        #road config list
        self.road_config_list = road_config_list

        #information below just defines the variables in which explain the state of the road
        self.current_tick = 0
        self.vehicles = {}
        self.lock = threading.Lock() #passing cars along can be a race condition. 


    #This function defines what it does with certain messages
    def handle_message(self, message):
        message_type = message["type"]

        if message_type == "GET_STATUS":
            return self.get_status()
        elif message_type == "TICK": 
            tick = message["tick"]

            with self.lock:
                if tick != self.current_tick + 1:
                    return {
                        "type": "ERROR",
                        "message": "Tick number not expected"
                    }

                self.current_tick = tick

            thread = threading.Thread(target=self.handle_tick, args=(tick,), daemon=True)
            thread.start()

            return {
                "type": "TICK_RECEIVED",
                "road_id": self.road_id,
                "tick": tick
            }

        else:
            return {
                "type": "ERROR",
                "message": f"Unknown message type: {message_type}"
            }

    def get_status(self):
        with self.lock:
            return {
                "type": "STATUS",
                "road_id": self.road_id,
                "capacity": self.capacity,
                "base_travel_ticks":self.base_travel_ticks,
                "connections":self.connections,
                "current_tick": self.current_tick,
                "vehicle_count": len(self.vehicles),
            }
        
    def handle_tick(self, tick):
        #temp var to track which vehicles are RTG (ready to go :) )
        readytogo_vehicles = []
        #we use the lock because it's changing things about the vehicles in 
        with self.lock:
            for vehicle_id, vehicle in self.vehicles.items():

                #Vehicles cannot move on the tick they entered.
                if vehicle.entry_tick >= tick:
                    continue

                #decrease travel time on vehicles not RTG
                if vehicle.remaining_ticks > 0:
                    vehicle.remaining_ticks -= 1

                #remember vehicles that are RTG
                if vehicle.remaining_ticks == 0:
                    readytogo_vehicles.append(vehicle_id)

        #now that it's done updating it's own vehicles, start sending processes
        for vehicle_id in readytogo_vehicles:
            self.attempt_sending_vehicle(vehicle_id, tick)

        #send coordinator the "I'm done" msg
        response = send_request(
            self.coordinator_host,
            self.coordinator_port,
            {
                "type": "TICK_DONE",
                "road_id": self.road_id,
                "tick": tick
            }
        )

        return response

    def attempt_sending_vehicle(self, vehicle_id, tick):
        #get the vehicle from the list
        with self.lock: 
            sending_vehicle = self.vehicles.get[vehicle_id]

            if sending_vehicle is None:
                return
            #IMPORTANT: WE MIGHT NEED TO PASS SOMETHING INTO THIS FUNCTION WHEN IT'S MADE POSSIBLY. 
            next_road_id = sending_vehicle.get_next_road()
            #IMPORTANT: MAKE SURE IT MATCHES WITH LATER VEHICLE IMPLEMENTATION. 
            vehicle_data = sending_vehicle.to_dictionary()

        #if the vehicle is done travleing
        if next_road_id is None:
            response = send_request(
                self.coordinator_host,
                self.coordinator_port,
                {
                    "type": "VEHICLE_COMPLETED",
                    "vehicle_id": vehicle_id,
                    "road_id": self.road_id,
                    "tick": tick
                }
            )

            if response["type"] == "ACKNOWLEDGE":
                with self.lock:
                    self.vehicles.pop(vehicle_id, None)

            return

        #a quick check to make sure the car is trying to go somewhere it can actually go. 
        if next_road_id not in self.connections:
            return

        #if the road is going to another road, get the next road's contact info essentially
        next_road_config = self.road_config_list[next_road_id]

        next_road_host = next_road_config["host"]
        next_road_port = next_road_config["port"]

        #send the request
        response = send_request(
            next_road_host,
            next_road_port,
            {
                "type": "TRANSFER_VEHICLE",
                "vehicle": vehicle_data,
                "tick": tick
            }
        )

        #remove vehicle if the transfer was accepted.
        if response["type"] == "ACCEPTED":
            with self.lock:
                self.vehicles.pop(vehicle_id, None)

        # If rejected, do nothing with the vehicle. 


            

    