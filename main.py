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
# Import ScrollingLabel for better text display
from adafruit_display_text import label, scrolling_label

# Configuration from settings.toml
ADAFRUIT_AIO_URL = "https://io.adafruit.com/api/v2/"

# Check for required credentials with fallbacks
ADAFRUIT_USERNAME = os.getenv("ADAFRUIT_AIO_USERNAME", "")
if not ADAFRUIT_USERNAME:
    print("WARNING: ADAFRUIT_AIO_USERNAME not set in settings.toml")

ADAFRUIT_KEY = os.getenv("ADAFRUIT_AIO_KEY", "")
if not ADAFRUIT_KEY:
    print("WARNING: ADAFRUIT_AIO_KEY not set in settings.toml")

FEED_NAME = os.getenv("ADAFRUIT_AIO_FEED_NAME", "distance-sensor")

# Time settings with defaults
REPORT_INTERVAL = int(os.getenv("DISTANCE_MONITOR_REPORT_INTERVAL", "10800"))  # 3 hours in seconds (default)
MIN_REPORT_INTERVAL = int(os.getenv("DISTANCE_MONITOR_MIN_REPORT_INTERVAL", "86400"))  # 24 hours in seconds (default)
AWAKE_TIME = int(os.getenv("DISTANCE_MONITOR_AWAKE_TIME", "30"))  # seconds to stay awake after button press (default)
MAX_STORED_READINGS = int(os.getenv("DISTANCE_MONITOR_MAX_STORED_READINGS", "5"))  # number of previous readings to store (default)

# Default hysteresis - can be overridden in settings.toml or by user via buttons
DEFAULT_HYSTERESIS = float(os.getenv("DISTANCE_MONITOR_DEFAULT_HYSTERESIS", "2.0"))  # 2cm change threshold (default)
MIN_HYSTERESIS = float(os.getenv("DISTANCE_MONITOR_MIN_HYSTERESIS", "0.5"))  # Minimum allowed hysteresis value
MAX_HYSTERESIS = float(os.getenv("DISTANCE_MONITOR_MAX_HYSTERESIS", "10.0"))  # Maximum allowed hysteresis value

# WiFi connection parameters with warnings for missing credentials
WIFI_SSID = os.getenv("CIRCUITPY_WIFI_SSID", "")
if not WIFI_SSID:
    print("WARNING: CIRCUITPY_WIFI_SSID not set in settings.toml")

WIFI_PASSWORD = os.getenv("CIRCUITPY_WIFI_PASSWORD", "")
if not WIFI_PASSWORD:
    print("WARNING: CIRCUITPY_WIFI_PASSWORD not set in settings.toml")

# Setup display and backlight
def setup_display():
    # The display is already initialized and available as board.DISPLAY
    display = board.DISPLAY
    
    # Setup backlight control with proper error handling
    backlight = None
    try:
        # First try the dedicated TFT_BACKLIGHT pin if available
        if hasattr(board, 'TFT_BACKLIGHT'):
            # Check if the pin is already in use
            try:
                backlight = digitalio.DigitalInOut(board.TFT_BACKLIGHT)
                backlight.direction = digitalio.Direction.OUTPUT
                backlight.value = True  # Turn on the backlight
            except ValueError as e:
                print(f"Backlight setup error: {e}")
                # Pin is in use, don't try to control it
                backlight = None
    except Exception as e:
        print(f"Backlight setup error: {e}")
        backlight = None
    
    # Create a group to hold display items
    main_group = displayio.Group()
    
    # Use root_group assignment instead of show() in CircuitPython 9
    display.root_group = main_group
    
    return display, main_group, backlight

# Setup buttons
def setup_buttons():
    button_pins = [board.D0, board.D1, board.D2]
    buttons = []
    
    for pin in button_pins:
        btn = digitalio.DigitalInOut(pin)
        btn.direction = digitalio.Direction.INPUT
        btn.pull = digitalio.Pull.UP
        # Store both the DigitalInOut object and the original pin
        buttons.append({"dio": btn, "pin": pin})
    
    return buttons

# Function to create the display interface with adaptive text sizing
def create_display_interface(main_group, current_distance, past_readings, hysteresis, countdown=None):
    # Clear the display
    while len(main_group) > 0:
        main_group.pop()
    
    # Get screen dimensions
    display_width = board.DISPLAY.width if hasattr(board.DISPLAY, 'width') else 320
    display_height = board.DISPLAY.height if hasattr(board.DISPLAY, 'height') else 240
    
    # Adjust text scale based on screen size
    title_scale = 2 if display_width >= 240 else 1
    reading_scale = 2 if display_width >= 240 else 1
    info_scale = 1
    
    # Calculate margins and spacing based on display size
    x_margin = int(display_width * 0.05)  # 5% margin
    y_start = int(display_height * 0.1)   # Start 10% from top
    y_spacing = int(display_height * 0.08)  # Spacing is 8% of height
    
    # Set up text area for title
    title_text = label.Label(terminalio.FONT, text="Distance Monitor", scale=title_scale)
    title_text.x = x_margin
    title_text.y = y_start
    main_group.append(title_text)
    
    # Current reading
    current_y = y_start + y_spacing
    current_text = label.Label(
        terminalio.FONT, 
        text=f"Current: {current_distance:.1f} cm", 
        scale=reading_scale
    )
    current_text.x = x_margin
    current_text.y = current_y
    main_group.append(current_text)
    
    # Past readings with scrolling if needed
    history_y = current_y + y_spacing
    history_title = label.Label(terminalio.FONT, text="Past Readings:", scale=info_scale)
    history_title.x = x_margin
    history_title.y = history_y
    main_group.append(history_title)
    
    # Use scrolling labels for past readings if they're too long
    max_width = display_width - (2 * x_margin)
    
    history_y += int(y_spacing * 0.8)
    for i, reading in enumerate(past_readings):
        reading_text = f"{i+1}: {reading:.1f} cm"
        # Check if the text would be too wide
        text_width = len(reading_text) * 6 * info_scale  # Approximate width
        
        if text_width > max_width:
            # Use scrolling label for wide text
            history_text = scrolling_label.ScrollingLabel(
                terminalio.FONT,
                text=reading_text,
                max_characters=int(max_width / (6 * info_scale)),
                animate_time=0.3,
                scale=info_scale
            )
        else:
            # Use regular label for text that fits
            history_text = label.Label(
                terminalio.FONT, 
                text=reading_text, 
                scale=info_scale
            )
        
        history_text.x = x_margin + 10
        history_text.y = history_y + (i * int(y_spacing * 0.6))
        
        # Don't add more items than will fit on screen
        if history_text.y < display_height - y_spacing:
            main_group.append(history_text)
        else:
            break
    
    # Bottom section - settings and buttons
    settings_y = display_height - int(y_spacing * 2.5)
    
    # Hysteresis setting
    hysteresis_text = label.Label(
        terminalio.FONT, 
        text=f"Hysteresis: {hysteresis:.1f}cm", 
        scale=info_scale
    )
    hysteresis_text.x = x_margin
    hysteresis_text.y = settings_y
    main_group.append(hysteresis_text)
    
    # Countdown timer if provided
    if countdown is not None:
        countdown_text = label.Label(
            terminalio.FONT, 
            text=f"Sleep in: {countdown}s", 
            scale=info_scale
        )
        # Position on right side
        countdown_width = len(countdown_text.text) * 6 * info_scale
        countdown_text.x = display_width - countdown_width - x_margin
        countdown_text.y = settings_y
        main_group.append(countdown_text)
    
    # Button labels
    buttons_y = display_height - int(y_spacing * 1.0)
    
    # Calculate button label positions
    button_width = int((display_width - (2 * x_margin)) / 3)
    
    button_labels = [
        label.Label(terminalio.FONT, text="D0: Hyst-", scale=info_scale),
        label.Label(terminalio.FONT, text="D1: Hyst+", scale=info_scale),
        label.Label(terminalio.FONT, text="D2: Report", scale=info_scale)
    ]
    
    for i, btn_label in enumerate(button_labels):
        btn_label.x = x_margin + (i * button_width)
        btn_label.y = buttons_y
        main_group.append(btn_label)

# Function to connect to WiFi with robust error handling
def connect_wifi():
    try:
        print("Connecting to WiFi...")
        # Check if we have credentials
        if not WIFI_SSID or not WIFI_PASSWORD:
            print("ERROR: WiFi credentials missing in settings.toml")
            return False
            
        # Try to connect with timeout
        try:
            # Make sure wifi is enabled
            wifi.radio.enabled = True
            time.sleep(1)  # Brief delay to allow radio to initialize
            
            # Check if we're in CircuitPython safe mode, which disables networking
            # Not all versions of CircuitPython expose this property
            try:
                if hasattr(supervisor.runtime, 'safe_mode') and supervisor.runtime.safe_mode:
                    print("WARNING: Running in safe mode, WiFi disabled")
                    return False
            except Exception:
                # If we can't check safe mode, just continue
                pass
                
            # Try connecting with timeout
            try:
                wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD, timeout=10)
                print(f"Connected to {WIFI_SSID}!")
                print(f"IP Address: {wifi.radio.ipv4_address}")
                return True
            except ConnectionError as e:
                print(f"WiFi connection error: {e}")
                return False
            except TimeoutError:
                print("WiFi connection timeout")
                return False
        except (ValueError, RuntimeError, OSError) as e:
            print(f"WiFi connection error: {e}")
            return False
    except Exception as e:
        print(f"Unexpected WiFi error: {e}")
        return False

# Function to send data to Adafruit IO with robust error handling
def send_to_ADAFRUIT_AIO(distance):
    try:
        # Check if we have required credentials
        if not ADAFRUIT_USERNAME or not ADAFRUIT_KEY:
            print("ERROR: Adafruit IO credentials missing in settings.toml")
            return False
            
        # Create session and make request
        pool = socketpool.SocketPool(wifi.radio)
        requests = adafruit_requests.Session(pool, ssl.create_default_context())
        
        # Construct URL and headers
        url = f"{ADAFRUIT_AIO_URL}feeds/{FEED_NAME}/data"
        headers = {
            "X-AIO-Key": ADAFRUIT_KEY,
            "Content-Type": "application/json"
        }
        
        # Create data payload
        data = {"value": distance}
        
        # Send the data with timeout handling
        print(f"Posting distance: {distance}cm to Adafruit IO...")
        try:
            response = requests.post(url, headers=headers, json=data, timeout=15)
            print(f"Response: {response.status_code}")
            response.close()
            return response.status_code == 200
        except Exception as e:
            print(f"Failed to post to Adafruit IO: {e}")
            return False
    except Exception as e:
        print(f"Unexpected error sending data: {e}")
        return False

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

# Read distance with error handling
def read_distance():
    try:
        # Measure distance multiple times and average for reliability
        total_distance = 0
        valid_readings = 0
        samples = 5
        
        for _ in range(samples):
            try:
                # Get distance and convert from mm to cm
                reading = sensor.range / 10  
                
                # Check for valid readings (some sensors might return 0 or very large values on error)
                if 0 < reading < 8000:  # Reasonable range check for VL53L0X/VL53L1X (0-8m)
                    total_distance += reading
                    valid_readings += 1
                else:
                    print(f"Ignored invalid reading: {reading}cm")
            except Exception as e:
                print(f"Error reading sensor: {e}")
            
            time.sleep(0.1)
        
        # Check if we got any valid readings
        if valid_readings > 0:
            return total_distance / valid_readings
        else:
            print("WARNING: No valid distance readings obtained")
            return -1  # Return negative value to indicate error
    except Exception as e:
        print(f"Unexpected error in read_distance: {e}")
        return -1

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
        send_to_ADAFRUIT_AIO(current_distance)
        
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
        if not buttons[0]["dio"].value:
            hysteresis = max(MIN_HYSTERESIS, hysteresis - 0.5)  # Respect minimum from settings
            print(f"Hysteresis decreased to {hysteresis}cm")
            create_display_interface(main_group, current_distance, past_readings, hysteresis, remaining_time)
            time.sleep(0.3)  # Debounce
        
        # D1: Increase hysteresis
        if not buttons[1]["dio"].value:
            hysteresis = min(MAX_HYSTERESIS, hysteresis + 0.5)  # Respect maximum from settings
            print(f"Hysteresis increased to {hysteresis}cm")
            create_display_interface(main_group, current_distance, past_readings, hysteresis, remaining_time)
            time.sleep(0.3)  # Debounce
        
        # D2: Force report
        if not buttons[2]["dio"].value:
            print("Manual report requested")
            # Connect to WiFi if not already connected
            if not wifi.radio.connected:
                connect_wifi()
            
            # Report to Adafruit IO
            send_to_ADAFRUIT_AIO(current_distance)
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
        print(f"Button obj: {button}")
        pin_alarm = alarm.pin.PinAlarm(pin=button.pin, value=False, pull=True)
        pin_alarms.append(pin_alarm)
    
    # Clear the display and turn off backlight before sleep to save power
    # Use root_group assignment instead of show()
    display.root_group = displayio.Group()
    if backlight:
        backlight.value = False
    
    # Go to deep sleep, wake on any of the alarms
    alarm.exit_and_deep_sleep_until_alarms(time_alarm, *pin_alarms)

# Run the main program with robust error handling
try:
    main()
except Exception as e:
    print(f"Critical error occurred: {e}")
    # Display error on screen
    try:
        error_group = displayio.Group()
        error_text1 = label.Label(terminalio.FONT, text="ERROR:", scale=2, color=0xFF0000)
        error_text1.x = 10
        error_text1.y = 40
        error_group.append(error_text1)
        
        # Split error message into multiple lines if needed
        error_msg = str(e)
        max_chars_per_line = 30  # Approximate max chars per line
        
        if len(error_msg) > max_chars_per_line:
            # Split long messages into multiple lines
            line1 = error_msg[:max_chars_per_line]
            line2 = error_msg[max_chars_per_line:]
            
            error_text2 = label.Label(terminalio.FONT, text=line1, scale=1)
            error_text2.x = 10
            error_text2.y = 80
            error_group.append(error_text2)
            
            error_text3 = label.Label(terminalio.FONT, text=line2, scale=1)
            error_text3.x = 10
            error_text3.y = 100
            error_group.append(error_text3)
        else:
            # Short message fits on one line
            error_text2 = label.Label(terminalio.FONT, text=error_msg, scale=1)
            error_text2.x = 10
            error_text2.y = 80
            error_group.append(error_text2)
        
        # Add instructions
        restart_text = label.Label(terminalio.FONT, text="Restarting in 10 seconds...", scale=1)
        restart_text.x = 10
        restart_text.y = 140
        error_group.append(restart_text)
        
        # Show error on display
        board.DISPLAY.root_group = error_group
        time.sleep(10)  # Show error for 10 seconds
    except Exception as display_error:
        print(f"Error showing error screen: {display_error}")
        time.sleep(10)  # Delay anyway
    
    # Reset the microcontroller on error
    microcontroller.reset()