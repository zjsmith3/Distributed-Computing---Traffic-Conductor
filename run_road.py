import sys
from config.config import load_network_file
from roads.road_node import RoadNode

def main():
    road_id = sys.argv[1]

    network = load_network_file()

    road = RoadNode(
        road_id,
        network["roads"][road_id],
        network["coordinator"],
        network["roads"],
    )

    road.start()

if __name__ == "__main__":
    main()