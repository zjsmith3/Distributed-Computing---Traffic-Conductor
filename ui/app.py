"""Simple traffic viewer — roads as paths, vehicles as the interactive objects."""

import math
import tkinter as tk
from tkinter import ttk

from config.config import load_network_file


VEHICLE_W = 28
VEHICLE_H = 16
PADDING = 48
ROAD_THICKNESS = 56
ANIMATION_MS = 40
# How much of a road segment a vehicle covers each frame (before tick scaling).
BASE_SPEED = 0.012

COLORS = {
    "bg": "#1a1f2e",
    "canvas": "#12161f",
    "panel": "#222938",
    "text": "#e8ecf4",
    "muted": "#9aa3b5",
    "road": "#4a5568",
    "road_outline": "#2a3142",
    "road_label": "#c5cedd",
    "vehicle": "#e8b84a",
    "vehicle_selected": "#ffd666",
    "vehicle_body": "#2a3142",
    "coord": "#c9a227",
}


def _demo_vehicles(roads):
    """Placeholder vehicles for the UI until the simulation is wired up."""
    road_ids = sorted(roads.keys())
    vehicles = []
    for index, road_id in enumerate(road_ids):
        connections = roads[road_id]["connections"]
        destination = connections[0] if connections else road_id
        route = [road_id] + ([destination] if destination != road_id else [])
        vehicles.append(
            {
                "id": index + 1,
                "road": road_id,
                "origin": road_id,
                "destination": destination,
                "route": route,
                "progress": 0.35 + (index * 0.18) % 0.5,
                "remaining_ticks": roads[road_id]["base_travel_ticks"],
            }
        )
    return vehicles


class TrafficConductorUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Traffic Conductor")
        self.root.minsize(860, 520)
        self.root.configure(bg=COLORS["bg"])

        self.network = load_network_file()
        self.vehicles = _demo_vehicles(self.network["roads"])
        self._initial_vehicles = [dict(vehicle) for vehicle in self.vehicles]
        self.selected_vehicle_id = None
        # road_id -> {"x1","y1","x2","y2"} centerline of the thick road block
        self.road_geometry = {}
        self.vehicle_items = {}
        self.hint_label = None
        self.playing = False
        self._anim_after_id = None

        self._build_layout()
        self._compute_road_geometry()
        self._draw_scene()
        self._show_overview()
        self._update_transport_buttons()
        self._schedule_frame()

    def _build_layout(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=COLORS["bg"])
        style.configure("Panel.TFrame", background=COLORS["panel"])
        style.configure("Controls.TFrame", background=COLORS["panel"])
        style.configure(
            "Title.TLabel",
            background=COLORS["bg"],
            foreground=COLORS["text"],
            font=("Helvetica", 16, "bold"),
        )
        style.configure(
            "Heading.TLabel",
            background=COLORS["panel"],
            foreground=COLORS["text"],
            font=("Helvetica", 13, "bold"),
        )
        style.configure(
            "Body.TLabel",
            background=COLORS["panel"],
            foreground=COLORS["muted"],
            font=("Helvetica", 11),
        )
        style.configure(
            "Value.TLabel",
            background=COLORS["panel"],
            foreground=COLORS["text"],
            font=("Helvetica", 11),
        )
        style.configure(
            "Transport.TButton",
            font=("Helvetica", 14),
            padding=(14, 8),
        )

        header = ttk.Frame(self.root, style="TFrame")
        header.pack(fill="x", padx=16, pady=(14, 8))
        ttk.Label(header, text="Traffic Conductor", style="Title.TLabel").pack(side="left")

        body = ttk.Frame(self.root, style="TFrame")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        left = ttk.Frame(body, style="TFrame")
        left.pack(side="left", fill="both", expand=True, padx=(0, 12))

        self.canvas = tk.Canvas(
            left,
            bg=COLORS["canvas"],
            highlightthickness=0,
            width=560,
            height=420,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        controls = ttk.Frame(left, style="Controls.TFrame")
        controls.pack(fill="x", pady=(10, 0))

        transport = ttk.Frame(controls, style="Controls.TFrame")
        transport.pack(pady=8)

        self.reset_btn = ttk.Button(
            transport,
            text="⏮",
            style="Transport.TButton",
            command=self._on_reset,
            width=4,
        )
        self.play_btn = ttk.Button(
            transport,
            text="▶",
            style="Transport.TButton",
            command=self._on_play,
            width=4,
        )
        self.pause_btn = ttk.Button(
            transport,
            text="⏸",
            style="Transport.TButton",
            command=self._on_pause,
            width=4,
        )
        self.reset_btn.pack(side="left", padx=4)
        self.play_btn.pack(side="left", padx=4)
        self.pause_btn.pack(side="left", padx=4)

        self.status_label = ttk.Label(
            controls,
            text="Paused",
            style="Body.TLabel",
        )
        self.status_label.pack(pady=(0, 8))

        side = ttk.Frame(body, style="Panel.TFrame", width=280)
        side.pack(side="right", fill="y")
        side.pack_propagate(False)

        inner = ttk.Frame(side, style="Panel.TFrame")
        inner.pack(fill="both", expand=True, padx=14, pady=14)

        self.detail_title = ttk.Label(inner, text="Traffic", style="Heading.TLabel")
        self.detail_title.pack(anchor="w", pady=(0, 10))

        self.detail_rows = ttk.Frame(inner, style="Panel.TFrame")
        self.detail_rows.pack(fill="both", expand=True)

        self.hint_label = ttk.Label(
            inner,
            text="Click a vehicle for details.",
            style="Body.TLabel",
        )
        self.hint_label.pack(anchor="w", pady=(8, 0))

    def _clear_detail_rows(self):
        for child in self.detail_rows.winfo_children():
            child.destroy()

    def _add_detail_row(self, label, value):
        row = ttk.Frame(self.detail_rows, style="Panel.TFrame")
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, style="Body.TLabel", width=14).pack(side="left")
        ttk.Label(row, text=str(value), style="Value.TLabel").pack(side="left", fill="x")

    def _show_overview(self):
        self.selected_vehicle_id = None
        self.detail_title.configure(text="Traffic")
        self._clear_detail_rows()

        coordinator = self.network["coordinator"]
        roads = self.network["roads"]
        by_road = {}
        for vehicle in self.vehicles:
            by_road.setdefault(vehicle["road"], 0)
            by_road[vehicle["road"]] += 1

        self._add_detail_row("Vehicles", len(self.vehicles))
        self._add_detail_row("Roads", len(roads))
        self._add_detail_row("Coordinator", f"{coordinator['host']}:{coordinator['port']}")
        occupancy = ", ".join(f"{road}:{count}" for road, count in sorted(by_road.items()))
        self._add_detail_row("On roads", occupancy or "—")
        self._redraw_selection()

    def _show_vehicle(self, vehicle_id):
        vehicle = next(v for v in self.vehicles if v["id"] == vehicle_id)
        road = self.network["roads"][vehicle["road"]]
        self.selected_vehicle_id = vehicle_id

        self.detail_title.configure(text=f"Vehicle {vehicle_id}")
        self._clear_detail_rows()
        self._add_detail_row("Current road", vehicle["road"])
        self._add_detail_row("Origin", vehicle["origin"])
        self._add_detail_row("Destination", vehicle["destination"])
        self._add_detail_row("Route", " → ".join(vehicle["route"]))
        self._add_detail_row("Remaining ticks", vehicle["remaining_ticks"])
        self._add_detail_row("Road capacity", road["capacity"])
        self._redraw_selection()

    def _compute_road_geometry(self):
        """Build thick road blocks. The roads *are* the links — no junction nodes."""
        roads = self.network["roads"]
        width = max(self.canvas.winfo_width(), 560)
        height = max(self.canvas.winfo_height(), 420)
        self.road_geometry = {}

        if set(roads) == {"A", "B", "C"}:
            # L-shaped map matching the sketch:
            #   A vertical, B horizontal from A's bottom, C vertical from B's right end.
            left = width * 0.28
            top = height * 0.12
            corner_y = height * 0.58
            right = width * 0.78
            bottom = height * 0.88
            half = ROAD_THICKNESS / 2

            self.road_geometry = {
                "A": {"x1": left, "y1": top, "x2": left, "y2": corner_y + half},
                "B": {"x1": left - half, "y1": corner_y, "x2": right + half, "y2": corner_y},
                "C": {"x1": right, "y1": corner_y - half, "x2": right, "y2": bottom},
            }
            return

        # Fallback: place each road as a short thick segment around a circle.
        cx, cy = width / 2, height / 2
        radius = min(width, height) / 2 - PADDING - ROAD_THICKNESS
        count = max(len(roads), 1)
        for index, road_id in enumerate(sorted(roads)):
            angle = (2 * math.pi * index / count) - (math.pi / 2)
            mx = cx + radius * math.cos(angle)
            my = cy + radius * math.sin(angle)
            dx = -math.sin(angle) * 55
            dy = math.cos(angle) * 55
            self.road_geometry[road_id] = {
                "x1": mx - dx,
                "y1": my - dy,
                "x2": mx + dx,
                "y2": my + dy,
            }

    def _road_segment(self, road_id):
        geom = self.road_geometry[road_id]
        return geom["x1"], geom["y1"], geom["x2"], geom["y2"]

    def _point_on_segment(self, x1, y1, x2, y2, progress):
        # Keep vehicles slightly inset from the block ends.
        t = 0.08 + 0.84 * progress
        return (x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)

    def _road_block_rect(self, x1, y1, x2, y2):
        """Axis-aligned thick rectangle covering the road centerline."""
        half = ROAD_THICKNESS / 2
        if abs(x2 - x1) >= abs(y2 - y1):
            # Horizontal road
            left, right = min(x1, x2), max(x1, x2)
            return left, y1 - half, right, y1 + half
        # Vertical road
        top, bottom = min(y1, y2), max(y1, y2)
        return x1 - half, top, x1 + half, bottom

    def _draw_scene(self):
        self.canvas.delete("all")
        self.vehicle_items = {}

        # Draw road blocks first (the links themselves).
        for road_id in self.network["roads"]:
            x1, y1, x2, y2 = self._road_segment(road_id)
            left, top, right, bottom = self._road_block_rect(x1, y1, x2, y2)
            self.canvas.create_rectangle(
                left, top, right, bottom,
                fill=COLORS["road"],
                outline=COLORS["road_outline"],
                width=2,
                tags=("path", road_id),
            )
            self.canvas.create_text(
                (left + right) / 2,
                (top + bottom) / 2,
                text=road_id,
                fill=COLORS["road_label"],
                font=("Helvetica", 18, "bold"),
                tags=("path", road_id),
            )

        for vehicle in self.vehicles:
            self._draw_vehicle(vehicle)

        coordinator = self.network["coordinator"]
        self.canvas.create_oval(18, 18, 34, 34, fill=COLORS["coord"], outline="")
        self.canvas.create_text(
            42, 26,
            anchor="w",
            fill=COLORS["muted"],
            font=("Helvetica", 10),
            text=f"Coordinator  {coordinator['host']}:{coordinator['port']}",
        )

    def _draw_vehicle(self, vehicle):
        x1, y1, x2, y2 = self._road_segment(vehicle["road"])
        x, y = self._point_on_segment(x1, y1, x2, y2, vehicle["progress"])
        angle = math.atan2(y2 - y1, x2 - x1)
        selected = vehicle["id"] == self.selected_vehicle_id
        fill = COLORS["vehicle_selected"] if selected else COLORS["vehicle"]
        tag = f"vehicle-{vehicle['id']}"

        hw, hh = VEHICLE_W / 2, VEHICLE_H / 2
        corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        points = []
        for cx, cy in corners:
            rx = cx * cos_a - cy * sin_a
            ry = cx * sin_a + cy * cos_a
            points.extend([x + rx, y + ry])

        body = self.canvas.create_polygon(
            points,
            fill=fill,
            outline=COLORS["vehicle_body"],
            width=2,
            tags=("vehicle", tag),
        )
        label = self.canvas.create_text(
            x, y,
            text=str(vehicle["id"]),
            fill=COLORS["vehicle_body"],
            font=("Helvetica", 9, "bold"),
            tags=("vehicle", tag),
        )
        self.vehicle_items[vehicle["id"]] = (body, label)

    def _redraw_selection(self):
        for vehicle_id, (body, _label) in self.vehicle_items.items():
            fill = (
                COLORS["vehicle_selected"]
                if vehicle_id == self.selected_vehicle_id
                else COLORS["vehicle"]
            )
            self.canvas.itemconfigure(body, fill=fill)

    def _on_canvas_click(self, event):
        items = self.canvas.find_overlapping(event.x - 2, event.y - 2, event.x + 2, event.y + 2)
        for item in items:
            tags = self.canvas.gettags(item)
            if "vehicle" in tags:
                for tag in tags:
                    if tag.startswith("vehicle-"):
                        vehicle_id = int(tag.split("-", 1)[1])
                        self._show_vehicle(vehicle_id)
                        return
        self._show_overview()

    def _on_canvas_resize(self, _event):
        self._compute_road_geometry()
        self._draw_scene()
        self._redraw_selection()

    def _advance_vehicle(self, vehicle):
        ticks = max(vehicle["remaining_ticks"], 1)
        vehicle["progress"] += BASE_SPEED / ticks

        if vehicle["progress"] < 1.0:
            return

        vehicle["progress"] = 0.0
        route = vehicle["route"]
        try:
            index = route.index(vehicle["road"])
        except ValueError:
            index = 0

        if index + 1 < len(route):
            next_road = route[index + 1]
        else:
            # Loop the demo route so animation keeps going.
            next_road = route[0]

        vehicle["road"] = next_road
        vehicle["remaining_ticks"] = self.network["roads"][next_road]["base_travel_ticks"]

    def _update_transport_buttons(self):
        if self.playing:
            self.play_btn.state(["disabled"])
            self.pause_btn.state(["!disabled"])
            self.status_label.configure(text="Playing")
        else:
            self.play_btn.state(["!disabled"])
            self.pause_btn.state(["disabled"])
            self.status_label.configure(text="Paused")

    def _on_play(self):
        self.playing = True
        self._update_transport_buttons()

    def _on_pause(self):
        self.playing = False
        self._update_transport_buttons()

    def _on_reset(self):
        self.playing = False
        self.vehicles = [dict(vehicle) for vehicle in self._initial_vehicles]
        self.selected_vehicle_id = None
        self._draw_scene()
        self._show_overview()
        self._update_transport_buttons()

    def _schedule_frame(self):
        self._anim_after_id = self.root.after(ANIMATION_MS, self._animate)

    def _animate(self):
        if self.playing:
            for vehicle in self.vehicles:
                self._advance_vehicle(vehicle)
            self._draw_scene()
            self._redraw_selection()

        self._schedule_frame()


def run():
    root = tk.Tk()
    TrafficConductorUI(root)
    root.mainloop()


