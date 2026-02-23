# blackroad-energy-monitor

A real-time energy-consumption tracker for smart homes, IoT deployments, and server rooms. Log wattage readings from any device, get daily kWh and cost estimates, and receive automatic anomaly alerts when a device's power draw deviates significantly from its historical baseline.

Anomaly detection uses a statistical baseline computed from the last 100 readings per device. If a new reading is more than two standard deviations away from the rolling mean, an alert is written to the database and printed to the terminal — no external alerting service needed.

Part of the **BlackRoad OS** developer toolchain — pair it with a Raspberry Pi and a smart plug to get a complete home-energy dashboard in minutes.

## Features

- **Multi-device tracking** — register unlimited devices with location tags
- **Wattage logging** — timestamped readings per device
- **Daily statistics** — avg/max/min watts, kWh, and USD cost estimate
- **Statistical anomaly detection** — 2-σ spike detection with automatic alerts
- **Threshold alerts** — configurable per-device wattage ceiling
- **Cost calculation** — configurable rate (default `$0.12/kWh`)
- **JSON report export** — daily stats + anomaly history
- **SQLite persistence** — `~/.blackroad/energy_monitor.db`
- **CLI interface** — `add-device`, `add-reading`, `list`, `status`, `anomalies`, `export`

## Installation

```bash
git clone https://github.com/BlackRoad-OS/blackroad-energy-monitor.git
cd blackroad-energy-monitor
python3 src/energy_monitor.py
```

Run the test suite:

```bash
pip install pytest
pytest tests/ -v
```

## Usage

```bash
# Register a device
python3 src/energy_monitor.py add-device "server-01" "Home Server" "office"
python3 src/energy_monitor.py add-device "ac-living" "Living Room AC" "living-room"

# Log a wattage reading
python3 src/energy_monitor.py add-reading "server-01" "Home Server" 185.5 "office"
python3 src/energy_monitor.py add-reading "ac-living" "Living Room AC" 2400.0

# Daily usage summary
python3 src/energy_monitor.py list
python3 src/energy_monitor.py list 2024-07-15   # specific date

# Overall status (total watts, kWh, cost)
python3 src/energy_monitor.py status

# View anomaly alerts
python3 src/energy_monitor.py anomalies

# Export JSON report
python3 src/energy_monitor.py export /tmp/energy_report.json
```

### Example output

```
=== Daily Energy Usage ===
  Home Server [office]
    ████░░░░░░░░░░░░░░░░ 185.5W avg | 4.452 kWh | $0.5342
  Living Room AC [living-room]
    ████████████████░░░░ 2400.0W avg | 57.6 kWh | $6.912
```

## API

### `EnergyReading`

| Field | Type | Description |
|---|---|---|
| `device_id` | `str` | Unique device identifier |
| `device_name` | `str` | Human-readable name |
| `watts` | `float` | Instantaneous power draw |
| `location` | `str` | Room / zone label |

### `EnergyMonitor`

| Method | Description |
|---|---|
| `add_device(id, name, location, threshold)` | Register a device |
| `add_reading(reading)` | Log a wattage reading, run anomaly check |
| `get_daily_usage(device_id, date_str)` | Return `DeviceStats` for a date |
| `get_anomalies(limit)` | Recent anomaly alerts |
| `export_report(path)` | Write JSON daily report |

## License

MIT © BlackRoad OS, Inc.
