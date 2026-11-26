import heapq
from communication.protocol import send_request

# Get traffic information from all road nodes
def get_live_traffic(road_data):
    traffic_data = {}

    for road_id, road_info in road_data.items():
        try:
            #ask the road for its status
            response = send_request(
                road_info["host"],
                road_info["port"],
                {"type": "GET_STATUS"}
            )

            if response.get("type") == "STATUS":
                traffic_data[road_id] = response

        except (OSError, ConnectionError) as error:
            print(f"Could not reach Road {road_id}: {error}")

    return traffic_data

# Calculate estimated travel time with BPR formula
def calculate_travel_time(base_time, vehicle_count, capacity):

    # Protect division by 0
    if capacity <= 0:
        return float("inf")

    congestion = vehicle_count / capacity

    # Formula based on the BPR function
    travel_time = base_time * (1 + 0.15 * congestion**4)

    return travel_time

# Find the fastest route using Djikstra's Algorithm
def find_best_route(start_road, destination_road, road_data, traffic_data=None):
    # To make sure that the starting road and destination is available
    if start_road not in road_data or destination_road not in road_data:
        return None

    # None means we are intentionally using normal road conditions
    use_live_data = traffic_data is not None

    if traffic_data is None:
        traffic_data = {}

    def get_road_cost(road_id):
        road_info = road_data[road_id]
        status = traffic_data.get(road_id)

        if status is None:
            # Live data was requested, but this road has no status
            if use_live_data:
                return float("inf")

            # No live data requested, so use normal travel times
            return calculate_travel_time(
                road_info["base_travel_ticks"],
                0,
                road_info["capacity"]
            )

        return calculate_travel_time(
            status["travel_ticks"],
            status["vehicle_count"],
            status["capacity"]
        )

    # Calculate the starting road's travel time
    start_time = get_road_cost(start_road)

    if start_time == float("inf"):
        return None

    # Queue stores travel time, current road, and route taken
    queue = [(start_time, start_road, [start_road])]

    # Keep track of the lowest travel time to each road
    best_times = {start_road: start_time}

    while queue:
        # Check the road with the lowest total travel time
        total_time, current_road, route = heapq.heappop(queue)

        if total_time > best_times[current_road]:
            continue

        # Return the route once we reach the destination
        if current_road == destination_road:
            return route, total_time
        
        # Check every road connected to the current road
        for next_road in road_data[current_road]["connections"]:
            if next_road not in road_data:
                continue

            travel_time = get_road_cost(next_road)

            # Skip roads that cannot be used
            if travel_time == float("inf"):
                continue

            # Add the next road's travel time to the total
            new_time = total_time + travel_time

            # Only update if this route is faster than the previous one
            if new_time < best_times.get(next_road, float("inf")):
                best_times[next_road] = new_time

                # Add the new route to the queue for checking
                heapq.heappush(
                    queue,
                    (new_time, next_road, route + [next_road])
                )

    return None


# Update the route if an accident makes another path faster
def reroute_for_accident(route, route_index, road_data, traffic_data):
    # Check if the route and index are valid
    if not route or not 0 <= route_index < len(route):
        return route

    current_road = route[route_index]
    destination = route[-1]
    remaining_route = route[route_index:]

    # Check if there is an accident on the remaining roads
    accident_ahead = any(
        traffic_data.get(road_id, {}).get("accident_active", False)
        for road_id in remaining_route[1:]
    )

    if not accident_ahead:
        return route

    # Find another route using the current traffic information
    best = find_best_route(
        current_road, destination, road_data, traffic_data
    )

    if best is None:
        return route

    new_remaining, new_time = best

    # Calculate the original route's travel time
    old_time = 0

    for road_id in remaining_route:
        status = traffic_data.get(road_id)

        if status is None:
            old_time = float("inf")
            break

        old_time += calculate_travel_time(
            status["travel_ticks"],
            status["vehicle_count"],
            status["capacity"]
        )

    # Only change the route if the new route is faster
    if new_time >= old_time or new_remaining == remaining_route:
        return route

    # Keep the roads the vehicle has already traveled
    return route[:route_index] + new_remaining
