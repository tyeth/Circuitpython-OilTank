import board
import supervisor
import storage
import digitalio
import time

# Setup buttons D1 and D2 as inputs with pull-ups
d1 = digitalio.DigitalInOut(board.D1)
d1.direction = digitalio.Direction.INPUT

d2 = digitalio.DigitalInOut(board.D2)
d2.direction = digitalio.Direction.INPUT

print("Booting up...")
print("Hold D1 or D2 to keep storage read-only to device (write for PC).")
time.sleep(1.500)  # Allow time for the user to press buttons

print(f"D1: {d1.value}, D2: {d2.value}")
# Check if buttons are pressed (with pull-up, button press gives False)
button_pressed = d1.value or d2.value

try:
    # If at least one button is pressed, wait for 2 seconds to confirm
    if button_pressed:
        print("Button(s) detected! Hold for 2 seconds to keep storage read-only to MCU...")
        countdown = 2
        
        # Count down while checking if buttons are still held
        while countdown > 0 and (d1.value or d2.value):
            print(f"Keeping read-only for MCU in {countdown} seconds...")
            time.sleep(1)
            countdown -= 1
        
        # If buttons were held for the full duration
        if countdown == 0 and (d1.value or d2.value):
            print("Buttons held! Storage remains read-only for MCU.")
        else:
            print("Button released. Enabling flash write access to MCU.")
            storage.remount("/", readonly=False)
            print("Storage mounted with write access enabled to MCU.")
    else:
        print("No buttons pressed. Enabling write access to MCU...")
        # No buttons pressed, enable write access
        storage.remount("/", readonly=False)
        print("Storage mounted with write access to MCU enabled.")

    # Clean up
    d1.deinit()
    d2.deinit()
except Exception as e:
    print(f"An error occurred: {e}")