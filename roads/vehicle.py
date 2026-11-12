class Vehicle:
    def __init__(
            self,
            vehicle_id: int,
            origin: str,
            destination: str,
            route: list,
            created_tick: int = 0,
            remaining_ticks: int = 0,
            route_index: int = 0,
            entry_tick: int = -1
            ):
        
        if vehicle_id < 0:
            raise ValueError("Vehicle ID cannot be negative.")

        if not origin or not destination:
            raise ValueError("Origin and destination are required.")

        if not route:
            raise ValueError("Vehicle route cannot be empty.")

        if route[0] != origin:
            raise ValueError("Route must begin at the origin.")

        if route[-1] != destination:
            raise ValueError("Route must end at the destination.")

        if not 0 <= route_index < len(route):
            raise ValueError("Invalid route index.")

        if remaining_ticks < 0:
            raise ValueError("Remaining ticks cannot be negative.")

        if created_tick < 0:
            raise ValueError("Created tick cannot be negative.")

        if entry_tick < -1:
            raise ValueError("Invalid entry tick.")
        
        self.id = vehicle_id
        self.origin = origin
        self.destination = destination
        self.route = list(route)

        self.route_index = route_index
        self.entry_tick = entry_tick

        self.created_tick = created_tick
        self.entry_tick = entry_tick
        self.remaining_ticks = remaining_ticks

    def get_current_road(self):
        return self.route[self.route_index]
    
    def get_next_road(self):
        if self.route_index + 1 < len(self.route):
            return self.route[self.route_index + 1 ]
        return None
    
    def to_dictionary(self):
        return {
            "id": self.id,
            "origin": self.origin,
            "destination": self.destination,
            "route": self.route,
            "route_index": self.route_index,
            "remaining_ticks": self.remaining_ticks,
            "created_tick": self.created_tick,
            "entry_tick": self.entry_tick
        }
    
    @classmethod
    def from_dictionary(cls, data):
        return cls(
            vehicle_id = data["id"],
            origin = data["origin"],
            destination = data["destination"],
            route = data["route"],
            route_index = data["route_index"],
            remaining_ticks = data["remaining_ticks"],
            created_tick = data["created_tick"],
            entry_tick = data["entry_tick"]
        )
    
    def _str_(self):
        return(
            f"Vehicle {self.id}: "
            f"{self.get_current_road()} going to {self.destination}, "
            f"Remaining Ticks: {self.remaining_ticks}"
        )
        
