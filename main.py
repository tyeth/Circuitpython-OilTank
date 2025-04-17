# Low Power Distance Monitor with Adafruit IO
# For CircuitPython 9 on ESP32-S2 Reverse TFT Feather with VL53L0X/VL53L1X sensor

import time
import traceback
import board
import busio
import digitalio
import displayio
import terminalio
import adafruit_vl53l0x
import adafruit_max1704x
import supervisor
import wifi
import socketpool
import ssl
import adafruit_requests
import microcontroller
import alarm
import json
import os
import rtc  # Import RTC for fixed schedule timing
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

# Oil Tank Feed
FEED_NAME = os.getenv("ADAFRUIT_AIO_FEED_NAME", "oil-tank-depth")

# Error feed name for posting sensor errors
ERROR_FEED_NAME = os.getenv("ADAFRUIT_AIO_ERROR_FEED_NAME", "error")


# Time settings with defaults
# Set fixed report times instead of intervals
MORNING_HOUR = int(os.getenv("DISTANCE_MONITOR_MORNING_HOUR", "10"))  # 10 AM
EVENING_HOUR = int(os.getenv("DISTANCE_MONITOR_EVENING_HOUR", "18"))  # 6 PM

# Board detection and configuration
BOARD_TYPE = os.getenv("DISTANCE_MONITOR_BOARD_TYPE", "auto").lower()
HAS_DISPLAY = (os.getenv("DISTANCE_MONITOR_HAS_DISPLAY", "auto").lower() == "true" or 
              (os.getenv("DISTANCE_MONITOR_HAS_DISPLAY", "auto").lower() == "auto" and 
               BOARD_TYPE != "qtpy"))

# Detect board type if set to auto
if BOARD_TYPE == "auto":
    try:
        # Try to detect board type based on available pins
        if hasattr(board, "TFT_BACKLIGHT") and hasattr(board, "D0") and hasattr(board, "D1") and hasattr(board, "D2"):
            BOARD_TYPE = "feather_tft"
            print("Detected board: Feather S2 Reverse TFT")
        elif hasattr(board, "G0") or hasattr(board, "BOOT0") or hasattr(board, "BUTTON"):
            BOARD_TYPE = "qtpy"
            print("Detected board: QT Py S2")
        else:
            BOARD_TYPE = "unknown"
            print("Unknown board type, using default configuration")
    except Exception as e:
        print(f"Error detecting board type: {e}")
        BOARD_TYPE = "unknown"

# Set appropriate wake time based on board type
if BOARD_TYPE == "qtpy":
    AWAKE_TIME = int(os.getenv("DISTANCE_MONITOR_AWAKE_TIME", "120"))  # 2 minutes for QT Py
else:
    AWAKE_TIME = int(os.getenv("DISTANCE_MONITOR_AWAKE_TIME", "30"))  # 30 seconds default for other boards

# We still keep a minimum report interval as a fallback
MIN_REPORT_INTERVAL = int(os.getenv("DISTANCE_MONITOR_MIN_REPORT_INTERVAL", "86400"))  # 24 hours in seconds (default)
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

# First, let's define a UI elements class to hold references to the display elements we'll update
class UIElements:
    def __init__(self):
        self.current_distance_label = None
        self.hysteresis_label = None
        self.countdown_label = None
        self.past_reading_labels = []
        self.battery_label = None
        self.last_report_label = None  # New label to show last reported value

# Setup display and backlight
def setup_display():
    # Skip display setup if board doesn't support display
    if not HAS_DISPLAY:
        print("Display not supported on this board, skipping setup")
        return None, None, None
    
    # Check if board has display
    if not hasattr(board, 'DISPLAY'):
        print("No display available on this board")
        return None, None, None
        
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
    buttons = []
    
    # Configure buttons based on board type
    if BOARD_TYPE == "qtpy":
        # QT Py S2 has only one button (G0/BOOT) with opposite logic to Feather TFT
        boot_pin = None
        # Try different possible button pin names
        if hasattr(board, 'BUTTON'):
            boot_pin = board.BUTTON
        elif hasattr(board, 'BOOT') or hasattr(board, 'BOOT0'):
            boot_pin = getattr(board, 'BOOT', getattr(board, 'BOOT0', None))
        elif hasattr(board, 'G0'):
            boot_pin = board.G0
            
        if boot_pin:
            # QT Py button is typically active HIGH (opposite to Feather TFT D0)
            button_configs = [
                {"pin": boot_pin, "active_low": False}  # Boot/G0 is active HIGH (pressed = HIGH)
            ]
            print(f"Using QT Py button on {boot_pin}")
        else:
            print("No buttons found for QT Py")
            button_configs = []
            
    else:  # Default to Feather TFT or unknown board with D0, D1, D2 pins
        # Define which buttons are active LOW (default) and which are active HIGH
        button_configs = []
        
        # Add D0 if available
        if hasattr(board, 'D0'):
            button_configs.append({"pin": board.D0, "active_low": True})  # D0 is active LOW (pressed = LOW)
        
        # Add D1 if available
        if hasattr(board, 'D1'):
            button_configs.append({"pin": board.D1, "active_low": False})  # D1 is active HIGH (pressed = HIGH)
            
        # Add D2 if available
        if hasattr(board, 'D2'):
            button_configs.append({"pin": board.D2, "active_low": False})  # D2 is active HIGH (pressed = HIGH)
    
    # Set up each configured button
    for config in button_configs:
        pin = config["pin"]
        active_low = config["active_low"]
        
        try:
            btn = digitalio.DigitalInOut(pin)
            btn.direction = digitalio.Direction.INPUT
            
            # Set pull direction based on active state
            if active_low:
                btn.pull = digitalio.Pull.UP  # Pull up for active LOW buttons
            else:
                btn.pull = digitalio.Pull.DOWN  # Pull down for active HIGH buttons
                
            # Store DigitalInOut object, pin, and active state
            buttons.append({
                "dio": btn, 
                "pin": pin,
                "active_low": active_low
            })
        except Exception as e:
            print(f"Error setting up button {pin}: {e}")
            # Create a placeholder if button setup fails
            buttons.append({
                "dio": None,
                "pin": pin,
                "active_low": active_low
            })
    
    return buttons

# Function to create the initial display interface - only called once
def setup_display_interface(main_group, current_distance, past_readings, hysteresis, last_reported_distance):
    # Clear the display
    while len(main_group) > 0:
        main_group.pop()
    
    # Create a UI elements object to store references
    ui_elements = UIElements()
    
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
    y_spacing = int(display_height * 0.13)  # Spacing is 16% of height
    
    # Set up text area for title - this never changes
    title_text = label.Label(terminalio.FONT, text="Distance Monitor", scale=title_scale)
    title_text.x = x_margin
    title_text.y = y_start
    main_group.append(title_text)
    
    # Current reading - we'll update this later
    current_y = y_start + y_spacing
    current_text = label.Label(
        terminalio.FONT, 
        text=f"Current: {current_distance:.1f} cm", 
        scale=reading_scale
    )
    current_text.x = x_margin
    current_text.y = current_y
    main_group.append(current_text)
    ui_elements.current_distance_label = current_text
    
    # Last reported distance - NEW
    last_reported_y = current_y + int(y_spacing * 0.7)
    last_reported_text = label.Label(
        terminalio.FONT,
        text=f"Last reported: {last_reported_distance:.1f} cm",
        scale=info_scale
    )
    last_reported_text.x = x_margin
    last_reported_text.y = last_reported_y
    main_group.append(last_reported_text)
    ui_elements.last_report_label = last_reported_text
    
    # Past readings section header - this never changes
    history_y = last_reported_y + y_spacing
    hysteresis_y = history_y
    history_title = label.Label(terminalio.FONT, text="Past Readings:", scale=info_scale)
    history_title.x = x_margin
    history_title.y = history_y
    main_group.append(history_title)
    
    # Create labels for past readings
    max_width = display_width - (2 * x_margin)
    history_y += int(y_spacing * 0.8)
    
    # Create empty slots for the maximum number of past readings
    for i in range(MAX_STORED_READINGS):
        if i < len(past_readings):
            reading_text = f"{i+1}: {past_readings[i]:.1f} cm"
        else:
            reading_text = f"{i+1}: ---.-- cm"  # Placeholder
            
        # Create label for this reading
        history_text = label.Label(
            terminalio.FONT, 
            text=reading_text, 
            scale=info_scale
        )
        
        history_text.x = x_margin + 10
        history_text.y = history_y + (i * int(y_spacing * 0.6))
        
        # Only add if it fits on screen
        if history_text.y < display_height - y_spacing:
            main_group.append(history_text)
            ui_elements.past_reading_labels.append(history_text)
    
    # Bottom section - settings
    settings_y = display_height - int(y_spacing * 2.5)
    
    # Hysteresis setting - we'll update this later
    hysteresis_text = label.Label(
        terminalio.FONT, 
        text=f"Hysteresis: {hysteresis:.1f}cm", 
        scale=info_scale
    )
    hysteresis_width = len(hysteresis_text.text) * 6 * info_scale
    right_x_margin = display_width - hysteresis_width - x_margin
    hysteresis_text.x = right_x_margin
    hysteresis_text.y = hysteresis_y # settings_y
    main_group.append(hysteresis_text)
    ui_elements.hysteresis_label = hysteresis_text
    
    # Battery voltage
    battery_text = label.Label(
        terminalio.FONT, 
        text="Battery: --.-V", 
        scale=info_scale
    )
    battery_text.x = right_x_margin
    battery_text.y = int((hysteresis_y + settings_y) / 2)
    main_group.append(battery_text)
    ui_elements.battery_label = battery_text

    # Countdown timer - we'll update this later
    countdown_text = label.Label(
        terminalio.FONT, 
        text=f"Sleep in: --s", 
        scale=info_scale
    )
    # Position on right side
    countdown_text.x = right_x_margin
    countdown_text.y = settings_y
    main_group.append(countdown_text)
    ui_elements.countdown_label = countdown_text
    
    # Button labels - these never change
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
    
    return ui_elements

# Function to update only the current distance reading
def update_current_distance(ui_elements, current_distance):
    if ui_elements.current_distance_label:
        ui_elements.current_distance_label.text = f"Current: {current_distance:.1f} cm"

# Function to update only the last reported value
def update_last_reported(ui_elements, last_reported_distance):
    if ui_elements.last_report_label:
        ui_elements.last_report_label.text = f"Last reported: {last_reported_distance:.1f} cm"

# Function to update only the past readings
def update_past_readings(ui_elements, past_readings):
    for i, label_obj in enumerate(ui_elements.past_reading_labels):
        if i < len(past_readings):
            label_obj.text = f"{i+1}: {past_readings[i]:.1f} cm"
        else:
            label_obj.text = f"{i+1}: ---.-- cm"  # Empty slot

# Function to update only the hysteresis value
def update_hysteresis(ui_elements, hysteresis):
    if ui_elements.hysteresis_label:
        ui_elements.hysteresis_label.text = f"Hysteresis: {hysteresis:.1f}cm"

# Function to update only the countdown timer
def update_countdown(ui_elements, seconds_remaining):
    if ui_elements.countdown_label:
        ui_elements.countdown_label.text = f"Sleep in: {seconds_remaining}s"

# Function to update only the battery level
def update_battery_label(ui_elements, battery_level):
    if ui_elements.battery_label:
        ui_elements.battery_label.text = f"Battery: {battery_level:.2f}V"

# Function to sync the RTC with network time
def sync_rtc_time():
    try:
        if not wifi.radio.connected:
            connect_wifi()
            
        if wifi.radio.connected:
            pool = socketpool.SocketPool(wifi.radio)
            requests = adafruit_requests.Session(pool, ssl.create_default_context())
            
            # Get time from a public API
            response = requests.get("http://worldtimeapi.org/api/ip", timeout=10)
            time_json = response.json()
            response.close()
            
            # Parse the datetime string
            time_struct = time.localtime(time_json["unixtime"])
            
            # Set the RTC
            r = rtc.RTC()
            r.datetime = time_struct
            
            print(f"RTC synchronized: {r.datetime}")
            return True
    except Exception as e:
        print(f"Error syncing RTC: {e}")
    
    return False

# Function to calculate time until next scheduled report
def time_until_next_report():
    try:
        # Get current time from RTC
        r = rtc.RTC()
        now = r.datetime
        
        # Current hour and minute
        current_hour = now.tm_hour
        current_minute = now.tm_min
        
        # Calculate minutes until morning report (10 AM)
        if current_hour < MORNING_HOUR:
            # Today's morning report
            hours_until_morning = MORNING_HOUR - current_hour
            minutes_until_morning = hours_until_morning * 60 - current_minute
        else:
            # Tomorrow's morning report
            hours_until_morning = 24 - current_hour + MORNING_HOUR
            minutes_until_morning = hours_until_morning * 60 - current_minute
        
        # Calculate minutes until evening report (6 PM)
        if current_hour < EVENING_HOUR:
            # Today's evening report
            hours_until_evening = EVENING_HOUR - current_hour
            minutes_until_evening = hours_until_evening * 60 - current_minute
        else:
            # Tomorrow's evening report
            hours_until_evening = 24 - current_hour + EVENING_HOUR
            minutes_until_evening = hours_until_evening * 60 - current_minute
        
        # Take the minimum time
        minutes_until_next = min(minutes_until_morning, minutes_until_evening)
        
        # Convert to seconds
        seconds_until_next = minutes_until_next * 60
        
        print(f"Minutes until next scheduled report: {minutes_until_next} (next at {MORNING_HOUR if minutes_until_morning < minutes_until_evening else EVENING_HOUR}:00)")
        
        return seconds_until_next
    except Exception as e:
        print(f"Error calculating next report time: {e}")
        # Fallback to a 12-hour interval
        return 12 * 60 * 60

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

# Function to send data to Adafruit IO with specified feed
def send_to_adafruit_io(value, feed_name=None):
    if feed_name is None:
        feed_name = FEED_NAME
        
    try:
        # Check if we have required credentials
        if not ADAFRUIT_USERNAME or not ADAFRUIT_KEY:
            print("ERROR: Adafruit IO credentials missing in settings.toml")
            return False
            
        # Create session and make request
        pool = socketpool.SocketPool(wifi.radio)
        requests = adafruit_requests.Session(pool, ssl.create_default_context())
        
        # Construct URL and headers
        url = f"{ADAFRUIT_AIO_URL}{ADAFRUIT_USERNAME}/feeds/{feed_name}/data"
        headers = {
            "X-AIO-Key": ADAFRUIT_KEY,
            "Content-Type": "application/json"
        }
        
        # Create data payload
        data = {"value": value}
        
        # Send the data with timeout handling
        print(f"Posting to feed '{feed_name}': {value}")
        print(f"URL: {url}")
        try:
            response = requests.post(url, headers=headers, json=data, timeout=15)
            print(f"Response: {response.status_code}")
            response_text = response.text
            response.close()
            
            if response.status_code == 404:
                print(f"Feed not found! Attempting to create feed ({feed_name}) and retry...")
                # Attempt to create the feed
                create_feed_url = f"{ADAFRUIT_AIO_URL}{ADAFRUIT_USERNAME}/feeds"
                create_feed_data = {
                    "name": feed_name,
                    "key": feed_name,
                    "description": f"Auto-created {feed_name} feed",
                    "visibility": "public"
                }
                create_response = requests.post(create_feed_url, headers=headers, json=create_feed_data, timeout=15)
                print(f"Response to create feed: {create_response.status_code}")
                create_response.close()
                
                if create_response.status_code == 201:
                    print("Feed created successfully! Retrying data post...")
                    response = requests.post(url, headers=headers, json=data, timeout=15)
                    print(f"Retry response: {response.status_code}")
                    response.close()
                    return response.status_code == 200
                else:
                    print(f"Failed to create feed")
                    return False
            
            return response.status_code == 200
        except Exception as e:
            print(f"Failed to post to Adafruit IO: {e}")
            return False
    except Exception as e:
        print(f"Unexpected error sending data: {e}")
        return False


# Initialize the I2C bus
i2c = busio.I2C(board.SCL, board.SDA)


sensor = None
sensor_type = None
sensor_out_of_range = 400  # Default out of range value for VL53L0X

try:
    # Try VL53L0X first
    import adafruit_vl53l0x
    sensor = adafruit_vl53l0x.VL53L0X(i2c)
    sensor.measurement_timing_budget = 200000  # 200ms
    sensor_type = "VL53L0X"
    print("VL53L0X sensor initialized")
except Exception as e:
    print(f"VL53L0X init failed: {e}")
    try:
        # Try VL53L1X if VL53L0X fails
        import adafruit_vl53l1x
        sensor = adafruit_vl53l1x.VL53L1X(i2c)
        # VL53L1X uses different configuration methods
        sensor.distance_mode = 2  # Long range mode
        sensor.timing_budget = 200  # 200ms
        sensor_type = "VL53L1X"
        sensor_out_of_range = 800  # Higher range for VL53L1X
        print("VL53L1X sensor initialized")
    except Exception as e:
        print(f"VL53L1X init failed: {e}")
        print("No supported distance sensor found!")
        raise

battery_sensor = None
battery_level = 0.0
try:
    try:
        # Try to initialize the battery sensor (MAX1704x)
        battery_sensor = adafruit_max1704x.MAX17048(i2c)
        print("Battery sensor initialized")
        battery_sensor.reset_voltage = 2.7  # Set reset voltage to 2.7V (default 3.0V)

        # The analog comparator is used to detect the rest voltage, if you don't think the battery
        # will ever be removed this can reduce current usage (see datasheet on VRESET.Dis)
        print("MAX17048 Analog comparator is ", end="")
        if battery_sensor.comparator_disabled:
            print("disabled")
        else:
            print("enabled, attempting to disable")
            battery_sensor.comparator_disabled = True
            print("Analog comparator disabled: ", battery_sensor.comparator_disabled)
        time.sleep(0.1)
        battery_level = battery_sensor.cell_voltage
        print(f"Battery voltage: {battery_level:.2f}V")
        battery_sensor.hibernate()
    except Exception as e:
        print(f"Battery sensor init failed: {e}")
        raise
except Exception as e:
    print(f"Battery sensor initialization failed: {e}")
    try:
        import traceback
        traceback.print_exception(e)
    except:
        print("(Traceback unavailable)")
    battery_sensor = None


# Global variables to track time and last readings
last_report_time = 0
last_distance = 0
last_reported_distance = 0  # NEW - track the last value we actually sent to AIO
past_readings = []
hysteresis = DEFAULT_HYSTERESIS  # Default hysteresis value from settings.toml

# Initialize display
display, main_group, backlight = setup_display()

# Initialize buttons
buttons = setup_buttons()
# Read distance with improved error handling and modal sampling
def read_distance():
    try:
        # Measure distance multiple times and use modal value for reliability
        readings = []
        valid_readings = []
        samples = 10  # Take more samples for better modal analysis
        
        for _ in range(samples):
            try:
                # Read sensor based on type with appropriate error checks
                if sensor_type == "VL53L0X":
                    # VL53L0X reports in mm, convert to cm
                    raw_range = sensor.range
                    
                    # Check if out of range or error
                    if raw_range >= sensor_out_of_range * 10:  # Check in mm
                        print(f"VL53L0X out of range: {raw_range/10:.1f}cm")
                        continue
                    
                    # Convert to cm
                    reading = raw_range / 10
                    
                elif sensor_type == "VL53L1X":
                    # Start measurement if needed (VL53L1X needs explicit start)
                    if not sensor.data_ready:
                        sensor.start_ranging()
                        # Wait for data to be ready
                        for _ in range(10):  # Try up to 10 times
                            time.sleep(0.01)
                            if sensor.data_ready:
                                break
                    
                    # Check if data is ready
                    if not sensor.data_ready:
                        print("VL53L1X data not ready")
                        continue
                    
                    # Get distance (already in cm)
                    raw_range = sensor.distance
                    
                    # # Check range status
                    # if sensor.status != 0:
                    #     print(f"VL53L1X status error: {sensor.status}")
                    #     continue
                        
                    # Check if out of range
                    if raw_range >= sensor_out_of_range * 10:  # Check in mm
                        print(f"VL53L1X out of range: {raw_range/10:.1f}cm")
                        continue
                        
                    # Convert to cm
                    reading = raw_range
                    
                    # Clear ranging to prepare for next sample
                    sensor.clear_interrupt()
                    
                else:
                    print("Unknown sensor type")
                    return -1
                
                # Add to all readings
                readings.append(reading)
                
                # Check for valid readings (reasonable range for oil tanks)
                if reading is not None and 5 < int(reading) < sensor_out_of_range:  # Between 5cm and out_of_range
                    valid_readings.append(reading)
                else:
                    print(f"Ignored questionable reading: {reading:.1f}cm")
                    
            except Exception as e:
                print(f"Error reading sensor: {e}")
                traceback.print_exception(e)

            
            time.sleep(0.1)
        
        # If we have valid readings, find the middle element
        avg_reading = -1  # Default to -1 if no valid readings
        if valid_readings:
            # Round readings to 1 decimal place for finding mode
            rounded_readings = [round(r, 1) for r in valid_readings]
            
            #return middle value
            sorted_readings = sorted(rounded_readings)
            mid_index = len(sorted_readings) // 2
            avg_reading = sorted_readings[mid_index]

            print(f"Valid reading: {avg_reading:.1f}cm")

            return avg_reading
        
        # If no valid readings but we have some readings, average them as fallback
        elif readings:
            avg_reading = sum(readings) / len(readings)
            print(f"WARNING: Using average of questionable readings: {avg_reading:.1f}cm")
            
            # Report error to error feed
            if wifi.radio.connected:
                error_msg = f"Using avg of {len(readings)} questionable readings: {avg_reading:.1f}cm"
                if not send_to_adafruit_io(error_msg, ERROR_FEED_NAME):
                    print(f"Failed to report error: {error_msg}")
                
            return avg_reading
        
        else:
            print("ERROR: No distance readings obtained")
            
            # Report error to error feed
            if wifi.radio.connected:
                send_to_adafruit_io("No distance readings obtained", ERROR_FEED_NAME)
                
            return -1
            
    except Exception as e:
        print(f"Unexpected error in read_distance: {e}")
        
        # Report error to error feed
        if wifi.radio.connected:
            send_to_adafruit_io(f"Sensor error: {str(e)}", ERROR_FEED_NAME)
            
        return -1

# Check if waking from deep sleep
wake_reason = None
if isinstance(alarm.wake_alarm, alarm.pin.PinAlarm):
    print("Woke from button press!")
    wake_reason = "button"
    # Turn on backlight if we have control over it and display is supported
    if backlight and HAS_DISPLAY:
        backlight.value = True
elif alarm.wake_alarm:
    print("Woke from time alarm!")
    wake_reason = "timer"
    # Don't turn on backlight for automatic wakeups to save power
elif supervisor.runtime.run_reason is supervisor.RunReason.STARTUP:
    print("First boot, initializing...")
    last_report_time = 0
    last_distance = 0
    last_reported_distance = 0  # Initialize last reported value
    past_readings = []
    # Turn on backlight for first boot if display is supported
    if backlight and HAS_DISPLAY:
        backlight.value = True
time.sleep(2) # debug
    
# Try to load previous state from a file
try:
    with open("state.json", "r") as f:
        state = json.load(f)
        last_report_time = state["last_report_time"]
        last_distance = state["last_distance"]
        last_reported_distance = state.get("last_reported_distance", last_distance)  # NEW - get last reported value, fallback to last distance
        past_readings = state.get("past_readings", [])
        hysteresis = state.get("hysteresis", DEFAULT_HYSTERESIS)
        print(f"Loaded state: last report at {last_report_time}, distance: {last_distance}cm")
        print(f"Last reported distance: {last_reported_distance}cm")
        print(f"Hysteresis: {hysteresis}cm")
except (OSError, ValueError):
    print("No valid state file found, starting fresh")
    last_report_time = 0
    last_distance = 0
    last_reported_distance = 0
    past_readings = []

def main():
    global last_report_time, last_distance, last_reported_distance, past_readings, hysteresis, battery_level
    
    current_time = time.monotonic()
    
    # Read current distance with error handling
    current_distance = read_distance()
    if current_distance < 0:
        print("ERROR: Could not get valid distance reading")
        # Try to use last known good reading if available
        if last_distance > 0:
            print(f"Using last known distance: {last_distance:.1f}cm")
            current_distance = last_distance
        else:
            print("No valid previous reading available - using default")
            current_distance = 100.0  # Default value for error case
    
    print(f"Current distance: {current_distance:.1f}cm")
    
    # Update past readings - only store valid readings
    if last_distance > 0:  # Only add non-error readings to history
        past_readings.insert(0, last_distance)
        # Keep only the last MAX_STORED_READINGS
        past_readings = past_readings[:MAX_STORED_READINGS]
    
    # Determine if we need to report based on criteria
    time_since_last_report = current_time - last_report_time
    
    # Calculate change compared to LAST REPORTED value (not just last reading)
    # This is the key change to fix the hysteresis issue
    distance_change = abs(current_distance - last_reported_distance) if last_reported_distance > 0 else 0
    
    # Check if it's time for a scheduled report
    is_scheduled_report_time = False
    try:
        # Get current time from RTC
        r = rtc.RTC()
        now = r.datetime
        
        # Check if current time matches one of our scheduled times (10 AM or 6 PM)
        if now.tm_hour == MORNING_HOUR and now.tm_min < 10:  # Within first 10 minutes of 10 AM
            is_scheduled_report_time = True
            print("Scheduled morning report time")
        elif now.tm_hour == EVENING_HOUR and now.tm_min < 10:  # Within first 10 minutes of 6 PM
            is_scheduled_report_time = True
            print("Scheduled evening report time")
    except Exception as e:
        print(f"Error checking scheduled report time: {e}")
        # Fallback to time-since-last-report if RTC fails
        is_scheduled_report_time = (time_since_last_report >= MIN_REPORT_INTERVAL)
    
    should_report = (
        is_scheduled_report_time or  # Report at scheduled times (10 AM and 6 PM)
        (time_since_last_report >= MIN_REPORT_INTERVAL) or  # Fallback: Report at least daily
        (distance_change >= hysteresis and distance_change > 0) or  # Report on significant change
        (wake_reason == "button")  # Report if woken by button
    )
    
    # If we're waking from a time alarm and the hysteresis check doesn't pass,
    # go back to sleep immediately without turning on display
    if wake_reason == "timer" and not (is_scheduled_report_time or time_since_last_report >= MIN_REPORT_INTERVAL) and not (distance_change >= hysteresis):
        print(f"Hysteresis threshold not met (change: {distance_change:.2f}cm, threshold: {hysteresis:.1f}cm)")
        print("Going back to sleep without reporting")
        
        # Save current reading before going back to sleep
        if current_distance > 0:
            last_distance = current_distance
            
        # Save state to file
        try:
            with open("state.json", "w") as f:
                json.dump({
                    "last_report_time": last_report_time,
                    "last_distance": last_distance,
                    "last_reported_distance": last_reported_distance,
                    "past_readings": past_readings,
                    "hysteresis": hysteresis
                }, f)
            print("State saved")
        except Exception as e:
            print(f"Error saving state: {e}")
            
        # Calculate time until next scheduled report
        next_wake_seconds = time_until_next_report()
        print(f"Going to sleep for {next_wake_seconds} seconds")
        
        # Set up a time alarm and go back to sleep
        time_alarm = alarm.time.TimeAlarm(monotonic_time=time.monotonic() + next_wake_seconds)
        alarm.exit_and_deep_sleep_until_alarms(time_alarm)
        # Code will not continue past this point when deep sleep is entered
    
    # Set up the display ONCE (not repeatedly) - only if display is supported
    ui_elements = None
    if HAS_DISPLAY and main_group is not None:
        ui_elements = setup_display_interface(main_group, current_distance, past_readings, hysteresis, last_reported_distance)
    
    # Report data if needed
    report_success = False
    if should_report:
        # Connect to WiFi with error handling
        wifi_connected = connect_wifi()
        
        if wifi_connected:
            # Try to sync RTC if needed
            if not is_scheduled_report_time:  # Don't sync if we're already at a scheduled time
                try:
                    sync_rtc_time()
                except Exception as e:
                    print(f"Error during RTC sync: {e}")
            
            # Report to Adafruit IO
            report_success = send_to_adafruit_io(current_distance)
            
            if report_success:
                # Update last reported values only on successful report
                last_report_time = current_time
                last_reported_distance = current_distance  # Update the last reported value
                # Also update the display to show new last reported value if display is enabled
                if HAS_DISPLAY and ui_elements and ui_elements.last_report_label:
                    update_last_reported(ui_elements, last_reported_distance)
                print(f"Successfully reported {current_distance:.1f}cm to Adafruit IO")
            
            # Read and report battery level
            if battery_sensor:
                try:
                    if battery_sensor.hibernating:
                        print("Waking up battery sensor")
                        battery_sensor.wake()
                    time.sleep(0.1)
                    battery_level = battery_sensor.cell_voltage
                    print(f"Battery voltage: {battery_level:.2f}V")
                    # Update display only if supported and enabled
                    if HAS_DISPLAY and ui_elements and ui_elements.battery_label:
                        update_battery_label(ui_elements, battery_level)
                    # Report battery level to Adafruit IO
                    battery_feed = FEED_NAME + "-bat"
                    bat_success = send_to_adafruit_io(battery_level, battery_feed)
                    print(f"Reported battery: {bat_success}")
                    battery_sensor.hibernate()  # Hibernate after reading
                except Exception as e:
                    print(f"Error reading+posting battery voltage: {e}")
            
            # Disconnect WiFi to save power
            wifi.radio.enabled = False
        else:
            print("ERROR: Could not connect to WiFi - skipping data upload")
    
    # Update the last distance - only store valid readings
    if current_distance > 0:
        last_distance = current_distance
    
    # Handle button interaction and display for AWAKE_TIME seconds
    start_time = time.monotonic()
    stay_awake = True
    
    # Main interaction loop - now with targeted updates instead of full rebuilds
    try:
        while stay_awake and (time.monotonic() - start_time < AWAKE_TIME):
            # Calculate remaining time
            remaining_time = int(AWAKE_TIME - (time.monotonic() - start_time))
            
            # ONLY update the countdown text, not the entire display (if display is enabled)
            if HAS_DISPLAY and ui_elements and ui_elements.countdown_label:
                update_countdown(ui_elements, remaining_time)
            
            # Check buttons with error handling
            try:
                # Handle buttons based on board type
                if BOARD_TYPE == "qtpy":
                    # QT Py has only one button, use it for force report
                    if buttons and buttons[0]["dio"] is not None:
                        is_pressed = buttons[0]["active_low"] == (not buttons[0]["dio"].value)
                        if is_pressed:
                            print("Manual report requested via QT Py button")
                            # Connect to WiFi if not already connected
                            if not wifi.radio.connected:
                                wifi_connected = connect_wifi()
                            else:
                                wifi_connected = True
                            
                            # Report to Adafruit IO if WiFi connected
                            if wifi_connected:
                                report_success = send_to_adafruit_io(current_distance)
                                if report_success:
                                    last_report_time = time.monotonic()
                                    last_reported_distance = current_distance  # Update last reported value
                                    # Update display if supported
                                    if HAS_DISPLAY and ui_elements and ui_elements.last_report_label:
                                        update_last_reported(ui_elements, last_reported_distance)
                                    print("Manual report successful")
                                else:
                                    print("Manual report failed")
                            else:
                                print("Could not connect to WiFi for manual report")
                        
                            # Reset the countdown timer regardless of success
                            start_time = time.monotonic()
                            time.sleep(0.3)  # Debounce
                
                else:  # Feather TFT or other multi-button board
                    # D0: Decrease hysteresis (active LOW) - if available
                    if buttons and len(buttons) > 0 and buttons[0]["dio"] is not None:
                        is_pressed = buttons[0]["active_low"] == (not buttons[0]["dio"].value)
                        if is_pressed:
                            hysteresis = max(MIN_HYSTERESIS, hysteresis - 0.5)  # Respect minimum from settings
                            print(f"Hysteresis decreased to {hysteresis}cm")
                            # ONLY update the hysteresis display element if display is enabled
                            if HAS_DISPLAY and ui_elements and ui_elements.hysteresis_label:
                                update_hysteresis(ui_elements, hysteresis)
                            time.sleep(0.3)  # Debounce
                    
                    # D1: Increase hysteresis (active HIGH) - if available
                    if buttons and len(buttons) > 1 and buttons[1]["dio"] is not None:
                        is_pressed = buttons[1]["active_low"] == (not buttons[1]["dio"].value)
                        if is_pressed:
                            hysteresis = min(MAX_HYSTERESIS, hysteresis + 0.5)  # Respect maximum from settings
                            print(f"Hysteresis increased to {hysteresis}cm")
                            # ONLY update the hysteresis display element if display is enabled
                            if HAS_DISPLAY and ui_elements and ui_elements.hysteresis_label:
                                update_hysteresis(ui_elements, hysteresis)
                            time.sleep(0.3)  # Debounce
                    
                    # D2: Force report (active HIGH) - if available
                    if buttons and len(buttons) > 2 and buttons[2]["dio"] is not None:
                        is_pressed = buttons[2]["active_low"] == (not buttons[2]["dio"].value)
                        if is_pressed:
                            print("Manual report requested")
                            # Connect to WiFi if not already connected
                            if not wifi.radio.connected:
                                wifi_connected = connect_wifi()
                            else:
                                wifi_connected = True
                            
                            # Report to Adafruit IO if WiFi connected
                            if wifi_connected:
                                report_success = send_to_adafruit_io(current_distance)
                                if report_success:
                                    last_report_time = time.monotonic()
                                    last_reported_distance = current_distance  # Update last reported value
                                    # Update display if supported
                                    if HAS_DISPLAY and ui_elements and ui_elements.last_report_label:
                                        update_last_reported(ui_elements, last_reported_distance)
                                    print("Manual report successful")
                                else:
                                    print("Manual report failed")
                            else:
                                print("Could not connect to WiFi for manual report")
                        
                            # Reset the countdown timer regardless of success
                            start_time = time.monotonic()
                            time.sleep(0.3)  # Debounce
            except Exception as e:
                print(f"Error during button handling: {e}")
            
            time.sleep(0.1)
    except Exception as e:
        print(f"Error in main interaction loop: {e}")
    
    # Save state to a file with error handling
    try:
        try:
            # First try to write to the file system
            with open("state.json", "w") as f:
                json.dump({
                    "last_report_time": last_report_time,
                    "last_distance": last_distance,
                    "last_reported_distance": last_reported_distance,  # Save last reported value
                    "past_readings": past_readings,
                    "hysteresis": hysteresis
                }, f)
            print("State saved")
        except OSError as e:
            if "Read-only" in str(e):
                print("Warning: Read-only filesystem, state won't be saved")
            else:
                print(f"Error saving state: {e}")
    except Exception as e:
        print(f"Unexpected error saving state: {e}")
    
    # Calculate time until next scheduled report
    next_wake_seconds = time_until_next_report()
    
    print(f"Going to sleep for {next_wake_seconds} seconds")
    
    # Set up alarms with error handling
    try:
        # Set up time alarm
        time_alarm = alarm.time.TimeAlarm(monotonic_time=time.monotonic() + next_wake_seconds)
        
        # Set up pin alarms for D0, D1, and D2
        pin_alarms = []  # Start with time alarm
        for button in buttons[1:]:
            try:
                # Access the pin directly from the dictionary
                button_pin = button["pin"]
                
                # For alarm setup, we need to make sure we're not using the pins already in use
                # First, close the DigitalInOut to release the pin if it was successfully set up
                if button["dio"] is not None:
                    button["dio"].deinit()
                
                # Then set up the pin alarm with the appropriate trigger value
                # For active LOW buttons, we want to trigger on LOW (False)
                # For active HIGH buttons, we want to trigger on HIGH (True)
                alarm_value = not button["active_low"]  # Opposite of active state

                # With a brief delay to ensure pin is released
                time.sleep(0.1)
                
                try:
                    print(f"Setting up alarm for {button}")
                    pin_alarm = alarm.pin.PinAlarm(pin=button['pin'], value=not button['active_low'], pull=True)
                    pin_alarms.append(pin_alarm)
                    print(f"Alarm set for pin {button_pin}")
                except Exception as e:
                    print(f"Error setting up button alarm: {e}")
            except Exception as e:
                print(f"Error preparing button for alarm: {e}")
        
        # Clear the display before sleep to save power (if display is supported)
        if HAS_DISPLAY and display:
            display.root_group = displayio.Group()
            if backlight:
                backlight.value = False
        
        # Go to deep sleep, wake on any of the alarms
        if pin_alarms:
            alarm.exit_and_deep_sleep_until_alarms(time_alarm, *pin_alarms)
        else:
            print("No pin alarms set, using time alarm only")
            alarm.exit_and_deep_sleep_until_alarms(time_alarm)
    except Exception as e:
        print(f"Error entering deep sleep: {e}")
        # If we can't enter deep sleep, just wait a bit and reset
        time.sleep(10)
        microcontroller.reset()

# Run the main program with robust error handling
try:
    main()
except Exception as e:
    print(f"Critical error occurred: {e}")
    print("*** Traceback:")
    traceback.print_exception(e)
    time.sleep(3)
    # Display error on screen if display is supported
    if HAS_DISPLAY and hasattr(board, 'DISPLAY'):
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
    else:
        # No display available, just wait before reset
        print("No display available, restarting in 10 seconds...")
        time.sleep(10)  # Delay before reset
    
    # Reset the microcontroller on error
    microcontroller.reset()