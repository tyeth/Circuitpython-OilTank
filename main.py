# Low Power Distance Monitor with Adafruit IO
# For CircuitPython 9 on ESP32-S2 Reverse TFT Feather with VL53L0X/VL53L1X sensor
# Also supports desktop platforms (Linux, macOS, Windows) via Pygame Blinka

import time
import json
import os
import sys
import platform

# Determine if we're running on CircuitPython or a desktop environment
is_circuitpython = False
try:
    import microcontroller
    is_circuitpython = True
except ImportError:
    is_circuitpython = False

is_fake_circuitpython = False if is_circuitpython else True
supervisor = None
try:
    import supervisor as sv
    supervisor = sv
except ImportError:
    is_fake_circuitpython = True
    # Stub out missing CircuitPython modules
    class SupervisorStub:
        class RuntimeStub:
            def __init__(self):
                self.safe_mode = False
                self.run_reason = None
        
        def __init__(self):
            self.runtime = self.RuntimeStub()
    
    class RunReason:
        STARTUP = "STARTUP"
    
    # Create stub modules for CircuitPython-specific imports
    supervisor = SupervisorStub()
    supervisor.RunReason = RunReason

is_circuitpython = not is_fake_circuitpython

# Get platform information for desktop environments
system_platform = None
if not is_circuitpython or is_fake_circuitpython:
    try:
        # Try os.name first (works on Windows)
        if hasattr(os, 'name'):
            if os.name == 'nt':
                system_platform = 'Windows'
            elif os.name == 'posix':
                # Further determine if it's Linux or macOS
                try:
                    # Try platform.system() which should work on most systems
                    system = platform.system()
                    if system == 'Linux':
                        system_platform = 'Linux'
                    elif system == 'Darwin':
                        system_platform = 'Mac'
                    else:
                        system_platform = system
                except:
                    # Try os.uname if platform.system fails
                    try:
                        if hasattr(os, 'uname'):
                            uname = os.uname()
                            if uname.sysname == 'Linux':
                                system_platform = 'Linux'
                            elif uname.sysname == 'Darwin':
                                system_platform = 'Mac'
                            else:
                                system_platform = uname.sysname
                    except:
                        system_platform = 'Unknown'
    except:
        system_platform = 'Unknown'

    print(f"Detected desktop platform: {system_platform}")

# Import appropriate modules based on platform
# Common imports that work on both platforms
import displayio
import terminalio
from adafruit_display_text import label, scrolling_label

if is_circuitpython and not is_fake_circuitpython:
    # Only import CircuitPython-specific modules if actually on CircuitPython
    import board
    import busio
    import digitalio
    import wifi
    import socketpool
    import ssl
    import adafruit_requests
    import alarm
    try:
        import adafruit_vl53l0x
    except ImportError:
        print("VL53L0X library not found, will try VL53L1X")
else:
    # Desktop environment imports
    import pygame
    from blinka_displayio_pygamedisplay import PyGameDisplay
    try:
        # These are available via blinka but aren't native CircuitPython
        import board
        print("Using Blinka board module")
    except ImportError:
        print("Blinka board module not available")
        
    # Create wifi stub if needed for desktop
    try:
        import wifi
    except ImportError:
        class WiFiRadioStub:
            def __init__(self):
                self.enabled = True
                self.connected = False
                self.ipv4_address = "0.0.0.0"
            
            def connect(self, ssid, password, timeout=10):
                print(f"WiFi stub: Simulating connection to {ssid}")
                self.connected = True
                return True
        
        class WiFiStub:
            def __init__(self):
                self.radio = WiFiRadioStub()
        
        wifi = WiFiStub()
        
    # Create busio stub for desktop
    try:
        import busio
    except ImportError:
        class I2CStub:
            def __init__(self, scl, sda):
                self.scl = scl
                self.sda = sda
                print(f"I2C stub initialized with SCL={scl}, SDA={sda}")
                
            def try_lock(self):
                return True
                
            def unlock(self):
                pass
                
            def scan(self):
                return []
                
            def readfrom_into(self, address, buffer, *, start=0, end=None):
                pass
                
            def writeto(self, address, buffer, *, start=0, end=None, stop=True):
                pass
        
        class BusioStub:
            def __init__(self):
                self.I2C = I2CStub
        
        busio = BusioStub()
    
    # Create alarm stub for desktop
    try:
        import alarm
    except ImportError:
        class PinAlarmStub:
            def __init__(self, pin, value, pull=False):
                self.pin = pin
                self.value = value
                self.pull = pull
        
        class TimeAlarmStub:
            def __init__(self, monotonic_time):
                self.monotonic_time = monotonic_time
        
        class AlarmStub:
            def __init__(self):
                self.wake_alarm = None
                self.pin = type('PinModule', (), {'PinAlarm': PinAlarmStub})
                self.time = type('TimeModule', (), {'TimeAlarm': TimeAlarmStub})
                
            def exit_and_deep_sleep_until_alarms(self, *alarms):
                print("Alarm stub: exit_and_deep_sleep_until_alarms called")
        
        alarm = AlarmStub()
        
    # Create ssl stub for desktop if needed
    try:
        import ssl
    except ImportError:
        class SSLContext:
            def load_verify_locations(self, cadata=None):
                pass
                
            def wrap_socket(self, sock, server_hostname=None):
                return sock
        
        class SSLStub:
            def create_default_context(self):
                return SSLContext()
        
        ssl = SSLStub()
        
    # Create socketpool stub
    try:
        import socketpool
    except ImportError:
        class SocketPoolStub:
            def __init__(self, radio):
                self.radio = radio
                
            def getaddrinfo(self, host, port):
                return [(2, 1, 6, '', (host, port))]
                
            def socket(self, family=None, type=None):
                return None
        
        class SocketPoolModuleStub:
            def SocketPool(self, radio):
                return SocketPoolStub(radio)
        
        socketpool = SocketPoolModuleStub()
    
    # Create adafruit_requests stub
    try:
        import adafruit_requests
    except ImportError:
        class RequestsSessionStub:
            def __init__(self, pool, context):
                self.pool = pool
                self.context = context
                
            def request(self, method, url, **kwargs):
                print(f"RequestsStub: {method} request to {url}")
                return ResponseStub(200)
                
            def get(self, url, **kwargs):
                return self.request("GET", url, **kwargs)
                
            def post(self, url, **kwargs):
                return self.request("POST", url, **kwargs)
        
        class ResponseStub:
            def __init__(self, status_code):
                self.status_code = status_code
                self.text = '{"value": "stub response"}'
                
            def close(self):
                pass
                
            def json(self):
                return {"value": "stub response"}
        
        class RequestsStub:
            def Session(self, pool, context):
                return RequestsSessionStub(pool, context)
        
        adafruit_requests = RequestsStub()
    
    # Create digitalio stub
    try:
        import digitalio
    except ImportError:
        class DigitalInOutStub:
            def __init__(self, pin):
                self.pin = pin
                self._value = False
                self._direction = None
                self._pull = None
                
            @property
            def value(self):
                return self._value
                
            @value.setter
            def value(self, val):
                self._value = val
                
            @property
            def direction(self):
                return self._direction
                
            @direction.setter
            def direction(self, val):
                self._direction = val
                
            @property
            def pull(self):
                return self._pull
                
            @pull.setter
            def pull(self, val):
                self._pull = val
                
            def deinit(self):
                pass
        
        class DirectionEnum:
            INPUT = "INPUT"
            OUTPUT = "OUTPUT"
            
        class PullEnum:
            UP = "UP"
            DOWN = "DOWN"
        
        class DigitalioStub:
            def __init__(self):
                self.DigitalInOut = DigitalInOutStub
                self.Direction = DirectionEnum()
                self.Pull = PullEnum()
        
        digitalio = DigitalioStub()

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

# First, let's define a UI elements class to hold references to the display elements we'll update
class UIElements:
    def __init__(self):
        self.current_distance_label = None
        self.hysteresis_label = None
        self.countdown_label = None
        self.past_reading_labels = []

# Setup display and backlight
def setup_display():
    # Create a group to hold display items
    main_group = displayio.Group()
    
    if is_circuitpython and not is_fake_circuitpython:
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
        
        # Use root_group assignment instead of show() in CircuitPython 9
        display.root_group = main_group
    else:
        # Desktop environment (PyGame)
        try:
            # Initialize pygame
            pygame.init()
            print("before super init")
            # Create a display - don't use title as it might not be supported
            display = PyGameDisplay(width=320, height=240)
            print("after super init")
            
            # Different versions of PyGameDisplay may use different methods
            try:
                # Try to use show method with splash parameter
                display.show(splash=main_group)
            except TypeError:
                # Fallback to different approaches
                try:
                    # Try direct root_group assignment
                    display.root_group = main_group
                except AttributeError:
                    # Try the show method without parameters
                    try:
                        display.show()
                        # If show() without parameters worked, try to add the group differently
                        if hasattr(display, 'group'):
                            display.group = main_group
                    except:
                        print("Could not attach display group")
                        
            print("PyGame display initialized")
        except Exception as e:
            print(f"Error initializing PyGame display: {e}")
            # Fallback to simple stdout display
            display = None
            
        backlight = None  # No backlight control needed for desktop
    
    return display, main_group, backlight

# Setup buttons
def setup_buttons():
    buttons = []
    
    if is_circuitpython:
        # Define which buttons are active LOW (default) and which are active HIGH
        button_configs = [
            {"pin": board.D0, "active_low": True},  # D0 is active LOW (pressed = LOW)
            {"pin": board.D1, "active_low": False}, # D1 is active HIGH (pressed = HIGH)
            {"pin": board.D2, "active_low": False}  # D2 is active HIGH (pressed = HIGH)
        ]
        
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
    else:
        # Desktop environment - use keyboard mapping instead of physical buttons
        # We'll create placeholders that will be checked differently in the main loop
        for i in range(3):
            buttons.append({
                "dio": None,
                "pin": f"key_{i}",
                "active_low": False
            })
        print("Desktop environment: Use keyboard keys 1, 2, 3 to simulate buttons D0, D1, D2")
    
    return buttons

# Function to create the initial display interface - only called once
def setup_display_interface(main_group, current_distance, past_readings, hysteresis):
    # Clear the display
    while len(main_group) > 0:
        main_group.pop()
    
    # Create a UI elements object to store references
    ui_elements = UIElements()
    
    # Get screen dimensions - default to desktop size if not on CircuitPython
    display_width = 320  # Default for desktop
    display_height = 240  # Default for desktop
    
    if is_circuitpython and not is_fake_circuitpython and hasattr(board, 'DISPLAY'):
        # We're on real CircuitPython hardware with a display
        display_width = board.DISPLAY.width
        display_height = board.DISPLAY.height
    
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
    
    # Past readings section header - this never changes
    history_y = current_y + y_spacing
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
def update_current_distance(ui_elements, current_distance, display=None):
    if ui_elements.current_distance_label:
        ui_elements.current_distance_label.text = f"Current: {current_distance:.1f} cm"
        # Force display refresh if on desktop
        if not is_circuitpython and display and hasattr(display, 'refresh'):
            display.refresh()

# Function to update only the past readings
def update_past_readings(ui_elements, past_readings, display=None):
    for i, label_obj in enumerate(ui_elements.past_reading_labels):
        if i < len(past_readings):
            label_obj.text = f"{i+1}: {past_readings[i]:.1f} cm"
        else:
            label_obj.text = f"{i+1}: ---.-- cm"  # Empty slot
    # Force display refresh if on desktop
    if not is_circuitpython and display and hasattr(display, 'refresh'):
        display.refresh()

# Function to update only the hysteresis value
def update_hysteresis(ui_elements, hysteresis, display=None):
    if ui_elements.hysteresis_label:
        ui_elements.hysteresis_label.text = f"Hysteresis: {hysteresis:.1f}cm"
        # Force display refresh if on desktop
        if not is_circuitpython and display and hasattr(display, 'refresh'):
            display.refresh()

# Function to update only the countdown timer
def update_countdown(ui_elements, seconds_remaining, display=None):
    if ui_elements.countdown_label:
        ui_elements.countdown_label.text = f"Sleep in: {seconds_remaining}s"
        # Force display refresh if on desktop
        if not is_circuitpython and display and hasattr(display, 'refresh'):
            display.refresh()

# Function to connect to WiFi with robust error handling
def connect_wifi():
    if not is_circuitpython:
        print("Desktop environment: WiFi connection simulation")
        return True
        
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
    if not is_circuitpython:
        print(f"Desktop environment: Simulating data send to Adafruit IO feed '{feed_name or FEED_NAME}': {value}")
        return True
        
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


# Initialize the sensor and related variables
sensor = None
sensor_type = None
sensor_out_of_range = 400  # Default out of range value for VL53L0X
i2c = None

if is_circuitpython and not is_fake_circuitpython:
    # Initialize the I2C bus on actual CircuitPython hardware
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        
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
else:
    # Desktop environment - use simulated sensor
    print("Desktop environment: Using simulated distance sensor")
    sensor_type = "SIMULATED"
    sensor_out_of_range = 400

# Global variables to track time and last readings
last_report_time = 0
last_distance = 0
past_readings = []
hysteresis = DEFAULT_HYSTERESIS  # Default hysteresis value from settings.toml

# Initialize display
display, main_group, backlight = setup_display()

# Initialize buttons
buttons = setup_buttons()
# Read distance with improved error handling and modal sampling
def read_distance():
    try:
        if is_circuitpython:
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
                        
                        # Get distance (already in mm)
                        raw_range = sensor.distance
                        
                        # Check range status
                        if sensor.status != 0:
                            print(f"VL53L1X status error: {sensor.status}")
                            continue
                            
                        # Check if out of range
                        if raw_range >= sensor_out_of_range * 10:  # Check in mm
                            print(f"VL53L1X out of range: {raw_range/10:.1f}cm")
                            continue
                            
                        # Convert to cm
                        reading = raw_range / 10
                        
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
        else:
            # Desktop environment - use simulated distance sensor
            import random
            # Simulate a realistic oil tank reading (between 20-80cm with some noise)
            base_reading = 40.0  # Base level of oil in tank
            noise = random.uniform(-2.0, 2.0)  # Add some random noise
            reading = base_reading + noise
            print(f"Simulated distance reading: {reading:.1f}cm")
            return reading
            
    except Exception as e:
        print(f"Unexpected error in read_distance: {e}")
        
        # Report error to error feed if on CircuitPython
        if is_circuitpython and wifi.radio.connected:
            send_to_adafruit_io(f"Sensor error: {str(e)}", ERROR_FEED_NAME)
            
        return -1

# Check if waking from deep sleep
wake_reason = None

if is_circuitpython:
    if isinstance(alarm.wake_alarm, alarm.pin.PinAlarm):
        print("Woke from button press!")
        wake_reason = "button"
        # Turn on backlight if we have control over it
        if backlight:
            backlight.value = True
    elif alarm.wake_alarm:
        print("Woke from time alarm!")
        wake_reason = "timer"
    elif supervisor.runtime.run_reason is supervisor.RunReason.STARTUP:
        print("First boot, initializing...")
        last_report_time = 0
        last_distance = 0
        past_readings = []
    time.sleep(2) # debug
else:
    # Desktop environment - always treat as first boot
    print("Desktop environment, initializing...")
    wake_reason = "startup"
    last_report_time = 0
    last_distance = 0
    past_readings = []
    
# Try to load previous state from a file
try:
    # Desktop environments should use the same state file, so we can switch back and forth
    with open("state.json", "r") as f:
        state = json.load(f)
        last_report_time = state["last_report_time"]
        last_distance = state["last_distance"]
        past_readings = state.get("past_readings", [])
        hysteresis = state.get("hysteresis", DEFAULT_HYSTERESIS)
        print(f"Loaded state: last report at {last_report_time}, distance: {last_distance}cm")
        print(f"Hysteresis: {hysteresis}cm")
except (OSError, ValueError, FileNotFoundError) as e:
    print(f"No valid state file found, starting fresh: {e}")
    last_report_time = 0
    last_distance = 0
    past_readings = []
    hysteresis = DEFAULT_HYSTERESIS

def main():
    global last_report_time, last_distance, past_readings, hysteresis
    
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
    distance_change = abs(current_distance - last_distance) if last_distance > 0 else 0
    
    should_report = (
        (time_since_last_report >= REPORT_INTERVAL) or  # Report every 3 hours
        (time_since_last_report >= MIN_REPORT_INTERVAL) or  # Report at least daily
        (distance_change >= hysteresis and distance_change > 0) or  # Report on significant change
        (wake_reason == "button")  # Report if woken by button
    )
    
    # Set up the display ONCE (not repeatedly)
    ui_elements = setup_display_interface(main_group, current_distance, past_readings, hysteresis)
    
    # Report data if needed
    report_success = False
    if should_report:
        # Connect to WiFi with error handling
        wifi_connected = connect_wifi()
        
        if wifi_connected:
            # Report to Adafruit IO
            report_success = send_to_adafruit_io(current_distance)
            
            if report_success:
                # Update last reported values only on successful report
                last_report_time = current_time
            
            # Disconnect WiFi to save power if on CircuitPython
            if is_circuitpython:
                wifi.radio.enabled = False
        else:
            print("ERROR: Could not connect to WiFi - skipping data upload")
    
    # Update the last distance - only store valid readings
    if current_distance > 0:
        last_distance = current_distance
    
    # Handle button interaction and display
    start_time = time.monotonic()
    stay_awake = True
    
    # Different main loop based on the environment
    if is_circuitpython:
        # CircuitPython main loop
        try:
            while stay_awake and (time.monotonic() - start_time < AWAKE_TIME):
                # Calculate remaining time
                remaining_time = int(AWAKE_TIME - (time.monotonic() - start_time))
                
                # ONLY update the countdown text, not the entire display
                update_countdown(ui_elements, remaining_time)
                
                # Check buttons with error handling
                try:
                    # D0: Decrease hysteresis (active LOW)
                    if buttons[0]["dio"] is not None:
                        is_pressed = buttons[0]["active_low"] == (not buttons[0]["dio"].value)
                        if is_pressed:
                            hysteresis = max(MIN_HYSTERESIS, hysteresis - 0.5)  # Respect minimum from settings
                            print(f"Hysteresis decreased to {hysteresis}cm")
                            # ONLY update the hysteresis display element
                            update_hysteresis(ui_elements, hysteresis)
                            time.sleep(0.3)  # Debounce
                    
                    # D1: Increase hysteresis (active HIGH)
                    if buttons[1]["dio"] is not None:
                        is_pressed = buttons[1]["active_low"] == (not buttons[1]["dio"].value)
                        if is_pressed:
                            hysteresis = min(MAX_HYSTERESIS, hysteresis + 0.5)  # Respect maximum from settings
                            print(f"Hysteresis increased to {hysteresis}cm")
                            # ONLY update the hysteresis display element
                            update_hysteresis(ui_elements, hysteresis)
                            time.sleep(0.3)  # Debounce
                    
                    # D2: Force report (active HIGH)
                    if buttons[2]["dio"] is not None:
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
            # First try to write to the file system
            with open("state.json", "w") as f:
                json.dump({
                    "last_report_time": last_report_time,
                    "last_distance": last_distance,
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
        
        # Calculate time until next wake
        time_until_next_check = min(REPORT_INTERVAL, MIN_REPORT_INTERVAL - time_since_last_report)
        if time_until_next_check < 0:
            time_until_next_check = REPORT_INTERVAL
        
        print(f"Going to sleep for {time_until_next_check} seconds")
        
        # Set up alarms with error handling
        try:
            # Set up time alarm
            time_alarm = alarm.time.TimeAlarm(monotonic_time=time.monotonic() + time_until_next_check)
            
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
            
            # Clear the display before sleep to save power
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
    
    else:
        # Desktop environment - PyGame main loop
        import pygame
        pygame.init()
        
        # Save state to a file with error handling
        try:
            with open("state.json", "w") as f:
                json.dump({
                    "last_report_time": last_report_time,
                    "last_distance": last_distance,
                    "past_readings": past_readings,
                    "hysteresis": hysteresis
                }, f)
            print("State saved")
        except Exception as e:
            print(f"Error saving state: {e}")
        
        # Main desktop loop
        try:
            running = True
            new_reading_interval = 30  # Seconds between new readings
            last_reading_time = time.monotonic()
            
            while running:
                # Check PyGame display running status and events
                if display and hasattr(display, 'check_quit') and display.check_quit():
                    running = False
                    break
                
                # Process pygame events
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.KEYDOWN:
                        # Key 1 = D0: Decrease hysteresis
                        if event.key == pygame.K_1:
                            hysteresis = max(MIN_HYSTERESIS, hysteresis - 0.5)
                            print(f"Hysteresis decreased to {hysteresis}cm")
                            update_hysteresis(ui_elements, hysteresis, display)
                        
                        # Key 2 = D1: Increase hysteresis
                        elif event.key == pygame.K_2:
                            hysteresis = min(MAX_HYSTERESIS, hysteresis + 0.5)
                            print(f"Hysteresis increased to {hysteresis}cm")
                            update_hysteresis(ui_elements, hysteresis, display)
                        
                        # Key 3 = D2: Force report
                        elif event.key == pygame.K_3:
                            print("Manual report requested")
                            current_distance = read_distance()  # Get fresh reading
                            report_success = send_to_adafruit_io(current_distance)
                            if report_success:
                                last_report_time = time.monotonic()
                                print("Manual report successful")
                                # Update display with new reading
                                update_current_distance(ui_elements, current_distance, display)
                            else:
                                print("Manual report failed")
                
                # Update countdown
                current_time = time.monotonic()
                remaining_time = int(AWAKE_TIME - (current_time - start_time))
                
                if remaining_time <= 0:
                    remaining_time = 0  # Don't show negative time
                    # On desktop, we don't actually sleep, just get a new reading
                    if current_time - last_reading_time >= new_reading_interval:
                        print("Taking new reading")
                        current_distance = read_distance()
                        
                        # Update past readings
                        if last_distance > 0:
                            past_readings.insert(0, last_distance)
                            past_readings = past_readings[:MAX_STORED_READINGS]
                        
                        # Check if we should report
                        distance_change = abs(current_distance - last_distance) if last_distance > 0 else 0
                        if distance_change >= hysteresis or current_time - last_report_time >= MIN_REPORT_INTERVAL:
                            report_success = send_to_adafruit_io(current_distance)
                            if report_success:
                                last_report_time = current_time
                        
                        # Update the UI
                        update_current_distance(ui_elements, current_distance, display)
                        update_past_readings(ui_elements, past_readings, display)
                        
                        # Update last distance
                        last_distance = current_distance
                        
                        # Reset timers
                        start_time = current_time
                        last_reading_time = current_time
                        
                # Update the countdown display
                update_countdown(ui_elements, remaining_time, display)
                # Refresh if display exists and has the refresh method
                if display and hasattr(display, 'refresh'):
                    display.refresh()
                
                # Sleep a bit to avoid maxing out CPU
                time.sleep(0.1)
                
        except Exception as e:
            print(f"Error in desktop main loop: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Clean shutdown
            print("Shutting down PyGame...")
            pygame.quit()

# Run the main program with robust error handling
try:
    main()
except Exception as e:
    print(f"Critical error occurred: {e}")
    print("*** Traceback:")
    import traceback
    traceback.print_exc()
    time.sleep(3)
    
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
        
        if is_circuitpython and not is_fake_circuitpython:
            # Show error on CircuitPython display
            board.DISPLAY.root_group = error_group
            time.sleep(10)  # Show error for 10 seconds
            # Reset the microcontroller on error
            microcontroller.reset()
        else:
            # For desktop, create a new PyGame display for the error
            try:
                from blinka_displayio_pygamedisplay import PyGameDisplay
                error_display = PyGameDisplay(width=320, height=240)
                error_display.show(splash=error_group)
                error_display.refresh()
                
                # Wait for 10 seconds or until window is closed
                start_time = time.monotonic()
                while time.monotonic() - start_time < 10:
                    if error_display.check_quit():
                        break
                    time.sleep(0.1)
                    
                # Clean shutdown
                import pygame
                pygame.quit()
                
                # Exit with error code
                import sys
                sys.exit(1)
            except Exception as pygame_error:
                print(f"Error showing PyGame error screen: {pygame_error}")
                time.sleep(1)
                import sys
                sys.exit(1)
    except Exception as display_error:
        print(f"Error showing error screen: {display_error}")
        time.sleep(10)  # Delay anyway
        
        if is_circuitpython and not is_fake_circuitpython:
            # Reset the microcontroller on error
            microcontroller.reset()
        else:
            # Exit with error code
            import sys
            sys.exit(1)