# Low Power Distance Monitor with Adafruit IO
# For CircuitPython on ESP32-S2/S3 with VL53L0X/VL53L1X sensor

import time
import board
import busio
import adafruit_vl53l0x
import rtc
import supervisor
import wifi
import socketpool
import ssl
import adafruit_requests
import microcontroller
import alarm
import json
from secrets import secrets

# Configuration
ADAFRUIT_IO_URL = "https://io.adafruit.com/api/v2/"
ADAFRUIT_USERNAME = secrets["aio_username"]
ADAFRUIT_KEY = secrets["aio_key"]
FEED_NAME = "distance-sensor"
REPORT_INTERVAL = 3 * 60 * 60  # 3 hours in seconds
MIN_REPORT_INTERVAL = 24 * 60 * 60  # 24 hours in seconds for mandatory reporting
SIGNIFICANT_CHANGE = 2.0  # 2cm change threshold

# Function to connect to WiFi
def connect_wifi():
    print("Connecting to WiFi...")
    wifi.radio.connect(secrets["ssid"], secrets["password"])
    print(f"Connected to {secrets['ssid']}!")
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

# Global variables to track time and last reading
last_report_time = 0
last_distance = 0

# Check if waking from deep sleep
if supervisor.runtime.run_reason is supervisor.RunReason.STARTUP:
    print("First boot, initializing...")
    last_report_time = 0
    last_distance = 0
elif alarm.wake_alarm:
    print("Woke from alarm!")
    
    # Try to load previous state from a file
    try:
        with open("state.json", "r") as f:
            state = json.load(f)
            last_report_time = state["last_report_time"]
            last_distance = state["last_distance"]
            print(f"Loaded state: last report at {last_report_time}, distance: {last_distance}cm")
    except (OSError, ValueError):
        print("No valid state file found, starting fresh")
        last_report_time = 0
        last_distance = 0

# Main loop
def main():
    global last_report_time, last_distance
    
    current_time = time.monotonic()
    
    # Measure distance a few times and average for reliability
    total_distance = 0
    samples = 5
    
    for _ in range(samples):
        total_distance += sensor.range / 10  # Convert from mm to cm
        time.sleep(0.1)
    
    current_distance = total_distance / samples
    print(f"Current distance: {current_distance:.1f}cm")
    
    # Determine if we need to report based on criteria
    time_since_last_report = current_time - last_report_time
    distance_change = abs(current_distance - last_distance)
    
    should_report = (
        (time_since_last_report >= REPORT_INTERVAL) or  # Report every 3 hours
        (time_since_last_report >= MIN_REPORT_INTERVAL) or  # Report at least daily
        (distance_change >= SIGNIFICANT_CHANGE)  # Report on significant change
    )
    
    if should_report:
        # Connect to WiFi
        connect_wifi()
        
        # Report to Adafruit IO
        send_to_adafruit_io(current_distance)
        
        # Update last reported values
        last_report_time = current_time
        last_distance = current_distance
        
        # Save state to a file
        try:
            with open("state.json", "w") as f:
                json.dump({
                    "last_report_time": last_report_time,
                    "last_distance": last_distance
                }, f)
            print("State saved")
        except OSError as e:
            print(f"Error saving state: {e}")
        
        # Disconnect WiFi to save power
        wifi.radio.enabled = False
    
    # Calculate time until next wake
    time_until_next_check = min(REPORT_INTERVAL, MIN_REPORT_INTERVAL - time_since_last_report)
    if time_until_next_check < 0:
        time_until_next_check = REPORT_INTERVAL
    
    print(f"Going to sleep for {time_until_next_check} seconds")
    
    # Set up time alarm
    time_alarm = alarm.time.TimeAlarm(monotonic_time=time.monotonic() + time_until_next_check)
    
    # Go to deep sleep
    alarm.exit_and_deep_sleep_until_alarms(time_alarm)

# Run the main program
try:
    main()
except Exception as e:
    print(f"Error occurred: {e}")
    # Reset the microcontroller on error
    microcontroller.reset()