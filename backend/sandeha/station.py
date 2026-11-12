"""Station-wide state shared by every product line (carried over from v1, now real):

* Emergency HOLD - a manual stop: every part is put on HOLD (no automatic verdict) until released.
* Hardware faults - injected failures that change real behaviour: a dead camera sends black frames
  (the quality gate HOLDs them), an overheated accelerator throttles inference, a broken conveyor
  encoder HOLDs parts (they can no longer be routed), a network outage queues messages.
* Alerts - persistent, acknowledgeable, resolvable (shift alarms, review overload, disputes, faults...).
* Audit log - who did what, when.
* Outbox - decisions published to the line (Zenoh/MQTT topic) and alerts to inspectors (Telegram);
  delivered when the network is up, queued while it is down.
* Telemetry - REAL host readings (CPU, RAM, GPU via nvidia-smi, disk) plus simulated station sensors
  (LED ring, conveyor), clearly labelled as simulated.
"""
from __future__ import annotations

import itertools
import json
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field

from .data import DATA_ROOT
from .events import bus

FAULTS = ("camera", "accelerator", "conveyor", "network")
ROLES = ("OPERATOR", "INSPECTOR", "QUALITY_MANAGER", "ADMIN")
_seq = itertools.count(1)


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Alert:
    id: str
    title: str
    message: str
    severity: str  # INFO / WARNING / CRITICAL
    category: str  # SHIFT / OVERLOAD / DISPUTE / HARDWARE / HOLD / FORECAST / REVIEWER / HIVE
    session: str | None
    created: str
    acknowledged: bool = False
    acknowledged_by: str | None = None
    resolved: bool = False
    action: str | None = None


@dataclass
class Station:
    name: str = "Station Alpha"
    hold: bool = False
    hold_reason: str = ""
    hold_since: str | None = None
    faults: set = field(default_factory=set)
    alerts: list = field(default_factory=list)
    audit: list = field(default_factory=list)
    outbox: list = field(default_factory=list)
    started: float = field(default_factory=time.time)
    settings: dict = field(default_factory=lambda: {"defaultBudget": 0.10, "falseRejectGuarantee": 0.02,
                                                    "costPerEscape": 2500, "costPerFalseReject": 150,
                                                    "costPerReview": 4, "overloadQueue": 12})
    lock: threading.RLock = field(default_factory=threading.RLock)

    # ------------------------------------------------------------------ alerts
    def raise_alert(self, title: str, message: str, severity: str, category: str, session: str | None = None,
                    action: str | None = None, dedupe: bool = True) -> Alert:
        with self.lock:
            if dedupe:
                for a in self.alerts:
                    if not a.resolved and a.title == title and a.session == session:
                        return a
            a = Alert(id=f"A{next(_seq):04d}", title=title, message=message, severity=severity, category=category,
                      session=session, created=now(), action=action)
            self.alerts.append(a)
            del self.alerts[:-300]
        bus.publish("alert", asdict(a))
        if severity == "CRITICAL":
            self.send("telegram", {"text": f"SANDEHA {severity}: {title} - {message}"})
        return a

    def ack(self, aid: str, by: str) -> Alert:
        a = self._alert(aid)
        a.acknowledged, a.acknowledged_by = True, by
        bus.publish("alert", asdict(a))
        return a

    def resolve(self, aid: str, by: str = "system") -> Alert:
        a = self._alert(aid)
        a.resolved, a.acknowledged = True, True
        a.acknowledged_by = a.acknowledged_by or by
        bus.publish("alert", asdict(a))
        return a

    def resolve_category(self, category: str, session: str | None = None) -> None:
        for a in list(self.alerts):
            if not a.resolved and a.category == category and (session is None or a.session == session):
                self.resolve(a.id)

    def _alert(self, aid: str) -> Alert:
        for a in self.alerts:
            if a.id == aid:
                return a
        raise KeyError(aid)

    # ------------------------------------------------------------------ audit / outbox
    def log(self, who: str, role: str, action: str, target: str = "", detail: dict | None = None) -> None:
        with self.lock:
            self.audit.append({"t": now(), "who": who, "role": role, "action": action, "target": target,
                               "detail": detail or {}})
            del self.audit[:-1000]

    def send(self, channel: str, payload: dict) -> str:
        """Telegram (inspectors) and Zenoh (line PLC) messages. Without credentials or a broker they are
        logged as 'simulated'; while the network is down they queue and flush on recovery."""
        status = "QUEUED_OFFLINE" if "network" in self.faults else "SIMULATED"
        with self.lock:
            self.outbox.append({"t": now(), "channel": channel, "status": status, "payload": payload})
            del self.outbox[:-500]
        return status

    def flush(self) -> int:
        n = 0
        with self.lock:
            for m in self.outbox:
                if m["status"] == "QUEUED_OFFLINE":
                    m["status"], n = "SIMULATED", n + 1
        return n

    # ------------------------------------------------------------------ hold + faults
    def set_hold(self, on: bool, reason: str, who: str) -> dict:
        self.hold, self.hold_reason = on, reason if on else ""
        self.hold_since = now() if on else None
        if on:
            self.raise_alert("Emergency HOLD engaged", reason or "Manual stop", "CRITICAL", "HOLD",
                             action="Release the HOLD once the cause is fixed")
        else:
            self.resolve_category("HOLD")
        self.log(who, "", "hold.on" if on else "hold.off", detail={"reason": reason})
        bus.publish("station", self.public())
        return self.public()

    def inject(self, fault: str, who: str) -> dict:
        if fault not in FAULTS:
            raise ValueError(f"fault must be one of {FAULTS}")
        self.faults.add(fault)
        text = {
            "camera": ("Camera offline", "The camera returns black frames. Every part is put on HOLD by the image check."),
            "accelerator": ("Accelerator overheating", "Inference is throttled. Parts take longer; nothing is decided blind."),
            "conveyor": ("Conveyor tracking lost", "Parts can no longer be routed to the right bin, so they are put on HOLD."),
            "network": ("Network offline", "Inspection continues locally. Messages to inspectors and the line are queued."),
        }[fault]
        self.raise_alert(text[0], text[1], "WARNING" if fault == "network" else "CRITICAL", "HARDWARE",
                         action="Restore the hardware, then confirm")
        self.log(who, "", "fault.inject", fault)
        bus.publish("station", self.public())
        return self.public()

    def restore(self, who: str) -> dict:
        self.faults.clear()
        flushed = self.flush()
        self.resolve_category("HARDWARE")
        self.log(who, "", "fault.restore", detail={"flushed": flushed})
        bus.publish("station", self.public())
        return self.public()

    def public(self) -> dict:
        return {"name": self.name, "hold": self.hold, "holdReason": self.hold_reason, "holdSince": self.hold_since,
                "faults": sorted(self.faults), "settings": self.settings,
                "alertsOpen": sum(1 for a in self.alerts if not a.resolved),
                "alertsUnacknowledged": sum(1 for a in self.alerts if not a.acknowledged)}

    # ------------------------------------------------------------------ telemetry
    def telemetry(self, sessions) -> dict:
        import psutil

        vm = psutil.virtual_memory()
        gpu = _nvidia()
        disk = shutil.disk_usage(DATA_ROOT)
        recs = [r for s in sessions for r in s.records[-200:]]
        lat = [r.latency_ms for r in recs if getattr(r, "latency_ms", None)]
        p50 = sorted(lat)[len(lat) // 2] if lat else None
        fps = (1000.0 / p50) if p50 else None
        slow = "accelerator" in self.faults
        from .persist import STORE

        saved = sum(f.stat().st_size for f in STORE.glob("*.pt")) / 1e6 if STORE.exists() else 0
        return {
            "measured": {
                "cpuPercent": psutil.cpu_percent(interval=0.15), "cpuCores": psutil.cpu_count(),
                "ramPercent": vm.percent, "ramUsedGB": round(vm.used / 1e9, 1), "ramTotalGB": round(vm.total / 1e9, 1),
                "gpu": gpu, "diskFreeGB": round(disk.free / 1e9, 1), "savedSessionsMB": round(saved, 1),
                "uptimeMin": round((time.time() - self.started) / 60, 1),
                "inferenceMsP50": round(p50, 1) if p50 else None, "partsPerSecond": round(fps, 1) if fps else None,
                "productLines": len(sessions), "partsInspected": sum(len(s.records) for s in sessions),
            },
            "simulated": {
                "camera": {"status": "OFFLINE" if "camera" in self.faults else "ONLINE", "source": "dataset feed / uploads"},
                "accelerator": {"status": "THROTTLED" if slow else "ONLINE", "tempC": 88.5 if slow else 52.0},
                "conveyor": {"status": "DESYNC" if "conveyor" in self.faults else "TRACKING", "speedMps": 0.35},
                "ledRing": {"status": "OK", "channels": ["TOP", "RIGHT", "BOTTOM", "LEFT"]},
                "network": {"status": "OFFLINE" if "network" in self.faults else "ONLINE",
                            "queued": sum(1 for m in self.outbox if m["status"] == "QUEUED_OFFLINE")},
            },
            "faults": sorted(self.faults), "hold": self.hold,
        }


def _nvidia() -> dict | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3).stdout.strip()
        name, util, temp, used, total, power = [x.strip() for x in out.split(",")[:6]]
        return {"name": name, "utilPercent": float(util), "tempC": float(temp), "memUsedMB": float(used),
                "memTotalMB": float(total), "powerW": float(power)}
    except Exception:
        return None


STATION = Station()
