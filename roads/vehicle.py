"""Vehicle model used by Traffic Conductor Road Nodes.

A vehicle carries its complete route as a list of road IDs. ``route_index``
points to the road it currently occupies. Road Nodes handle all network
communication and update ``entry_tick``/``remaining_ticks`` when the vehicle
enters a road.
"""


class Vehicle:
    """A vehicle travelling along a predetermined route through the network."""

    def __init__(
        self,
        vehicle_id,
        origin,
        destination,
        route,
        created_tick=0,
        remaining_ticks=0,
        route_index=0,
        entry_tick=-1,
    ):
        # IDs may be integers or strings. The Coordinator currently generates
        # string IDs, while an older Vehicle draft used integer IDs.
        if isinstance(vehicle_id, bool) or not isinstance(vehicle_id, (int, str)):
            raise ValueError("Vehicle ID must be a string or integer.")
        if isinstance(vehicle_id, str) and not vehicle_id.strip():
            raise ValueError("Vehicle ID cannot be empty.")

        if not isinstance(origin, str) or not origin.strip():
            raise ValueError("Origin is required.")
        if not isinstance(destination, str) or not destination.strip():
            raise ValueError("Destination is required.")
        if not isinstance(route, (list, tuple)) or not route:
            raise ValueError("Route must be a non-empty list of road IDs.")
        if any(not isinstance(road_id, str) or not road_id.strip() for road_id in route):
            raise ValueError("Every route entry must be a non-empty road ID.")
        if route[0] != origin:
            raise ValueError("Route must begin at the origin.")
        if route[-1] != destination:
            raise ValueError("Route must end at the destination.")

        self._validate_integer("created_tick", created_tick, minimum=0)
        self._validate_integer("remaining_ticks", remaining_ticks, minimum=0)
        self._validate_integer("route_index", route_index, minimum=0)
        self._validate_integer("entry_tick", entry_tick, minimum=-1)
        if route_index >= len(route):
            raise ValueError("Route index is outside the route.")

        self.vehicle_id = vehicle_id
        self.origin = origin
        self.destination = destination
        self.route = list(route)
        self.created_tick = created_tick
        self.remaining_ticks = remaining_ticks
        self.route_index = route_index
        self.entry_tick = entry_tick

    @staticmethod
    def _validate_integer(name, value, minimum):
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"{name} must be an integer greater than or equal to {minimum}.")

    @property
    def id(self):
        """Compatibility alias for an earlier draft that used ``id``."""
        return self.vehicle_id

    def get_current_road(self):
        """Return the road currently occupied by this vehicle."""
        return self.route[self.route_index]

    def get_next_road(self):
        """Return the next road ID, or None when the destination is reached."""
        next_index = self.route_index + 1
        if next_index < len(self.route):
            return self.route[next_index]
        return None

    def advance_route(self):
        """Advance the route position after a receiving Road Node accepts it.

        Returns True when the vehicle advances, or False if it is already at
        its destination. The Road Node is responsible for resetting travel time
        and entry tick after accepting the transfer.
        """
        if self.route_index + 1 >= len(self.route):
            return False
        self.route_index += 1
        return True

    def to_dictionary(self):
        """Return all vehicle state in a JSON-compatible dictionary."""
        return {
            "vehicle_id": self.vehicle_id,
            "origin": self.origin,
            "destination": self.destination,
            "route": list(self.route),
            "route_index": self.route_index,
            "created_tick": self.created_tick,
            "entry_tick": self.entry_tick,
            "remaining_ticks": self.remaining_ticks,
        }

    @classmethod
    def from_dictionary(cls, vehicle_data):
        """Rebuild a Vehicle from JSON data received by a Road Node.

        The ``id`` fallback supports dictionaries made by the earlier Vehicle
        draft. New code should use the canonical ``vehicle_id`` key.
        """
        if not isinstance(vehicle_data, dict):
            raise ValueError("Vehicle data must be a dictionary.")

        vehicle_id = vehicle_data.get("vehicle_id", vehicle_data.get("id"))
        return cls(
            vehicle_id=vehicle_id,
            origin=vehicle_data.get("origin"),
            destination=vehicle_data.get("destination"),
            route=vehicle_data.get("route"),
            created_tick=vehicle_data.get("created_tick", 0),
            remaining_ticks=vehicle_data.get("remaining_ticks", 0),
            route_index=vehicle_data.get("route_index", 0),
            entry_tick=vehicle_data.get("entry_tick", -1),
        )

    # Compatibility wrappers for the method names used in the earlier draft.
    def to_dict(self):
        return self.to_dictionary()

    @classmethod
    def from_dict(cls, vehicle_data):
        return cls.from_dictionary(vehicle_data)

    def __str__(self):
        return (
            f"Vehicle {self.vehicle_id}: {self.get_current_road()} to "
            f"{self.destination}, remaining ticks: {self.remaining_ticks}"
        )
