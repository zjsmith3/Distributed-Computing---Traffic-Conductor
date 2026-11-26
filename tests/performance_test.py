import time
import csv
import statistics

from communication.protocol import send_request
from config.config import load_network_file


network = load_network_file()

COORDINATOR_HOST = network["coordinator"]["host"]
COORDINATOR_PORT = network["coordinator"]["port"]

NUMBER_OF_TICKS = 25

def send_coordinator_request(message):
    return send_request(COORDINATOR_HOST, COORDINATOR_PORT, message)

def measure_request_latency():
    """Measure Coordinator TCP request and response latency."""

    start = time.perf_counter()

    response = send_coordinator_request({"type": "GET_SIMULATION_INFO"})

    elapsed = time.perf_counter() - start

    if response.get("type") != "SIMULATION_INFO":
        raise RuntimeError(f"Unexpected response: {response}")

    return elapsed

def wait_for_tick(expected_tick, timeout = 30):
    """Wait until every Road Node finishes the requested tick."""

    start = time.perf_counter()

    while time.perf_counter() - start < timeout:

        status = send_coordinator_request({"type": "GET_SIMULATION_INFO"})

        if status.get("current_tick") == expected_tick:
            if status.get("failed_roads"):
                raise RuntimeError(f"Road failures: {status['failed_roads']}")

            if not status.get("tick_in_progress"):
                return status
    
        time.sleep(0.01)

    raise TimeoutError(f"Tick {expected_tick} did not finish in time.")

def measure_tick_performance():
    """Measure the time required to complete simulation ticks."""

    tick_results = []

    initial_status = send_coordinator_request({"type": "GET_SIMULATION_INFO"})

    previous_tick =  initial_status["current_tick"]

    for _ in range(NUMBER_OF_TICKS):
        start = time.perf_counter()

        response = send_coordinator_request({"type": "ADVANCE_TICK"})

        if response.get("type") != "TICK_STARTED":
            raise RuntimeError(f"Could not start tick: {response}")

        expected_tick = previous_tick + 1

        status = wait_for_tick(expected_tick)

        elapsed = time.perf_counter() - start

        tick_results.append(elapsed)

        previous_tick = expected_tick

        print (f"Tick {expected_tick}: "
               f"{elapsed:.4f} seconds")

    return tick_results

def calculate_metrics(latencies, tick_times):
    
    average_latency = statistics.mean(latencies)

    average_tick_time = statistics.mean(tick_times)

    total_tick_time = sum(tick_times)

    throughput = len(tick_times) / total_tick_time

    p95_latency = statistics.quantiles(latencies, n = 100) [94]

    print("\n !PERFORMANCE RESULTS!")
    print(f"Average request latency: {average_latency:.4f}s")
    print(f"P95 request latency: {p95_latency:.4f}s")
    print(f"Average tick time: {average_tick_time:.4f}s")
    print(f"Tick throughput: {throughput:.2f} ticks/second")

def save_results(latencies, tick_times):

    with open("performance_results.csv", "w", newline = "") as file:
                writer = csv.writer(file)

                writer.writerow(["Test", "Iteration", "Latency_Seconds"])

                for index, value in enumerate(latencies):
                    writer.writerow(["Coordinator Request", index + 1, value])

                for index, value in enumerate(tick_times):
                    writer.writerow(["Simulation Tick",index + 1,value])

def main():

     print("Starting Traffic Conductor Performance Test")

     latencies = [measure_request_latency() for _ in range(100)]

     tick_times = measure_tick_performance()

     calculate_metrics(latencies, tick_times)

     save_results(latencies, tick_times)

     print("\nResults saved to performance_results.csv")

if __name__ == "__main__":
     main()




        
