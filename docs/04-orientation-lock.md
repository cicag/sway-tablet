# Orientation Lock

Auto-rotate the sway output based on an accelerometer when **unlocked**, and
hold the current orientation when **locked**, mimicking how Android implement it.

## How it works

- `controlpanel` exposes an **Orientation** tile in the action bar.
  - **Unlocked** (`[+]`): `orientation-daemon` runs in the background, polling
    the accelerometer and calling `swaymsg output <name> transform <angle>`
    whenever the device is physically rotated.
  - **Locked** (`[-]`): the daemon stops; the screen stays at its current
    orientation no matter how you hold the tablet.
- Lock state is persisted to `~/.config/swaytablet/orientation-locked`, so it
  survives restarts.
- The daemon has **EMA smoothing** of raw accelerometer values so minor
  movements and sensor noise don't cause jitter.

## Configuration (environment variables)

All settings are configurable via environment variables.

| Variable | Default | Meaning |
|----------|---------|---------|
| `SENSOR_PATH` | auto-detect | IIO device directory containing `in_accel_x_raw` |
| `OUTPUT_NAME` | auto-detect | Sway output name (first non-headless output) |
| `POLL_INTERVAL_MS` | `1000` | Polling interval in milliseconds |
| `EMA_ALPHA` | `0.3` | Exponential moving average smoothing factor (0.0-1.0). Higher = faster response, more noise |
| `LOCK_STATE_FILE` | `~/.config/swaytablet/orientation-locked` | Lock state file path |
| `ORIENTATION_OFFSET` | `0` | Extra degrees (0/90/180/270) added to the computed transform, to correct for accelerometer mounting orientation in the device |

Example (launch manually with device-specific values):

```sh
SENSOR_PATH=/sys/bus/iio/devices/iio:device0 \
OUTPUT_NAME=DSI-1 \
POLL_INTERVAL_MS=1000 \
ORIENTATION_OFFSET=180 \
orientation-daemon &
```

## Files

| File | Role |
|------|------|
| `config/home/.local/bin/orientation-daemon` | Background accelerometer polling daemon |
| `config/home/.local/bin/controlpanel.py` | Orientation lock toggle tile in the control panel |

### Calibrating ORIENTATION_OFFSET

Accelerometers are mounted differently on every device, so the computed
transform may be off by 90/180/270 degrees. 
