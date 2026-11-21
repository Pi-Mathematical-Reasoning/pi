"""What a run costs the machine: the model's resident memory and swap growth.

Ollama serves the model from a child process of its server, so memory is
measured over the server and everything it launched, not over this process.
"""

import platform
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


def without_home(command: str) -> str:
    """A command line with the home directory written as ~, fit for a public record."""
    return command.replace(str(Path.home()), "~")


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


_POWER_SOURCE = re.compile(r"drawing from '([^']+)'")
_ENERGY_MODE = re.compile(r"^\s*((?:low)?powermode)\s+(\d+)\s*$", re.MULTILINE)


def parse_power(status: str, settings: str) -> dict:
    """Parse `pmset -g batt` and `pmset -g`: the power source and the energy mode.

    The energy mode is kept as pmset prints it, such as "powermode 2", because
    its numbering is not documented.
    """
    source = _POWER_SOURCE.search(status)
    if source is None:
        raise ValueError(f"cannot read the power source from {status!r}")
    mode = _ENERGY_MODE.search(settings)
    return {
        "source": source.group(1),
        "mode": None if mode is None else f"{mode.group(1)} {mode.group(2)}",
    }


def read_power() -> dict | None:
    """Whether the machine is on battery or mains, or None where this is not read (off macOS)."""
    if sys.platform != "darwin":
        return None
    status = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, check=True)
    settings = subprocess.run(["pmset", "-g"], capture_output=True, text=True, check=True)
    return parse_power(status.stdout, settings.stdout)


def parse_thermal(text: str) -> list[str]:
    """Parse `pmset -g therm`: its notes and readings, one line each, as printed.

    Kept as printed because the format differs between macOS versions and states.
    """
    return [line.strip() for line in text.splitlines() if line.strip()]


def read_thermal() -> list[str] | None:
    """The machine's thermal and performance warnings, or None off macOS."""
    if sys.platform != "darwin":
        return None
    done = subprocess.run(["pmset", "-g", "therm"], capture_output=True, text=True, check=True)
    return parse_thermal(done.stdout)


def read_wake() -> str | None:
    """When the machine last woke from sleep, or None where this is not read (off macOS).

    It changes only when the machine wakes, so a value that differs after an
    attempt from before it means the machine slept during the attempt.
    """
    if sys.platform != "darwin":
        return None
    return _sysctl("kern.waketime")


def read_machine() -> dict:
    """The machine a run is on: what a reader needs to compare its times with another's."""
    machine = {"python": platform.python_version()}
    if sys.platform == "darwin":
        machine.update(
            model=_sysctl("hw.model"),
            chip=_sysctl("machdep.cpu.brand_string"),
            memory_bytes=int(_sysctl("hw.memsize")),
            os="macOS {} ({})".format(
                *(
                    subprocess.run(
                        ["sw_vers", flag], capture_output=True, text=True, check=True
                    ).stdout.strip()
                    for flag in ("-productVersion", "-buildVersion")
                )
            ),
        )
    else:
        machine.update(os=platform.platform())
    return machine


def _sysctl(name: str) -> str:
    done = subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, check=True)
    return done.stdout.strip()


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
        # Since the last begin_attempt(): one problem's own peak, and the swap after it.
        self.attempt_peak_resident_bytes = None
        self.last_swap_bytes = None
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
            self.attempt_peak_resident_bytes = max(
                self.attempt_peak_resident_bytes or 0, tree.resident_bytes
            )
            if tree.runner_commands:
                self.runner_commands = tree.runner_commands

        swap = self._read_swap()
        if swap is not None:
            if self.swap_before_bytes is None:
                self.swap_before_bytes = swap
            self.swap_peak_bytes = max(self.swap_peak_bytes or 0, swap)
            self.last_swap_bytes = swap

    def begin_attempt(self) -> None:
        """Start measuring one problem's own peak memory."""
        self.attempt_peak_resident_bytes = None

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
