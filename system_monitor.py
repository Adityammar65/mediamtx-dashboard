"""Fetch and summarize host metrics exposed by Prometheus Node Exporter."""

import re
import time
from collections import deque
from typing import Optional

import httpx

from config import settings


METRIC_LINE_RE = re.compile(
    r'^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)'
    r'(?:\{(?P<labels>.*)\})?\s+'
    r'(?P<value>[^\s]+)(?:\s+[^\s]+)?$'
)
LABEL_NAME_RE = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]*')
VIRTUAL_INTERFACE_PREFIXES = (
    "br-", "docker", "veth", "virbr", "cni", "flannel", "tun", "tap",
    "wg", "zt", "tailscale", "ifb", "dummy", "macvlan", "ipvlan",
    "vnet", "kube", "podman", "vmnet",
)


class SystemMonitor:
    """Client for fetching and computing system metrics from Node Exporter."""

    def __init__(self):
        self.base_url = str(settings.NODE_EXPORTER_URL).rstrip("/")
        self.client = httpx.AsyncClient(timeout=5.0)
        self._cpu_history = deque(maxlen=60)
        self._net_history = deque(maxlen=60)
        self._net_rx_rate_history = deque(maxlen=60)
        self._net_tx_rate_history = deque(maxlen=60)
        self._mem_history = deque(maxlen=60)
        self._disk_history = deque(maxlen=60)
        self._last_fetch_time: Optional[float] = None

    async def close(self):
        await self.client.aclose()

    async def fetch_metrics(self) -> dict:
        """Fetch raw metrics from Node Exporter's Prometheus endpoint."""
        try:
            response = await self.client.get(f"{self.base_url}/metrics")
            response.raise_for_status()
            return {"raw": response.text, "error": None}
        except httpx.HTTPError as exc:
            return {"raw": "", "error": str(exc)}

    @staticmethod
    def _parse_labels(labels_text: str) -> dict:
        """Parse Prometheus labels, including escaped quotes and commas."""
        labels = {}
        index = 0
        length = len(labels_text)

        while index < length:
            while index < length and labels_text[index] in " ,\t":
                index += 1
            if index >= length:
                break

            name_match = LABEL_NAME_RE.match(labels_text, index)
            if not name_match:
                break
            name = name_match.group(0)
            index = name_match.end()
            if index >= length or labels_text[index] != "=":
                break
            index += 1
            if index >= length or labels_text[index] != '"':
                break
            index += 1

            value_chars = []
            while index < length:
                char = labels_text[index]
                index += 1
                if char == '"':
                    break
                if char == "\\" and index < length:
                    escaped = labels_text[index]
                    index += 1
                    value_chars.append({"n": "\n", '"': '"', "\\": "\\"}.get(escaped, escaped))
                else:
                    value_chars.append(char)

            labels[name] = "".join(value_chars)
            while index < length and labels_text[index] in " \t":
                index += 1
            if index < length and labels_text[index] == ",":
                index += 1

        return labels

    def parse_metrics(self, raw: str) -> dict:
        """Parse Prometheus text exposition format into metric samples."""
        metrics = {}
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            match = METRIC_LINE_RE.match(line)
            if not match:
                continue

            try:
                value = float(match.group("value"))
            except ValueError:
                continue

            labels_text = match.group("labels")
            labels = self._parse_labels(labels_text) if labels_text is not None else {}
            metrics.setdefault(match.group("name"), []).append(
                {"labels": labels, "value": value}
            )

        return metrics

    def compute_cpu_usage(self, metrics: dict) -> tuple[Optional[float], list[float], Optional[str]]:
        """Calculate CPU usage from the latest pair of cumulative samples."""
        cpu_data = metrics.get("node_cpu_seconds_total", [])
        if not cpu_data:
            return None, [], "Node Exporter did not provide CPU metrics"

        mode_totals = {}
        for entry in cpu_data:
            mode = entry["labels"].get("mode", "")
            mode_totals[mode] = mode_totals.get(mode, 0.0) + entry["value"]

        total = sum(mode_totals.values())
        idle = mode_totals.get("idle", 0.0) + mode_totals.get("iowait", 0.0)
        now = time.time()
        self._cpu_history.append((now, total, idle))

        if len(self._cpu_history) < 2:
            return None, [], "Waiting for the next CPU sample"

        previous = self._cpu_history[-2]
        current = self._cpu_history[-1]
        delta_total = current[1] - previous[1]
        delta_idle = current[2] - previous[2]
        if delta_total <= 0 or delta_idle < 0:
            return None, [], "CPU counters reset; waiting for a new sample pair"

        usage = max(0.0, min(100.0, (1.0 - delta_idle / delta_total) * 100.0))
        history = []
        for previous, current in zip(self._cpu_history, list(self._cpu_history)[1:]):
            delta_total = current[1] - previous[1]
            delta_idle = current[2] - previous[2]
            if delta_total > 0 and delta_idle >= 0:
                history.append(max(0.0, min(100.0, (1.0 - delta_idle / delta_total) * 100.0)))
        return usage, history, None

    def compute_memory_usage(self, metrics: dict) -> tuple[Optional[float], Optional[int], Optional[int], list[float], Optional[str]]:
        """Calculate memory usage from host MemTotal and MemAvailable."""
        total_entries = metrics.get("node_memory_MemTotal_bytes", [])
        available_entries = metrics.get("node_memory_MemAvailable_bytes", [])
        if not total_entries or not available_entries:
            return None, None, None, [], "Node Exporter did not provide memory metrics"

        total = total_entries[0]["value"]
        available = available_entries[0]["value"]
        if total <= 0 or available < 0:
            return None, int(total), int(available), [], "Memory metrics contain invalid values"

        usage = max(0.0, min(100.0, (total - available) / total * 100.0))
        self._mem_history.append((time.time(), usage))
        return usage, int(total), int(available), [value for _, value in self._mem_history], None

    def compute_disk_usage(self, metrics: dict) -> tuple[Optional[float], Optional[int], Optional[int], list[float], Optional[str]]:
        """Calculate usage for the host root filesystem."""
        size_by_mount = {
            entry["labels"].get("mountpoint"): entry["value"]
            for entry in metrics.get("node_filesystem_size_bytes", [])
            if entry["labels"].get("mountpoint") == "/"
        }
        avail_by_mount = {
            entry["labels"].get("mountpoint"): entry["value"]
            for entry in metrics.get("node_filesystem_avail_bytes", [])
            if entry["labels"].get("mountpoint") == "/"
        }
        total = size_by_mount.get("/")
        available = avail_by_mount.get("/")
        if total is None or available is None:
            return None, None, None, [], "Node Exporter did not provide root filesystem metrics"
        if total <= 0 or available < 0:
            return None, int(total), int(available), [], "Filesystem metrics contain invalid values"

        usage = max(0.0, min(100.0, (total - available) / total * 100.0))
        self._disk_history.append((time.time(), usage))
        return usage, int(total), int(available), [value for _, value in self._disk_history], None

    @staticmethod
    def _is_physical_interface(device: str) -> bool:
        if not device or device == "lo":
            return False
        return not device.lower().startswith(VIRTUAL_INTERFACE_PREFIXES)

    def compute_network_rates(self, metrics: dict) -> tuple[Optional[float], Optional[float], list[float], list[float], Optional[str]]:
        """Calculate physical-interface rates from the latest counter delta."""
        rx_samples = metrics.get("node_network_receive_bytes_total", [])
        tx_samples = metrics.get("node_network_transmit_bytes_total", [])
        if not rx_samples or not tx_samples:
            return None, None, list(self._net_rx_rate_history), list(self._net_tx_rate_history), "Node Exporter did not provide network metrics"

        rx = {
            item["labels"].get("device"): item["value"]
            for item in rx_samples
            if self._is_physical_interface(item["labels"].get("device", ""))
        }
        tx = {
            item["labels"].get("device"): item["value"]
            for item in tx_samples
            if self._is_physical_interface(item["labels"].get("device", ""))
        }
        if not rx or not tx:
            return None, None, list(self._net_rx_rate_history), list(self._net_tx_rate_history), "No physical network interfaces found"

        now = time.time()
        self._net_history.append((now, rx, tx))
        if len(self._net_history) < 2:
            return None, None, list(self._net_rx_rate_history), list(self._net_tx_rate_history), "Waiting for the next network sample"

        previous_time, previous_rx, previous_tx = self._net_history[-2]
        current_time, current_rx, current_tx = self._net_history[-1]
        elapsed = current_time - previous_time
        if elapsed <= 0:
            return None, None, list(self._net_rx_rate_history), list(self._net_tx_rate_history), "Invalid network sample interval"

        rx_deltas = [current_rx[device] - previous_rx[device] for device in current_rx.keys() & previous_rx.keys()]
        tx_deltas = [current_tx[device] - previous_tx[device] for device in current_tx.keys() & previous_tx.keys()]
        valid_rx = [delta for delta in rx_deltas if delta >= 0]
        valid_tx = [delta for delta in tx_deltas if delta >= 0]
        if not valid_rx or not valid_tx:
            return None, None, list(self._net_rx_rate_history), list(self._net_tx_rate_history), "Network counters reset or interfaces changed; waiting for stable samples"

        rx_rate = sum(valid_rx) / elapsed
        tx_rate = sum(valid_tx) / elapsed
        self._net_rx_rate_history.append(rx_rate)
        self._net_tx_rate_history.append(tx_rate)
        return rx_rate, tx_rate, list(self._net_rx_rate_history), list(self._net_tx_rate_history), None

    @staticmethod
    def _unavailable_metrics(error: str, last_update: Optional[float]) -> dict:
        return {
            "available": False,
            "error": error,
            "last_update": last_update,
            "cpu": {"usage": None, "history": [], "error": error},
            "memory": {"usage": None, "total": None, "available": None, "history": [], "error": error},
            "disk": {"usage": None, "total": None, "free": None, "history": [], "error": error},
            "network": {"rx_rate": None, "tx_rate": None, "rx_history": [], "tx_history": [], "error": error},
        }

    async def get_system_metrics(self) -> dict:
        """Fetch, parse, and compute all system metrics."""
        result = await self.fetch_metrics()
        if result["error"]:
            return self._unavailable_metrics(result["error"], self._last_fetch_time)

        metrics = self.parse_metrics(result["raw"])
        cpu_usage, cpu_history, cpu_error = self.compute_cpu_usage(metrics)
        mem_usage, mem_total, mem_available, mem_history, mem_error = self.compute_memory_usage(metrics)
        disk_usage, disk_total, disk_available, disk_history, disk_error = self.compute_disk_usage(metrics)
        rx_rate, tx_rate, rx_history, tx_history, network_error = self.compute_network_rates(metrics)

        self._last_fetch_time = time.time()
        return {
            "available": True,
            "error": None,
            "last_update": self._last_fetch_time,
            "cpu": {"usage": cpu_usage, "history": cpu_history, "error": cpu_error},
            "memory": {"usage": mem_usage, "total": mem_total, "available": mem_available, "history": mem_history, "error": mem_error},
            "disk": {"usage": disk_usage, "total": disk_total, "free": disk_available, "history": disk_history, "error": disk_error},
            "network": {"rx_rate": rx_rate, "tx_rate": tx_rate, "rx_history": rx_history, "tx_history": tx_history, "error": network_error},
        }


_system_monitor: Optional[SystemMonitor] = None


def get_system_monitor() -> SystemMonitor:
    global _system_monitor
    if _system_monitor is None:
        _system_monitor = SystemMonitor()
    return _system_monitor
