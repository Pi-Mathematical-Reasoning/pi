"""Measuring what a run costs the machine: resident memory and swap."""

import sys
import threading
import time

import pytest

from pi.resources import (
    OllamaTree,
    ResourceSampler,
    ollama_tree,
    parse_power,
    parse_process_table,
    parse_swap_used_bytes,
    read_machine,
    read_ollama_tree,
    read_power,
    read_swap_used_bytes,
    read_wake,
)

# pid, parent pid, resident KiB, command. The server (964) launched the runner
# (74892), which has a helper child. The other two processes are unrelated,
# one of them with "ollama" in its name.
PROCESS_TABLE = """\
  964     1    32448 /opt/homebrew/opt/ollama/bin/ollama serve
74892   964 10387472 /opt/lib/ollama/llama-server --model /m/blobs/sha256-a8cc --port 54860 -c 16384
74900 74892     1024 /bin/sh -c helper
  501     1   204800 /usr/bin/python3 -m http.server
 7000   501   999999 /usr/local/bin/ollama-exporter --listen
"""


def test_sums_the_resident_memory_of_the_ollama_server_and_its_descendants():
    tree = ollama_tree(parse_process_table(PROCESS_TABLE))

    # (32448 + 10387472 + 1024) KiB
    assert tree.resident_bytes == 10_671_046_656


def test_reports_the_command_the_server_launched_the_runner_with():
    tree = ollama_tree(parse_process_table(PROCESS_TABLE))

    assert tree.runner_commands == (
        "/opt/lib/ollama/llama-server --model /m/blobs/sha256-a8cc --port 54860 -c 16384",
    )


def test_finds_no_tree_when_ollama_is_not_running():
    without_ollama = "  501     1   204800 /usr/bin/python3 -m http.server\n"

    assert ollama_tree(parse_process_table(without_ollama)) is None


def test_reads_the_swap_in_use():
    line = "total = 3072.00M  used = 2085.25M  free = 986.75M  (encrypted)"

    assert parse_swap_used_bytes(line) == 2_186_543_104


def test_reads_swap_reported_in_gigabytes():
    line = "total = 4.00G  used = 1.50G  free = 2.50G  (encrypted)"

    assert parse_swap_used_bytes(line) == 1_610_612_736


def test_reads_no_swap_in_use_as_zero():
    assert parse_swap_used_bytes("total = 0.00M  used = 0.00M  free = 0.00M  (encrypted)") == 0


def test_refuses_swap_output_it_cannot_read():
    with pytest.raises(ValueError, match="swap"):
        parse_swap_used_bytes("vm.swapusage: unavailable")


def readings(values):
    """A reader that returns each value in turn, then repeats the last."""
    remaining = list(values)
    return lambda: remaining.pop(0) if len(remaining) > 1 else remaining[0]


def tree(resident_bytes, command="runner"):
    return OllamaTree(resident_bytes=resident_bytes, runner_commands=(command,))


def test_sampler_keeps_the_peak_memory_across_samples():
    sampler = ResourceSampler(readings([tree(100), tree(900), tree(400)]), readings([0]))

    for _ in range(3):
        sampler.sample()

    assert sampler.peak_resident_bytes == 900


def test_sampler_measures_swap_growth_from_the_first_sample_to_the_peak():
    sampler = ResourceSampler(readings([tree(1)]), readings([10, 50, 30]))

    for _ in range(3):
        sampler.sample()

    assert sampler.swap_before_bytes == 10
    assert sampler.swap_peak_bytes == 50
    assert sampler.swap_growth_bytes == 40


def test_sampler_tolerates_samples_taken_before_the_model_is_loaded():
    sampler = ResourceSampler(readings([None, tree(500), None]), readings([0]))

    for _ in range(3):
        sampler.sample()

    assert sampler.peak_resident_bytes == 500


def test_sampler_reports_nothing_when_ollama_was_never_seen():
    sampler = ResourceSampler(readings([None]), readings([None]))

    sampler.sample()

    assert sampler.peak_resident_bytes is None
    assert sampler.swap_growth_bytes is None
    assert sampler.runner_commands == ()


def test_sampler_remembers_the_runner_command_after_the_runner_exits():
    sampler = ResourceSampler(readings([tree(5, "llama-server -c 16384"), None]), readings([0]))

    sampler.sample()
    sampler.sample()

    assert sampler.runner_commands == ("llama-server -c 16384",)


def test_a_run_shorter_than_the_interval_is_still_sampled_at_both_ends():
    calls = []

    def read_tree():
        calls.append(len(calls))
        return tree(100 if len(calls) == 1 else 700)

    with ResourceSampler(read_tree, readings([0]), interval=60):
        pass

    assert len(calls) == 2
    # The sample at the end is the only one that saw the loaded model.


def test_sampler_keeps_sampling_in_the_background_until_stopped():
    third_sample = threading.Event()
    calls = []

    def read_tree():
        calls.append(None)
        if len(calls) >= 3:
            third_sample.set()
        return tree(1)

    with ResourceSampler(read_tree, readings([0]), interval=0.01):
        assert third_sample.wait(timeout=5)

    after_stop = len(calls)
    time.sleep(0.05)
    assert len(calls) == after_stop


def test_a_reader_that_fails_in_the_background_fails_the_run():
    # A sampler that died quietly would report a peak it never measured.
    failed = threading.Event()
    calls = []

    def read_tree():
        calls.append(None)
        if len(calls) == 2:
            failed.set()
            raise RuntimeError("ps went away")
        return tree(1)

    sampler = ResourceSampler(read_tree, readings([0]), interval=0.01)
    with pytest.raises(RuntimeError, match="ps went away"), sampler:
        assert failed.wait(timeout=5)


def test_the_real_process_reader_works_on_this_machine():
    found = read_ollama_tree()

    assert found is None or found.resident_bytes > 0


def test_the_real_swap_reader_works_on_this_machine():
    used = read_swap_used_bytes()

    if sys.platform == "darwin":
        assert used >= 0
    else:
        assert used is None


BATTERY_STATUS = """Now drawing from 'Battery Power'
 -InternalBattery-0 (id=24182883)	15%; discharging; 0:24 remaining present: true
"""

MAINS_STATUS = """Now drawing from 'AC Power'
 -InternalBattery-0 (id=24182883)	100%; charged; 0:00 remaining present: true
"""

SETTINGS = """System-wide power settings:
Currently in use:
 standby              1
 powermode            2
 sleep                1
"""


def test_reads_whether_the_machine_is_on_battery_or_mains_and_its_energy_mode():
    assert parse_power(BATTERY_STATUS, SETTINGS) == {
        "source": "Battery Power",
        "mode": "powermode 2",
    }
    assert parse_power(MAINS_STATUS, SETTINGS)["source"] == "AC Power"


def test_reads_the_energy_mode_under_the_name_older_macs_give_it():
    settings = "Currently in use:\n lowpowermode         1\n sleep                1\n"

    assert parse_power(MAINS_STATUS, settings)["mode"] == "lowpowermode 1"


def test_reports_no_energy_mode_when_the_machine_has_none():
    assert parse_power(MAINS_STATUS, "Currently in use:\n sleep 1\n")["mode"] is None


def test_refuses_a_power_status_it_cannot_read():
    with pytest.raises(ValueError, match="power"):
        parse_power("pmset: unavailable", SETTINGS)


def test_the_real_power_reader_works_on_this_machine():
    power = read_power()

    if sys.platform == "darwin":
        assert power["source"] in ("AC Power", "Battery Power")
    else:
        assert power is None


def test_reads_the_machine_it_runs_on():
    machine = read_machine()

    assert machine["python"].count(".") == 2
    if sys.platform == "darwin":
        assert machine["chip"] and machine["model"] and machine["memory_bytes"] > 0
        assert machine["os"].startswith("macOS ")


def test_reads_the_last_wake_from_sleep():
    wake = read_wake()

    assert wake is None or isinstance(wake, str)
    if sys.platform == "darwin":
        assert wake
