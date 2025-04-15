# Low Power Distance Monitor with Adafruit IO
# For CircuitPython 9 on ESP32-S2 Reverse TFT Feather with VL53L0X/VL53L1X sensor

import time
import board
import busio
import digitalio
import displayio
import terminalio
import adafruit_vl53l0x
import supervisor
import wifi
import socketpool
import ssl
import adafruit_requests
import microcontroller
import alarm
import json
import os
from adafruit_display_text import label

# Configuration from settings.toml
ADAFRUIT_IO_URL = "https://io.adafruit.com/api/v2/"
ADAFRUIT_USERNAME = os.getenv("ADAFRUIT_IO_USERNAME")
ADAFRUIT_KEY = os.getenv("ADAFRUIT_IO_KEY")
FEED_NAME = os.getenv("ADAFRUIT_IO_FEED_NAME", "distance-sensor")

# Time settings with defaults
REPORT_INTERVAL = int(os.getenv("DISTANCE_MONITOR_REPORT_INTERVAL", "10800"))  # 3 hours in seconds (default)
MIN_REPORT_INTERVAL = int(os.getenv("DISTANCE_MONITOR_MIN_REPORT_INTERVAL", "86400"))  # 24 hours in seconds (default)
AWAKE_TIME = int(os.getenv("DISTANCE_MONITOR_AWAKE_TIME", "30"))  # seconds to stay awake after button press (default)
MAX_STORED_READINGS = int(os.getenv("DISTANCE_MONITOR_MAX_STORED_READINGS", "5"))  # number of previous readings to store (default)

# Default hysteresis - can be overridden in settings.toml or by user via buttons
DEFAULT_HYSTERESIS = float(os.getenv("DISTANCE_MONITOR_DEFAULT_HYSTERESIS", "2.0"))  # 2cm change threshold (default)
MIN_HYSTERESIS = float(os.getenv("DISTANCE_MONITOR_MIN_HYSTERESIS", "0.5"))  # Minimum allowed hysteresis value
MAX_HYSTERESIS = float(os.getenv("DISTANCE_MONITOR_MAX_HYSTERESIS", "10.0"))  # Maximum allowed hysteresis value

# WiFi connection parameters
WIFI_SSID = os.getenv("CIRCUITPY_WIFI_SSID")
WIFI_PASSWORD = os.getenv("CIRCUITPY_WIFI_PASSWORD")

# Setup display and backlight
def setup_display():
    # The display is already initialized and available as board.DISPLAY
    display = board.DISPLAY
    
    # Setup backlight control
    try:
        # First try the dedicated TFT_BACKLIGHT pin if available
        if hasattr(board, 'TFT_BACKLIGHT'):
            backlight = digitalio.DigitalInOut(board.TFT_BACKLIGHT)
            backlight.direction = digitalio.Direction.OUTPUT
            backlight.value = True  # Turn on the backlight
        else:
            # If no dedicated backlight pin, we don't control the backlight
            backlight = None
    except Exception as e:
        print(f"Backlight setup error: {e}")
        backlight = None
    
    # Create a group to hold display items
    main_group = displayio.Group()
    display.root_group=main_group
    
    return display, main_group, backlight

# Setup buttons
def setup_buttons():
    button_pins = [board.D0, board.D1, board.D2]
    buttons = []
    
    for pin in button_pins:
        btn = digitalio.DigitalInOut(pin)
        btn.direction = digitalio.Direction.INPUT
        btn.pull = digitalio.Pull.UP
        buttons.append(btn)
    
    return buttons

# Function to create the display interface
def create_display_interface(main_group, current_distance, past_readings, hysteresis, countdown=None):
    # Clear the display
    while len(main_group) > 0:
        main_group.pop()
    
    # Set up text area for title
    title_text = label.Label(terminalio.FONT, text="Distance Monitor", scale=2)
    title_text.x = 70
    title_text.y = 20
    main_group.append(title_text)
    
    # Current reading
    current_text = label.Label(
        terminalio.FONT, 
        text=f"Current: {current_distance:.1f} cm", 
        scale=2
    )
    current_text.x = 20
    current_text.y = 50
    main_group.append(current_text)
    
    # Past readings
    history_title = label.Label(terminalio.FONT, text="Past Readings:", scale=1)
    history_title.x = 20
    history_title.y = 80
    main_group.append(history_title)
    
    y_pos = 100
    for i, reading in enumerate(past_readings):
        history_text = label.Label(
            terminalio.FONT, 
            text=f"{i+1}: {reading:.1f} cm", 
            scale=1
        )
        history_text.x = 30
        history_text.y = y_pos
        main_group.append(history_text)
        y_pos += 20
    
    # Hysteresis setting
    hysteresis_text = label.Label(
        terminalio.FONT, 
        text=f"Hysteresis: {hysteresis:.1f} cm", 
        scale=1
    )
    hysteresis_text.x = 20
    hysteresis_text.y = 190
    main_group.append(hysteresis_text)
    
    # Button labels
    button_labels = [
        label.Label(terminalio.FONT, text="D0: Hyst-", scale=1),
        label.Label(terminalio.FONT, text="D1: Hyst+", scale=1),
        label.Label(terminalio.FONT, text="D2: Report", scale=1)
    ]
    
    y_pos = 210
    for i, btn_label in enumerate(button_labels):
        btn_label.x = 20 + (i * 100)
        btn_label.y = y_pos
        main_group.append(btn_label)
    
    # Countdown timer if provided
    if countdown is not None:
        countdown_text = label.Label(
            terminalio.FONT, 
            text=f"Sleep in: {countdown}s", 
            scale=1
        )
        countdown_text.x = 230
        countdown_text.y = 190
        main_group.append(countdown_text)

# Function to connect to WiFi
def connect_wifi():
    print("Connecting to WiFi...")
    wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
    print(f"Connected to {WIFI_SSID}!")
    print(f"IP Address: {wifi.radio.ipv4_address}")

# Function to send data to Adafruit IO
def send_to_adafruit_io(distance):
    # Create session and make request
    pool = socketpool.SocketPool(wifi.radio)
    requests = adafruit_requests.Session(pool, ssl.create_default_context())
    
    # Construct URL and headers
    url = f"{ADAFRUIT_IO_URL}feeds/{FEED_NAME}/data"
    headers = {
        "X-AIO-Key": ADAFRUIT_KEY,
        "Content-Type": "application/json"
    }
    
    # Create data payload
    data = {"value": distance}
    
    # Send the data
    print(f"Posting distance: {distance}cm to Adafruit IO...")
    response = requests.post(url, headers=headers, json=data)
    print(f"Response: {response.status_code}")
    response.close()

# Initialize the I2C bus
i2c = busio.I2C(board.SCL, board.SDA)

# Initialize the VL53L0X sensor
sensor = adafruit_vl53l0x.VL53L0X(i2c)

# For better accuracy, you can set timing budget
sensor.measurement_timing_budget = 200000  # 200ms

# Global variables to track time and last readings
last_report_time = 0
last_distance = 0
past_readings = []
hysteresis = DEFAULT_HYSTERESIS  # Default hysteresis value from settings.toml

# Initialize display
display, main_group, backlight = setup_display()

# Initialize buttons
buttons = setup_buttons()

# Function to read the current distance
def read_distance():
    # Measure distance multiple times and average for reliability
    total_distance = 0
    samples = 5
    
    for _ in range(samples):
        total_distance += sensor.range / 10  # Convert from mm to cm
        time.sleep(0.1)
    
    return total_distance / samples

# Check if waking from deep sleep
wake_reason = None
if supervisor.runtime.run_reason is supervisor.RunReason.STARTUP:
    print("First boot, initializing...")
    last_report_time = 0
    last_distance = 0
    past_readings = []
elif isinstance(alarm.wake_alarm, alarm.pin.PinAlarm):
    print("Woke from button press!")
    wake_reason = "button"
elif alarm.wake_alarm:
    print("Woke from time alarm!")
    wake_reason = "timer"
    
# Try to load previous state from a file
try:
    with open("state.json", "r") as f:
        state = json.load(f)
        last_report_time = state["last_report_time"]
        last_distance = state["last_distance"]
        past_readings = state.get("past_readings", [])
        hysteresis = state.get("hysteresis", DEFAULT_HYSTERESIS)
        print(f"Loaded state: last report at {last_report_time}, distance: {last_distance}cm")
        print(f"Hysteresis: {hysteresis}cm")
except (OSError, ValueError):
    print("No valid state file found, starting fresh")
    last_report_time = 0
    last_distance = 0
    past_readings = []

# Main loop
def main():
    global last_report_time, last_distance, past_readings, hysteresis
    
    current_time = time.monotonic()
    current_distance = read_distance()
    print(f"Current distance: {current_distance:.1f}cm")
    
    # Update past readings
    if last_distance != 0:  # Don't add the initial reading if it's just starting up
        past_readings.insert(0, last_distance)
        # Keep only the last MAX_STORED_READINGS
        past_readings = past_readings[:MAX_STORED_READINGS]
    
    # Determine if we need to report based on criteria
    time_since_last_report = current_time - last_report_time
    distance_change = abs(current_distance - last_distance)
    
    should_report = (
        (time_since_last_report >= REPORT_INTERVAL) or  # Report every 3 hours
        (time_since_last_report >= MIN_REPORT_INTERVAL) or  # Report at least daily
        (distance_change >= hysteresis) or  # Report on significant change
        (wake_reason == "button")  # Report if woken by button
    )
    
    # Show the current readings on display
    create_display_interface(main_group, current_distance, past_readings, hysteresis)
    
    if should_report:
        # Connect to WiFi
        connect_wifi()
        
        # Report to Adafruit IO
        send_to_adafruit_io(current_distance)
        
        # Update last reported values
        last_report_time = current_time
        
        # Disconnect WiFi to save power
        wifi.radio.enabled = False
    
    # Update the last distance
    last_distance = current_distance
    
    # Handle button interaction and display for AWAKE_TIME seconds
    start_time = time.monotonic()
    stay_awake = True
    
    while stay_awake and (time.monotonic() - start_time < AWAKE_TIME):
        # Calculate remaining time
        remaining_time = int(AWAKE_TIME - (time.monotonic() - start_time))
        
        # Update display with countdown
        create_display_interface(main_group, current_distance, past_readings, hysteresis, remaining_time)
        
        # Check buttons
        # D0: Decrease hysteresis
        if not buttons[0].value:
            hysteresis = max(MIN_HYSTERESIS, hysteresis - 0.5)  # Respect minimum from settings
            print(f"Hysteresis decreased to {hysteresis}cm")
            create_display_interface(main_group, current_distance, past_readings, hysteresis, remaining_time)
            time.sleep(0.3)  # Debounce
        
        # D1: Increase hysteresis
        if not buttons[1].value:
            hysteresis = min(MAX_HYSTERESIS, hysteresis + 0.5)  # Respect maximum from settings
            print(f"Hysteresis increased to {hysteresis}cm")
            create_display_interface(main_group, current_distance, past_readings, hysteresis, remaining_time)
            time.sleep(0.3)  # Debounce
        
        # D2: Force report
        if not buttons[2].value:
            print("Manual report requested")
            # Connect to WiFi if not already connected
            if not wifi.radio.connected:
                connect_wifi()
            
            # Report to Adafruit IO
            send_to_adafruit_io(current_distance)
            last_report_time = time.monotonic()
            
            # Reset the countdown timer
            start_time = time.monotonic()
            time.sleep(0.3)  # Debounce
        
        time.sleep(0.1)
        
    # Save state to a file
    try:
        with open("state.json", "w") as f:
            json.dump({
                "last_report_time": last_report_time,
                "last_distance": last_distance,
                "past_readings": past_readings,
                "hysteresis": hysteresis
            }, f)
        print("State saved")
    except OSError as e:
        print(f"Error saving state: {e}")
    
    # Calculate time until next wake
    time_until_next_check = min(REPORT_INTERVAL, MIN_REPORT_INTERVAL - time_since_last_report)
    if time_until_next_check < 0:
        time_until_next_check = REPORT_INTERVAL
    
    print(f"Going to sleep for {time_until_next_check} seconds")
    
    # Set up time alarm
    time_alarm = alarm.time.TimeAlarm(monotonic_time=time.monotonic() + time_until_next_check)
    
    # Set up pin alarms for D0, D1, and D2
    pin_alarms = []
    for button in buttons:
        pin_alarm = alarm.pin.PinAlarm(pin=button.pin, value=False, pull=True)
        pin_alarms.append(pin_alarm)
    
    # Clear the display and turn off backlight before sleep to save power
    display.root_group = displayio.Group()
    if backlight:
        backlight.value = False
    
    # Go to deep sleep, wake on any of the alarms
    alarm.exit_and_deep_sleep_until_alarms(time_alarm, *pin_alarms)

# Run the main program
try:
    main()
except Exception as e:
    print(f"Error occurred: {e}")
    # Display error on screen
    error_group = displayio.Group()
    error_text = label.Label(terminalio.FONT, text=f"ERROR: {str(e)}", scale=1)
    error_text.x = 10
    error_text.y = 120
    error_group.append(error_text)
    display.root_group = error_group
    time.sleep(10)  # Show error for 10 seconds
    # Reset the microcontroller on error
    microcontroller.reset()