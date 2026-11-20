# How to apply this update

This archive is a **drop-in update** for the existing Traffic Conductor repo. It
contains only files that are new or need to be replaced. Extract it into the
repository's top-level folder, not into a new nested folder.

## 1. Start from the current main branch

The earlier `feature/coordinator` branch was based on an older version of the
project. Start a fresh branch from the current `main` so this work uses the
same vehicle ID format and interfaces as the team’s latest changes.

In the VS Code terminal, from the project folder:

```powershell
git status
git fetch origin
git switch main
git pull --ff-only origin main
git switch -c feature/coordinator-reliability
```

Before switching branches, `git status` should show a clean working tree. If it
shows local changes you still need, stop and save those separately rather than
overwriting or deleting them.

## 2. Extract the ZIP into the repo root

Download `traffic-conductor-coordinator-update.zip`. In File Explorer, extract
its contents directly into the `Distributed-Computing---Traffic-Conductor`
folder and allow Windows to replace the existing files when prompted.

The archive keeps the existing `config`, `protocol`, `vehicle`, and UI files
intact. It replaces the Coordinator, Road Node, and shared TCP server, and adds
tests and documentation.

## 3. Run the tests

Back in the VS Code terminal, run:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q coordinator roads communication tests
```

The automated tests use mocked requests for unit tests and temporary local TCP
servers for the end-to-end tests. They do not require the regular simulation
ports to be free.

## 4. Commit and push your branch

```powershell
git status
git add coordinator/coordinator.py roads/road_node.py roads/test_vehicle.py communication/server.py tests README.md docs .github/workflows/tests.yml
git commit -m "Improve coordinator reliability and road monitoring"
git push -u origin feature/coordinator-reliability
```

Then open the repository on GitHub, choose **Compare & pull request**, set the
base branch to `main`, and the compare branch to
`feature/coordinator-reliability`. The suggested title and PR write-up are in
`PR_DESCRIPTION.md`.

Do not merge the old `feature/coordinator` branch into this new branch as part
of this update; its earlier Coordinator/Vehicle interfaces are out of date.
