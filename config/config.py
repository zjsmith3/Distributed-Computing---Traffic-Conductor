import json
from pathlib import Path

#purpose of this script is to just get the network file where we house communication information for each road node. 

config_path = Path(__file__).resolve().parent / "network.json" #makes it consistently run no matter where ya run the code from. 

def load_network_file():
    with open(config_path, "r") as file:
        network = json.load(file)

    return network 

