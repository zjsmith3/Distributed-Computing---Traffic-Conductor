import json
from pathlib import Path

#purpose of this script is to just get the network file where we house communication information for each road node. 

config_path = Path(__file__).resolve().parent / "network.json" #makes it consistently run no matter where ya run the code from. 

def load_network_file():
    with open(config_path, "r") as file:
        network = json.load(file)

    validate_network(network)

    return network 

#A function that confirms that the config file is set up correctly for when we use different maps. 
def validate_network(network):
    #for validating ports 
    used_ports = set()


    # Validate coordinator port
    coordinator_port = network["coordinator"]["port"]

    if not (1024 <= coordinator_port <= 65535):
        raise ValueError("Coordinator's port is invalid")

    used_ports.add(coordinator_port)

    for road_ID, road_config in network["roads"].items():
        port = road_config["port"]

        #1. Check ports

        #Validate port numbers are vlid
        if not (1024 <= road_config["port"] <= 65535):
            raise ValueError(f"{road_ID}'s port is invalid")
        #Validate that the prots are not duplicated of another's
        if port in used_ports:
            raise ValueError(f"Duplicate port {port} found on Road {road_ID}")

        used_ports.add(port)

        #2. Check connections
        for connection in road_config["connections"]:
            connection_exists = False
            for other_road_ID in network["roads"]:
                if other_road_ID == connection:
                    connection_exists = True
                    break
            if not connection_exists:
                raise ValueError(f"{road_ID}'s connection {connection} does not actually exist")

        #3. validate capacity
        if road_config["capacity"] <= 0:
            raise ValueError(f"{road_ID}'s capacity is not greater than 0")

        #4. Validate travel time
        if road_config["base_travel_ticks"] <= 0:
            raise ValueError(f"{road_ID}'s travel time is not greater than 0")

       

        
        


        
