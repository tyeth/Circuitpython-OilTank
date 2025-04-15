# CircuitPython Oil Tank Monitor

This project is a distance monitor for oil tanks using an Adafruit ESP32-S2 Feather with a VL53L0X/VL53L1X distance sensor. It reports measurements to Adafruit IO and can be configured using on-board buttons.

## Installation

Install requirements:

```shell
pip install -r requirements.txt
```

For development on desktop, set up the CircuitPython stubs:

```shell
circuitpython_setboard adafruit_feather_esp32s2_reverse_tft
```

## Configuration

Configuration is stored in `settings.toml`. The following settings are available:

- `CIRCUITPY_WIFI_SSID` - WiFi network name
- `CIRCUITPY_WIFI_PASSWORD` - WiFi password
- `ADAFRUIT_AIO_USERNAME` - Adafruit IO username
- `ADAFRUIT_AIO_KEY` - Adafruit IO key
- `ADAFRUIT_AIO_FEED_NAME` - Feed name for distance readings (default: `oil-tank-distance-sensor`)

## Running on Desktop

This project can now run on desktop environments (Linux, macOS, Windows) using the Blinka compatibility layer and PyGame for display emulation. To run on desktop:

1. Install the required packages:
   ```shell
   pip install -r requirements.txt
   ```

2. Run the script:
   ```shell
   python main.py
   ```

### Desktop Features

In desktop mode, the application:
- Simulates distance readings (no actual sensor required)
- Shows a PyGame window to simulate the TFT display (if PyGame is properly installed)
- Takes readings at regular intervals (every 30 seconds)
- Simulates sending data to Adafruit IO (no actual data is sent)
- Maintains state between runs in a local `state.json` file

### Desktop Controls

When running on desktop:

- Use key `1` to decrease hysteresis (equivalent to button D0)
- Use key `2` to increase hysteresis (equivalent to button D1) 
- Use key `3` to force a manual report (equivalent to button D2)
- Close the window to exit

### Troubleshooting Desktop Mode

If you encounter display issues:
- Make sure PyGame is properly installed
- The application will fall back to console-only mode if the display can't be initialized
- Check terminal output for error messages

## Running on CircuitPython Hardware

Upload all files to your CircuitPython device. The code will run automatically.

### Hardware Controls

- Button D0: Decrease hysteresis
- Button D1: Increase hysteresis
- Button D2: Force a manual report

### Sleep Mode

On hardware, the device will go into deep sleep after a configurable period to save power. It will wake up on button press or when the timer expires.
