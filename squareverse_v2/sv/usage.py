"""CPU and GPU usage for the top-right readout, sampled in the background so the frame never waits on it.

CPU: the whole (Linux) machine's busy share from /proc/stat, and this process's share of all its cores from
/proc/self/stat. GPU: Windows' own counters (as in Task Manager: the busiest engine type, summed over every
process), read by one long-running powershell.exe, so under WSL it covers the real GPU; elsewhere it shows as
unavailable.
"""

import os
import shutil
import subprocess
import threading
import time

CPU_EVERY = 0.5                 # s between CPU samples
GPU_SCRIPT = (
    "while ($true) { "
    "$c = (Get-Counter '\\GPU Engine(*)\\Utilization Percentage' -ErrorAction SilentlyContinue).CounterSamples; "
    "$m = ($c | Group-Object { ($_.InstanceName -split 'engtype_')[1] } | "
    "ForEach-Object { ($_.Group | Measure-Object CookedValue -Sum).Sum } | Measure-Object -Maximum).Maximum; "
    "[Console]::WriteLine([math]::Round([double]$m, 1)); [Console]::Out.Flush() }"
)


def _proc_stat():
    """(busy, total) clock ticks of all CPUs since boot."""
    with open("/proc/stat") as f:
        v = [int(x) for x in f.readline().split()[1:]]
    idle = v[3] + (v[4] if len(v) > 4 else 0)
    return sum(v[:8]) - idle, sum(v[:8])


def _self_ticks():
    """This process's user + system clock ticks."""
    with open("/proc/self/stat") as f:
        rest = f.read().rsplit(")", 1)[1].split()
    return int(rest[11]) + int(rest[12])


class Usage:
    """Latest readings, as percentages (None until known or when unavailable): cpu (the machine), sim (this
    process, of all cores) and gpu."""

    def __init__(self):
        self.cpu = self.sim = self.gpu = None
        self.gpu_note = "starting"
        self._proc = None
        self._stop = threading.Event()

    def start(self):
        if os.path.exists("/proc/stat"):
            threading.Thread(target=self._cpu_loop, daemon=True).start()
        ps = shutil.which("powershell.exe")
        if ps is None:
            self.gpu_note = "n/a"
            return self
        try:
            self._proc = subprocess.Popen([ps, "-NoProfile", "-NonInteractive", "-Command", GPU_SCRIPT],
                                          stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL, text=True, bufsize=1)
        except OSError:
            self.gpu_note = "n/a"
            return self
        threading.Thread(target=self._gpu_loop, daemon=True).start()
        return self

    def stop(self):
        self._stop.set()
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()

    def _cpu_loop(self):
        tck, cores = os.sysconf("SC_CLK_TCK"), os.cpu_count() or 1
        busy0, total0 = _proc_stat()
        own0, t0 = _self_ticks(), time.monotonic()
        while not self._stop.wait(CPU_EVERY):
            busy, total = _proc_stat()
            own, t = _self_ticks(), time.monotonic()
            if total > total0:
                self.cpu = 100.0 * (busy - busy0) / (total - total0)
            if t > t0:
                self.sim = min(100.0, 100.0 * (own - own0) / tck / (t - t0) / cores)
            busy0, total0, own0, t0 = busy, total, own, t

    def _gpu_loop(self):
        for line in self._proc.stdout:
            if self._stop.is_set():
                break
            try:
                self.gpu = min(100.0, float(line))
            except ValueError:
                continue
        if self.gpu is None:
            self.gpu_note = "n/a"
