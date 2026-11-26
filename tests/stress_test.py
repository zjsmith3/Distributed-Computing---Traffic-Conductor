"""100-tick real-TCP Traffic Conductor stress test.

Run from the repository root:
    python stress_test.py --config config/network.json --ticks 100 --vehicles 60

Starts 1 coordinator + all configured road TCP servers in this process, each
serving requests in threads. Does not launch separate OS processes or test
multi-machine networking. Uses the actual Coordinator/RoadNode/protocol code.
"""
import argparse
from collections import deque
import json
from pathlib import Path
import socketserver
import sys
import threading
import time

from communication.server import handle_connection
from coordinator.coordinator import Coordinator
from roads.road_node import RoadNode


class NodeServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False

    def __init__(self, address, handler):
        self.message_handler = handler
        super().__init__(address, NodeRequestHandler)


class NodeRequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        handle_connection(self.request, self.server.message_handler)


def route_to_destination(roads, origin, destination):
    """Find a valid directed route; this is test setup, not the project router."""
    queue = deque([[origin]])
    visited = {origin}
    while queue:
        route = queue.popleft()
        last = route[-1]
        if last == destination:
            return route
        for neighbor in roads[last]['connections']:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(route + [neighbor])
    return None


def main():
    parser = argparse.ArgumentParser(description='Run a timed real-TCP Traffic Conductor stress test.')
    parser.add_argument('--config', default='config/network.json', help='Path to JSON network configuration')
    parser.add_argument('--ticks', type=int, default=100)
    parser.add_argument('--vehicles', type=int, default=60, help='Vehicles to spawn before tick 1')
    parser.add_argument('--timeout', type=float, default=30, help='Seconds allowed per tick')
    args = parser.parse_args()
    if args.ticks < 1 or args.vehicles < 0 or args.timeout <= 0:
        parser.error('ticks must be positive, vehicles nonnegative, timeout positive')

    with Path(args.config).open(encoding='utf-8') as file:
        network = json.load(file)
    roads_config = network['roads']
    coordinator = Coordinator(network=network)
    coordinator.target_vehicle_count = args.vehicles
    # Keep the workload fixed and reproducible instead of spawning extra random cars.
    roads = {
        road_id: RoadNode(road_id, cfg, network['coordinator'], roads_config)
        for road_id, cfg in roads_config.items()
    }

    servers = []
    threads = []
    start = time.perf_counter()
    try:
        endpoints = [(network['coordinator'], coordinator.handle_message)]
        endpoints += [(cfg, roads[road_id].handle_message) for road_id, cfg in roads_config.items()]
        for cfg, handler in endpoints:
            server = NodeServer((cfg['host'], cfg['port']), handler)
            servers.append(server)
        for server in servers:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            threads.append(thread)

        destination = list(roads_config)[-1]
        routes = [route_to_destination(roads_config, road_id, destination) for road_id in roads_config]
        routes = [route for route in routes if route and len(route) > 1]
        if args.vehicles and not routes:
            raise RuntimeError(f'No origin can reach destination {destination}.')

        spawned = 0
        attempts = 0
        # Try different starting roads to respect their capacities.
        while spawned < args.vehicles and attempts < max(100, args.vehicles * len(routes) * 2):
            route = routes[attempts % len(routes)]
            attempts += 1
            vehicle = {
                'origin': route[0], 'destination': route[-1], 'route': route,
                'route_index': 0, 'remaining_ticks': 0,
                'created_tick': 0, 'entry_tick': -1,
            }
            response = coordinator.spawn_vehicle({'road_id': route[0], 'vehicle': vehicle})
            if response.get('type') == 'ACCEPTED':
                spawned += 1
            elif response.get('type') != 'REJECTED_FULL':
                raise RuntimeError(f'Spawn failed on {route[0]}: {response}')
            if attempts >= len(routes) and spawned == 0:
                raise RuntimeError('Could not spawn any vehicles; check road capacities.')
            # If all eligible origin roads are full, additional attempts cannot help.
            if attempts % len(routes) == 0 and all(
                roads[r[0]].get_status()['vehicle_count'] >= roads_config[r[0]]['capacity']
                for r in routes
            ):
                break

        print(f'\nNETWORK: {len(roads)} roads, {sum(len(c["connections"]) for c in roads_config.values())} directed connections')
        print(f'WORKLOAD: {args.ticks} ticks, {spawned}/{args.vehicles} vehicles spawned, destination {destination}')
        if spawned < args.vehicles:
            print('WARNING: Not all requested vehicles fit on starting roads.')
        print('TIMING: Includes real localhost TCP requests, tick processing, and synchronization.')
        tick_times = []
        tick_start = time.perf_counter()
        failure = None
        for number in range(1, args.ticks + 1):
            before = time.perf_counter()
            result = coordinator.run_tick(timeout=args.timeout)
            elapsed = time.perf_counter() - before
            tick_times.append(elapsed)
            if not result.get('success') or result.get('status') != 'completed':
                failure = result
                print(f'\nFAILED at requested tick {number}: {result}')
                break
            if number == 1 or number % 10 == 0 or number == args.ticks:
                info = coordinator.get_simulation_info()
                print(f'PROGRESS: {number}/{args.ticks} ticks | last {elapsed:.3f}s | '
                      f'completed vehicles {info["completed_vehicles"]} | active {info["active_vehicles"]}')
        total_ticks_time = time.perf_counter() - tick_start
        info = coordinator.get_simulation_info()
        total_road_vehicles = sum(len(road.vehicles) for road in roads.values())
        tracked_active = info['active_vehicles']
        print('\n========== STRESS TEST REPORT ==========')
        print(f'Completed ticks:     {len(tick_times) if not failure else len(tick_times)-1}/{args.ticks}')
        print(f'Tick execution time: {total_ticks_time:.3f} seconds')
        print(f'Total elapsed time:  {time.perf_counter()-start:.3f} seconds (includes setup/spawning)')
        print(f'Average tick time:   {sum(tick_times)/len(tick_times):.3f} seconds')
        print(f'Slowest tick:        {max(tick_times):.3f} seconds')
        print(f'Vehicles spawned:    {info["total_vehicles_spawned"]}')
        print(f'Vehicles completed:  {info["completed_vehicles"]}')
        print(f'Vehicles active:     {tracked_active}')
        print(f'Vehicles on roads:   {total_road_vehicles}')
        print(f'Vehicle count match: {"YES" if tracked_active == total_road_vehicles else "NO (investigate)"}')
        print(f'Result:              {"PASS" if not failure and tracked_active == total_road_vehicles else "FAIL"}')
        return 0 if not failure and tracked_active == total_road_vehicles else 1
    finally:
        for server in servers:
            server.shutdown() if threads else None
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(f'STRESS TEST ERROR: {error}', file=sys.stderr)
        sys.exit(1)
