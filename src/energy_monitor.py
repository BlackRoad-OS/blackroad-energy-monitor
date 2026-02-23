#!/usr/bin/env python3
"""
BlackRoad Energy Monitor
Production module for monitoring energy consumption and detecting anomalies.
"""

import sqlite3
import json
import sys
import os
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional, List, Dict

GREEN = '\033[0;32m'
RED = '\033[0;31m'
CYAN = '\033[0;36m'
YELLOW = '\033[1;33m'
NC = '\033[0m'

DB_PATH = os.path.expanduser("~/.blackroad/energy_monitor.db")
COST_PER_KWH = 0.12  # USD


@dataclass
class EnergyReading:
    device_id: str
    device_name: str
    watts: float
    timestamp: Optional[str] = None
    location: str = "default"
    id: Optional[int] = None


@dataclass
class EnergyAlert:
    device_id: str
    device_name: str
    alert_type: str   # anomaly, high_usage, threshold
    watts: float
    baseline_watts: float
    deviation_pct: float
    message: str
    created_at: str


@dataclass
class DeviceStats:
    device_id: str
    device_name: str
    location: str
    avg_watts: float
    max_watts: float
    min_watts: float
    daily_kwh: float
    daily_cost_usd: float
    reading_count: int
    last_reading_at: Optional[str]


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            device_id TEXT PRIMARY KEY,
            device_name TEXT NOT NULL,
            location TEXT DEFAULT 'default',
            threshold_watts REAL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            device_name TEXT NOT NULL,
            watts REAL NOT NULL,
            location TEXT DEFAULT 'default',
            timestamp TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            device_name TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            watts REAL,
            baseline_watts REAL,
            deviation_pct REAL,
            message TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


class EnergyMonitor:
    def __init__(self):
        init_db()
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row

    def close(self):
        self.conn.close()

    def add_device(self, device_id: str, device_name: str,
                   location: str = "default", threshold_watts: float = 0.0):
        c = self.conn.cursor()
        try:
            c.execute("""
                INSERT INTO devices (device_id, device_name, location, threshold_watts, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (device_id, device_name, location, threshold_watts, datetime.utcnow().isoformat()))
            self.conn.commit()
            print(f"{GREEN}✓ Added device: {device_name} ({device_id}){NC}")
        except sqlite3.IntegrityError:
            print(f"{YELLOW}⚠ Device '{device_id}' already exists{NC}")

    def add_reading(self, reading: EnergyReading) -> EnergyReading:
        reading.timestamp = reading.timestamp or datetime.utcnow().isoformat()
        c = self.conn.cursor()
        c.execute("""
            INSERT INTO readings (device_id, device_name, watts, location, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (reading.device_id, reading.device_name, reading.watts,
              reading.location, reading.timestamp))
        reading.id = c.lastrowid

        # Check for anomaly
        c.execute("""
            SELECT watts FROM readings WHERE device_id = ?
            ORDER BY timestamp DESC LIMIT 100
        """, (reading.device_id,))
        history = [r["watts"] for r in c.fetchall()]

        if len(history) >= 10:
            baseline = statistics.mean(history)
            std = statistics.stdev(history) if len(history) > 1 else 0
            if std > 0 and abs(reading.watts - baseline) > 2 * std:
                deviation = ((reading.watts - baseline) / baseline) * 100 if baseline > 0 else 0
                msg = (f"Anomaly: {reading.watts:.1f}W vs baseline {baseline:.1f}W "
                       f"({deviation:+.1f}%)")
                c.execute("""
                    INSERT INTO alerts (device_id, device_name, alert_type, watts,
                        baseline_watts, deviation_pct, message, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (reading.device_id, reading.device_name, "anomaly",
                      reading.watts, round(baseline, 2), round(deviation, 2),
                      msg, datetime.utcnow().isoformat()))
                print(f"{RED}⚠ ANOMALY: {msg}{NC}")

        # Threshold check
        c.execute("SELECT threshold_watts FROM devices WHERE device_id = ?", (reading.device_id,))
        dev = c.fetchone()
        if dev and dev["threshold_watts"] > 0 and reading.watts > dev["threshold_watts"]:
            print(f"{YELLOW}⚠ Threshold exceeded: {reading.watts}W > {dev['threshold_watts']}W{NC}")

        self.conn.commit()
        return reading

    def get_daily_usage(self, device_id: Optional[str] = None,
                        date_str: Optional[str] = None) -> List[DeviceStats]:
        date = date_str or datetime.utcnow().strftime("%Y-%m-%d")
        c = self.conn.cursor()
        query = """
            SELECT device_id, device_name, location,
                   AVG(watts) as avg_watts, MAX(watts) as max_watts,
                   MIN(watts) as min_watts, COUNT(*) as cnt,
                   MAX(timestamp) as last_ts
            FROM readings
            WHERE timestamp LIKE ?
        """
        params = [f"{date}%"]
        if device_id:
            query += " AND device_id = ?"
            params.append(device_id)
        query += " GROUP BY device_id, device_name, location"
        c.execute(query, params)

        results = []
        for r in c.fetchall():
            hours = 24.0
            kwh = (r["avg_watts"] * hours) / 1000.0
            cost = kwh * COST_PER_KWH
            results.append(DeviceStats(
                device_id=r["device_id"], device_name=r["device_name"],
                location=r["location"], avg_watts=round(r["avg_watts"], 2),
                max_watts=round(r["max_watts"], 2), min_watts=round(r["min_watts"], 2),
                daily_kwh=round(kwh, 4), daily_cost_usd=round(cost, 4),
                reading_count=r["cnt"], last_reading_at=r["last_ts"]
            ))
        return results

    def get_anomalies(self, limit: int = 20) -> List[dict]:
        c = self.conn.cursor()
        c.execute("""
            SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?
        """, (limit,))
        return [dict(r) for r in c.fetchall()]

    def export_report(self, output_path: str = "/tmp/energy_report.json"):
        stats = self.get_daily_usage()
        anomalies = self.get_anomalies()
        total_kwh = sum(s.daily_kwh for s in stats)
        total_cost = sum(s.daily_cost_usd for s in stats)
        data = {
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "devices": [asdict(s) for s in stats],
            "recent_anomalies": anomalies,
            "summary": {
                "total_daily_kwh": round(total_kwh, 4),
                "total_daily_cost_usd": round(total_cost, 4),
                "device_count": len(stats),
                "anomaly_count": len(anomalies),
            },
            "exported_at": datetime.utcnow().isoformat()
        }
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"{GREEN}✓ Report exported to {output_path}{NC}")
        return output_path


def usage_bar(watts: float, max_watts: float = 3000.0) -> str:
    pct = min(1.0, watts / max_watts)
    filled = int(pct * 20)
    color = GREEN if pct < 0.5 else (YELLOW if pct < 0.8 else RED)
    return f"{color}{'█' * filled}{'░' * (20 - filled)}{NC}"


def main():
    monitor = EnergyMonitor()
    args = sys.argv[1:]
    if not args:
        print(f"{CYAN}BlackRoad Energy Monitor{NC}")
        print("Commands: list [date], add-device <id> <name> [location],")
        print("          add-reading <device_id> <name> <watts> [location],")
        print("          status, anomalies, export")
        monitor.close()
        return
    cmd = args[0]
    rest = args[1:]
    if cmd == "list":
        date = rest[0] if rest else None
        stats = monitor.get_daily_usage(date_str=date)
        if not stats:
            print(f"{YELLOW}No readings for today. Use 'add-reading' to log data.{NC}")
        else:
            print(f"\n{CYAN}=== Daily Energy Usage ==={NC}")
            for s in stats:
                bar = usage_bar(s.avg_watts)
                print(f"  {CYAN}{s.device_name}{NC} [{s.location}]")
                print(f"    {bar} {s.avg_watts}W avg | "
                      f"{s.daily_kwh} kWh | ${s.daily_cost_usd:.4f}")
    elif cmd == "add-device":
        if len(rest) < 2:
            print(f"{RED}Usage: add-device <id> <name> [location]{NC}")
        else:
            loc = rest[2] if len(rest) > 2 else "default"
            monitor.add_device(rest[0], rest[1], loc)
    elif cmd == "add-reading":
        if len(rest) < 3:
            print(f"{RED}Usage: add-reading <device_id> <name> <watts> [location]{NC}")
        else:
            loc = rest[3] if len(rest) > 3 else "default"
            r = EnergyReading(device_id=rest[0], device_name=rest[1],
                              watts=float(rest[2]), location=loc)
            monitor.add_reading(r)
            print(f"{GREEN}✓ Reading logged: {r.device_name} {r.watts}W{NC}")
    elif cmd == "status":
        stats = monitor.get_daily_usage()
        total_w = sum(s.avg_watts for s in stats)
        total_kwh = sum(s.daily_kwh for s in stats)
        print(f"\n{CYAN}=== Energy Status ==={NC}")
        print(f"  Active Devices:   {len(stats)}")
        print(f"  Total Power:      {total_w:.1f}W")
        print(f"  Est. Daily:       {total_kwh:.2f} kWh")
        print(f"  Est. Daily Cost:  ${total_kwh * COST_PER_KWH:.4f}")
    elif cmd == "anomalies":
        anomalies = monitor.get_anomalies(20)
        if not anomalies:
            print(f"{GREEN}No anomalies detected.{NC}")
        else:
            print(f"\n{RED}=== Recent Anomalies ({len(anomalies)}) ==={NC}")
            for a in anomalies:
                print(f"  {a['created_at'][:19]} | {a['device_name']} | {a['message']}")
    elif cmd == "export":
        path = rest[0] if rest else "/tmp/energy_report.json"
        monitor.export_report(path)
    else:
        print(f"{RED}Unknown command: {cmd}{NC}")
    monitor.close()


if __name__ == "__main__":
    main()
