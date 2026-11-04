import _json
from vehicle import vehicle

def main():

    vehicle = Vehicle(
        vehicle_id = 101
        origin = "A",
        destination = "D",
        route = ["A", "B", "C", "D"],
        created_tick = 4
    )

    print("original vehicle: ")
    print(vehicle)


    print("\nCurrent Road: ", vehicle.get_current_road())
    print("Next road: ", vehicle.get_next_road())
    print("Destination Reached: ", vehicle.has_reached_destination())

    vehicle.entry_tick = 5
    vehicle.remaining_ticks = 3

    json_data = json.dumps(vehicle.to_dict())

    print("\nSerialized Vehicle: ")
    print(json_data)

    received_data = json.loads(json_data)
    received_vehicle = Vehicle.from_dict(received_data)

    print("\nReconstructed Vehicle: ")
    print(received_vehicle)

    assert received_vehicle.id == vehicle.id
    assert received_vehicle.route == vehicle.route
    assert received_vehicle.entry_tick == vehicle.entry_tick
    assert received_vehicle.remaining_ticks == vehicle.remaining_ticks

    print("\nAll vehicle tests passed")

if __name__ == "_main_":
    main()