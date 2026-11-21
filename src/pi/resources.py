"""What a run costs the machine: the model's resident memory and swap growth.

Ollama serves the model from a child process of its server, so memory is
measured over the server and everything it launched, not over this process.
"""

import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Process:
    pid: int
    parent: int
    resident_bytes: int
    command: str


@dataclass(frozen=True)
class OllamaTree:
    resident_bytes: int
    runner_commands: tuple[str, ...]


def parse_process_table(text: str) -> list[Process]:
    """Parse `ps -eo pid=,ppid=,rss=,args=`, where rss is in KiB."""
    processes = []
    for line in text.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4:
            pid, parent, resident_kib, command = parts
            processes.append(Process(int(pid), int(parent), int(resident_kib) * 1024, command))
    return processes


def ollama_tree(processes: list[Process]) -> OllamaTree | None:
    """The Ollama server and its descendants, or None if no server is running."""
    servers = [p for p in processes if Path(p.command.split()[0]).name == "ollama"]
    if not servers:
        return None

    members = {p.pid: p for p in servers}
    grew = True
    while grew:
        grew = False
        for process in processes:
            if process.parent in members and process.pid not in members:
                members[process.pid] = process
                grew = True

    server_pids = {p.pid for p in servers}
    runners = [p for p in processes if p.parent in server_pids and p.pid not in server_pids]
    return OllamaTree(
        resident_bytes=sum(p.resident_bytes for p in members.values()),
        runner_commands=tuple(p.command for p in runners),
    )


_SWAP_USED = re.compile(r"used = ([\d.]+)([KMG])")
_UNITS = {"K": 2**10, "M": 2**20, "G": 2**30}


def parse_swap_used_bytes(text: str) -> int:
    """Parse the output of `sysctl -n vm.swapusage`."""
    match = _SWAP_USED.search(text)
    if match is None:
        raise ValueError(f"cannot read swap usage from {text!r}")
    return round(float(match.group(1)) * _UNITS[match.group(2)])


def read_ollama_tree() -> OllamaTree | None:
    listing = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,rss=,args="], capture_output=True, text=True, check=True
    )
    return ollama_tree(parse_process_table(listing.stdout))


def read_swap_used_bytes() -> int | None:
    """Swap in use, or None where this is not measured (anywhere but macOS)."""
    if sys.platform != "darwin":
        return None
    usage = subprocess.run(
        ["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True, check=True
    )
    return parse_swap_used_bytes(usage.stdout)


class ResourceSampler:
    """Samples memory and swap while a block runs, and keeps the peaks.

    One sample is taken on entry and one on exit, so a run shorter than the
    interval is still measured before and after.
    """

    def __init__(self, read_tree=read_ollama_tree, read_swap=read_swap_used_bytes, interval=0.5):
        self._read_tree = read_tree
        self._read_swap = read_swap
        self._interval = interval
        self._stop = threading.Event()
        self._thread = None
        self._failure = None
        self.peak_resident_bytes = None
        self.runner_commands = ()
        self.swap_before_bytes = None
        self.swap_peak_bytes = None

    @property
    def swap_growth_bytes(self) -> int | None:
        if self.swap_before_bytes is None:
            return None
        return self.swap_peak_bytes - self.swap_before_bytes

    def sample(self) -> None:
        tree = self._read_tree()
        if tree is not None:
            self.peak_resident_bytes = max(self.peak_resident_bytes or 0, tree.resident_bytes)
            if tree.runner_commands:
                self.runner_commands = tree.runner_commands

        swap = self._read_swap()
        if swap is not None:
            if self.swap_before_bytes is None:
                self.swap_before_bytes = swap
            self.swap_peak_bytes = max(self.swap_peak_bytes or 0, swap)

    def __enter__(self):
        self.sample()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._stop.set()
        self._thread.join()
        if self._failure is not None:
            raise self._failure
        self.sample()
        return False

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.sample()
            except Exception as error:
                self._failure = error
                return
