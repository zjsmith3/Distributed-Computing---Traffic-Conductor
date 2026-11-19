import heapq
from config.config import load_network_file



def calculate_travel_time(base_time, vehicle_count, capacity):
    if capacity <= 0:
        return float("inf")

    congestion = vehicle_count / capacity

    travel_time = base_time * (1 + 0.15 * congestion**4)

    return travel_time


def find_best_route(start_road, destination_road, road_data, traffic_data=None):
    if start_road not in road_data or destination_road not in road_data:
        return None

    # Use empty traffic data if none is provided
    if traffic_data is None:
        traffic_data = {}

    # Calculate travel time for the starting road
    start_info = road_data[start_road]

    start_time = calculate_travel_time(
        start_info["base_travel_ticks"],
        traffic_data.get(start_road, 0),
        start_info["capacity"]
    )

    queue = [(start_time, start_road, [start_road])]
    best_times = {start_road: start_time}

    while queue:
        total_time, current_road, route = heapq.heappop(queue)

        if total_time > best_times[current_road]:
            continue

        if current_road == destination_road:
            return route, total_time

        for next_road in road_data[current_road]["connections"]:
            road_info = road_data[next_road]

            # Calculate travel time using congestion
            travel_time = calculate_travel_time(
                road_info["base_travel_ticks"],
                traffic_data.get(next_road, 0),
                road_info["capacity"]
            )

            new_time = total_time + travel_time

            if new_time < best_times.get(next_road, float("inf")):
                best_times[next_road] = new_time

                heapq.heappush(
                    queue,
                    (new_time, next_road, route + [next_road])
                )

    return None



if __name__ == "__main__":
    network = load_network_file()
    roads = network["roads"]

    # Example traffic conditions
    traffic = {
        "A": 2,
        "B": 7,
        "C": 10
    }

    # Normal routing
    normal = find_best_route("A", "C", roads)

    # Routing with traffic
    congested = find_best_route("A", "C", roads, traffic)

    print("Normal route:", normal)
    print("Traffic-aware route:", congested)
