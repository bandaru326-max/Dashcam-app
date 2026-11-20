"""
GPIO Controller HAL for Physical Push-Button and Status LED.
Runs as an autonomous hardware daemon. Continues functioning seamlessly
even if the mobile smartphone disconnects.
"""

from __future__ import annotations
import threading
import time
from enum import Enum
from typing import Callable, Optional


class LEDPattern(str, Enum):
    OFF = "OFF"
    SOLID = "SOLID"
    BLINK_1HZ = "BLINK_1HZ"      # Recording in progress
    BLINK_4HZ = "BLINK_4HZ"      # Locked / Critical Alert
    BREATHING = "BREATHING"      # Standby / Hotspot beacon


class GPIOController:
    """Manages physical button gestures and status LED patterns on Raspberry Pi 5."""

    def __init__(
        self,
        button_pin: int = 17,
        led_pin: int = 22,
        simulated: bool = False,
        on_short_click: Optional[Callable[[], None]] = None,
        on_long_press: Optional[Callable[[], None]] = None,
        on_double_click: Optional[Callable[[], None]] = None,
    ):
        self.button_pin = button_pin
        self.led_pin = led_pin
        self.simulated = simulated
        self.on_short_click = on_short_click
        self.on_long_press = on_long_press
        self.on_double_click = on_double_click

        self._pattern = LEDPattern.SOLID
        self._running = False
        self._led_thread: Optional[threading.Thread] = None
        self._btn_thread: Optional[threading.Thread] = None
        self._is_hardware = False
        self._gpio = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        if not self.simulated:
            self._try_init_hardware()

        # Start LED pattern runner
        self._led_thread = threading.Thread(
            target=self._led_worker, daemon=True, name="GPIO_LED_Worker"
        )
        self._led_thread.start()

        # Start Button polling / interrupt worker
        self._btn_thread = threading.Thread(
            target=self._button_worker, daemon=True, name="GPIO_Button_Worker"
        )
        self._btn_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._gpio:
            try:
                self._gpio.cleanup()
            except Exception:
                pass

    def set_led_pattern(self, pattern: LEDPattern) -> None:
        self._pattern = pattern

    def get_led_pattern(self) -> LEDPattern:
        return self._pattern

    # Manual test hooks for simulation / API control
    def simulate_button_click(self) -> None:
        print("[GPIO] Simulating physical button single click (Toggle Recording).")
        if self.on_short_click:
            self.on_short_click()

    def simulate_button_long_press(self) -> None:
        print("[GPIO] Simulating physical button long press (Lock Segment).")
        if self.on_long_press:
            self.on_long_press()

    def simulate_button_double_click(self) -> None:
        print("[GPIO] Simulating physical button double click (Snapshot).")
        if self.on_double_click:
            self.on_double_click()

    def _try_init_hardware(self) -> None:
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.button_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(self.led_pin, GPIO.OUT, initial=GPIO.LOW)
            self._gpio = GPIO
            self._is_hardware = True
            print(f"[GPIO] Hardware GPIO initialized (Button pin {self.button_pin}, LED pin {self.led_pin}).")
        except Exception as e:
            print(f"[GPIO] Hardware GPIO init failed: {e}. Running in simulation mode.")
            self._is_hardware = False
            self.simulated = True

    def _set_hardware_led(self, state: bool) -> None:
        if self._is_hardware and self._gpio:
            try:
                self._gpio.output(self.led_pin, self._gpio.HIGH if state else self._gpio.LOW)
            except Exception:
                pass

    def _led_worker(self) -> None:
        """Runs the active LED blink/breathing pattern."""
        step = 0
        while self._running:
            pattern = self._pattern
            if pattern == LEDPattern.OFF:
                self._set_hardware_led(False)
                time.sleep(0.1)
            elif pattern == LEDPattern.SOLID:
                self._set_hardware_led(True)
                time.sleep(0.1)
            elif pattern == LEDPattern.BLINK_1HZ:
                # 500ms ON, 500ms OFF
                self._set_hardware_led(True)
                time.sleep(0.5)
                self._set_hardware_led(False)
                time.sleep(0.5)
            elif pattern == LEDPattern.BLINK_4HZ:
                # 125ms ON, 125ms OFF
                self._set_hardware_led(True)
                time.sleep(0.125)
                self._set_hardware_led(False)
                time.sleep(0.125)
            elif pattern == LEDPattern.BREATHING:
                # Soft toggle simulation
                self._set_hardware_led(True)
                time.sleep(1.0)
                self._set_hardware_led(False)
                time.sleep(1.0)

    def _button_worker(self) -> None:
        """Physical button state machine with click, long-press, and double-click."""
        if not self._is_hardware or self._gpio is None:
            return  # In simulation, events are triggered programmatically or via API

        last_state = 1  # Pull-up default high
        press_time = 0.0
        release_time = 0.0
        click_count = 0

        while self._running:
            try:
                current_state = self._gpio.input(self.button_pin)
                now = time.time()

                # Falling edge: Button pressed down
                if last_state == 1 and current_state == 0:
                    press_time = now
                    # Check if this is a double click candidate
                    if (now - release_time) < 0.4:
                        click_count += 1
                    else:
                        click_count = 1

                # Button held down
                elif last_state == 0 and current_state == 0:
                    held_duration = now - press_time
                    if held_duration >= 2.5 and click_count == 1:
                        # Long press detected
                        if self.on_long_press:
                            self.on_long_press()
                        click_count = 0
                        # Wait for release to prevent repeating
                        while self._running and self._gpio.input(self.button_pin) == 0:
                            time.sleep(0.05)

                # Rising edge: Button released
                elif last_state == 0 and current_state == 1:
                    release_time = now
                    duration = release_time - press_time
                    if duration < 1.5:
                        if click_count >= 2:
                            # Double click
                            if self.on_double_click:
                                self.on_double_click()
                            click_count = 0
                        else:
                            # Single click candidate; wait briefly for potential second click
                            time.sleep(0.35)
                            if self._gpio.input(self.button_pin) == 1 and click_count == 1:
                                if self.on_short_click:
                                    self.on_short_click()
                                click_count = 0

                last_state = current_state
                time.sleep(0.02)  # 50Hz debounce poll
            except Exception as e:
                print(f"[GPIO] Button worker exception: {e}")
                time.sleep(0.2)
