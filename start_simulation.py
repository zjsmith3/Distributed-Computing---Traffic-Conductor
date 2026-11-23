import subprocess
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

with open(PROJECT_ROOT / "config" / "network.json") as file:
    config = json.load(file)

# Create a command for each node
commands = [
    ["new-tab", "--title", "Coordinator", "-d", str(PROJECT_ROOT),
     "python", "-m", "coordinator.coordinator"]
]

for road_id in config["roads"]:
    commands.append([
        "new-tab", "--title", f"Road {road_id}",
        "-d", str(PROJECT_ROOT),
        "python", "run_road.py", road_id
    ])

# Combine commands into one Windows Terminal launch
arguments = ["wt"]

for index, command in enumerate(commands):
    if index > 0:
        arguments.append(";")
    arguments.extend(command)

subprocess.Popen(arguments)

print("Launched Coordinator and all Road Nodes!")
