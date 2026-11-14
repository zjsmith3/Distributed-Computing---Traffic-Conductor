import _json
from vehicle import Vehicle

def main():

    vehicle = Vehicle(
        vehicle_id = 11037
        origin = "A",
        destination = "D",
        route = ["A", "B", "C", "D"],
        created_tick = 4
    )

    print("original vehicle: ")
    print(vehicle.to_dictionary())

    print("Next road: ", vehicle.get_next_road())

    vehicle.entry_tick = 5
    vehicle.remaining_ticks = 3

    vehicle_data = vehicle.to_dictionary()

    print("\nSerialized Vehicle: ")
    print(vehicle_data)

    json_data = json.dumps(vehicle_data)

    print("\nSerialized JOSN:")
    print(json_data)
    received_vehicle = Vehicle.from_dictionary(received_data)

    print("\nReconstructed Vehicle: ")
    print(received_vehicle.to_dictionary())

    assert received_vehicle.id == vehicle.id
    assert received_vehicle.origin == vehicle.origin
    assert received_vehicle.destination == vehicle.destination
    assert received_vehicle.route == vehicle.route
    assert received_vehicle.route_index == vehicle.route_index
    assert received_vehicle.entry_tick == vehicle.entry_tick
    assert received_vehicle.remaining_ticks == vehicle.remaining_ticks
    assert received_vehicle.created_tick == vehicle.created_tick

    assert received_vehicle.get_next_road() == "B"

    print("\nAll vehicle tests passed")

if __name__ == "_main_":
    main()