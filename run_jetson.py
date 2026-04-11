import cv2
import numpy as np
import json
import os
import math
import time
import threading
import logging
import Jetson.GPIO as GPIO
from ultralytics import YOLO
from pythonosc.udp_client import SimpleUDPClient
from pythonosc import dispatcher, osc_server

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- CONFIGURATION ---
GRID_ROWS = 5
GRID_COLS = 9
SNAP_THRESHOLD = 40
BLEED_PADDING = 60

# Files
CALIBRATION_FILE = "calibration_matrix.json"
MODEL_PATH = "runs/detect/coin_model_v13/weights/best.engine"

# GPIO Pin Config (BOARD pin numbering)
BUTTON_PIN = 7    # Active LOW, internal pull-up. Change to match your wiring.
LED_PIN    = 15   # PWM output to L298N IN1.    Change to match your wiring.

# RGB strip type: True = Common Anode (12V+), False = Common Cathode (GND)
LED_IS_COMMON_ANODE = True

# OSC Config
OSC_TARGET_IP = "192.168.1.103" #Raspberry Piq
OSC_SEND_PORT = 9000
OSC_RECV_PORT = 9001

# Performance: run YOLO every N frames, reuse cached results in between
INFERENCE_EVERY_N_FRAMES = 3

# Required classes
REQUIRED_CLASSES = ["will", "fount", "ethos", "cycle", "seed"]


# ---------------------------------------------------------------------------
# LED control thread — mirrors the Arduino sketch behaviour:
#   IDLE    → breathing glow
#   ACTIVE  → flicker 5x then hold on
#   RESET   → back to breathing (happens when button_triggered flips False)
#
# Uses direct GPIO.output() + manual timing instead of GPIO.PWM so it works
# reliably on any GPIO pin (hardware-PWM pins via sysfs + ChangeDutyCycle from
# a background thread is unreliable on Jetson and causes cleanup errors).
# ---------------------------------------------------------------------------
def led_thread_func(state, led_flickered, stop_event):
    # Logic-level shortcuts so the rest of the code reads "ON / OFF"
    LED_ON  = GPIO.LOW  if LED_IS_COMMON_ANODE else GPIO.HIGH
    LED_OFF = GPIO.HIGH if LED_IS_COMMON_ANODE else GPIO.LOW

    PWM_PERIOD = 0.020   # 20 ms per PWM cycle = 50 Hz (matches Arduino glowSpeed)

    brightness  = 0      # 0 = off, 255 = fully on
    fade_amount = 3

    GPIO.output(LED_PIN, LED_OFF)

    while not stop_event.is_set():
        triggered = state["button_triggered"]

        if not triggered:
            # ---- IDLE: breathing glow ----
            if led_flickered["done"]:
                # Returning from active state → reset
                led_flickered["done"] = False
                brightness  = 0
                fade_amount = abs(fade_amount)
                GPIO.output(LED_PIN, LED_OFF)

            # Manual PWM: spend (brightness/255) of the period in ON state
            duty     = brightness / 255.0
            on_time  = duty * PWM_PERIOD
            off_time = PWM_PERIOD - on_time

            if on_time > 0.0005:
                GPIO.output(LED_PIN, LED_ON)
                time.sleep(on_time)

            GPIO.output(LED_PIN, LED_OFF)
            if off_time > 0.0005:
                time.sleep(off_time)

            # Advance brightness (same cadence as Arduino: once per glowSpeed)
            brightness += fade_amount
            if brightness <= 0 or brightness >= 255:
                fade_amount = -fade_amount
                brightness  = max(0, min(255, brightness))

        else:
            # ---- ACTIVE ----
            if not led_flickered["done"]:
                # Flicker 5 times (60 ms on / 60 ms off)
                for _ in range(5):
                    if stop_event.is_set():
                        return
                    GPIO.output(LED_PIN, LED_ON)
                    time.sleep(0.060)
                    GPIO.output(LED_PIN, LED_OFF)
                    time.sleep(0.060)
                # Hold fully on until reset
                GPIO.output(LED_PIN, LED_ON)
                led_flickered["done"] = True
            else:
                time.sleep(0.050)   # stay on, avoid busy-loop

    GPIO.output(LED_PIN, LED_OFF)   # tidy up on exit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_calibration():
    if not os.path.exists(CALIBRATION_FILE):
        logging.error("Error: Calibration file not found. Please copy it from your PC.")
        return None, None

    with open(CALIBRATION_FILE, 'r') as f:
        data = json.load(f)
        matrix = np.array(data["homography_matrix"])
        base_size = tuple(data["warped_size"])

        translation_matrix = np.array([
            [1, 0, BLEED_PADDING],
            [0, 1, BLEED_PADDING],
            [0, 0, 1]
        ])
        final_matrix = np.dot(translation_matrix, matrix)
        final_size = (base_size[0] + 2 * BLEED_PADDING, base_size[1] + 2 * BLEED_PADDING)

        return final_matrix, final_size


def generate_grid_nodes(total_w, total_h, rows, cols):
    nodes = {}
    start_x = BLEED_PADDING
    end_x = total_w - BLEED_PADDING
    start_y = BLEED_PADDING
    end_y = total_h - BLEED_PADDING

    step_x = (end_x - start_x) / (cols - 1) if cols > 1 else 0
    step_y = (end_y - start_y) / (rows - 1) if rows > 1 else 0

    for r in range(rows):
        for c in range(cols):
            x = int(start_x + c * step_x)
            y = int(start_y + r * step_y)
            nodes[(r, c)] = (x, y)
    return nodes


def get_closest_node(point, nodes):
    px, py = point
    best_node = None
    min_dist = float('inf')
    for key, (nx, ny) in nodes.items():
        dist = math.sqrt((px - nx)**2 + (py - ny)**2)
        if dist < min_dist:
            min_dist = dist
            best_node = key
    return best_node, min_dist


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # --- OSC Setup ---
    osc_client = SimpleUDPClient(OSC_TARGET_IP, OSC_SEND_PORT)

    state = {
        "button_triggered": False,
        "sent_start_signal": False,
        "detection_start_time": None,
        "button_released": True,
    }

    # Shared flag so the LED thread knows whether it has already flickered
    # for the current button press (avoids repeating the flicker on every loop).
    led_flickered = {"done": False}

    def on_back_received(address, *args):
        logging.info("--- BACK RECEIVED: Resetting State ---")
        state["button_triggered"] = False
        state["sent_start_signal"] = False
        state["detection_start_time"] = None
        # led_thread resets led_flickered["done"] itself when it sees triggered=False

    osc_dispatcher = dispatcher.Dispatcher()
    osc_dispatcher.map("/pendulum/back", on_back_received)
    receive_server = osc_server.ThreadingOSCUDPServer(("0.0.0.0", OSC_RECV_PORT), osc_dispatcher)
    threading.Thread(target=receive_server.serve_forever, daemon=True).start()
    logging.info(f"OSC receiver listening on port {OSC_RECV_PORT}")

    # --- GPIO Setup ---
    GPIO.setmode(GPIO.BOARD)

    # Button
    GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def on_gpio_event(channel):
        if GPIO.input(channel) == GPIO.LOW:
            # Falling edge → button pressed
            if state["button_released"] and not state["button_triggered"]:
                logging.info("Button Pressed (GPIO falling edge)")
                state["button_triggered"] = True
            state["button_released"] = False
        else:
            # Rising edge → button released
            state["button_released"] = True

    GPIO.add_event_detect(BUTTON_PIN, GPIO.BOTH, callback=on_gpio_event, bouncetime=50)
    logging.info(f"GPIO button on BOARD pin {BUTTON_PIN} (active LOW, internal pull-up)")

    # LED (direct GPIO output — thread does manual PWM, no GPIO.PWM needed)
    GPIO.setup(LED_PIN, GPIO.OUT,
               initial=GPIO.HIGH if LED_IS_COMMON_ANODE else GPIO.LOW)  # start off
    logging.info(f"GPIO LED on BOARD pin {LED_PIN} (common-anode={LED_IS_COMMON_ANODE})")

    # Start LED background thread
    led_stop = threading.Event()
    t_led = threading.Thread(
        target=led_thread_func,
        args=(state, led_flickered, led_stop),
        daemon=True,
    )
    t_led.start()

    # --- Calibration & Grid ---
    logging.info("Loading calibration...")
    matrix, warped_size = load_calibration()
    if matrix is None:
        led_stop.set()
        GPIO.cleanup()
        return

    logging.info("Generating grid...")
    grid_nodes = generate_grid_nodes(warped_size[0], warped_size[1], GRID_ROWS, GRID_COLS)

    # --- Model ---
    if not os.path.exists(MODEL_PATH):
        logging.error(f"Model not found: {MODEL_PATH}")
        logging.info("Run: yolo export model=best.pt format=engine device=0")
        led_stop.set()
        GPIO.cleanup()
        return

    logging.info(f"Loading TensorRT Engine: {MODEL_PATH}...")
    model = YOLO(MODEL_PATH, task='detect')

    # --- Camera ---
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    logging.info("--- INFERENCE RUNNING ---")
    logging.info("Press 'q' to quit.")

    # Frame-skip state
    frame_count = 0
    cached_board_state = {}
    cached_detections = []
    cached_boxes = []

    prev_time = time.time()

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            warped_frame = cv2.warpPerspective(frame, matrix, warped_size)
            display_frame = warped_frame.copy()

            frame_count += 1
            if frame_count % INFERENCE_EVERY_N_FRAMES == 0:
                results = model(warped_frame, verbose=False, conf=0.5, device=0)

                cached_board_state = {}
                cached_detections = []
                cached_boxes = []

                for result in results:
                    for box in result.boxes:
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                        cls_id = int(box.cls[0])
                        class_name = result.names[cls_id]

                        center_x = int((x1 + x2) / 2)
                        center_y = int((y1 + y2) / 2)
                        cached_detections.append((class_name, center_x, center_y))

                        node_key, dist = get_closest_node((center_x, center_y), grid_nodes)
                        if dist < SNAP_THRESHOLD:
                            cached_board_state[node_key] = class_name
                            cached_boxes.append((x1, y1, x2, y2, class_name, node_key))
                        else:
                            cached_boxes.append((x1, y1, x2, y2, class_name, None))

            # --- Draw cached detections ---
            for (x1, y1, x2, y2, class_name, node_key) in cached_boxes:
                center_x = int((x1 + x2) / 2)
                center_y = int((y1 + y2) / 2)
                if node_key is not None:
                    grid_x, grid_y = grid_nodes[node_key]
                    row, col = node_key
                    cv2.line(display_frame, (center_x, center_y), (grid_x, grid_y), (0, 255, 0), 2)
                    cv2.rectangle(display_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(display_frame, f"{class_name} ({row},{col})", (x1, y1 - 5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                else:
                    cv2.rectangle(display_frame, (x1, y1), (x2, y2), (0, 0, 255), 1)
                    cv2.putText(display_frame, "?", (center_x, center_y),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            # --- Draw Grid ---
            for key, (nx, ny) in grid_nodes.items():
                color = (0, 255, 0) if key in cached_board_state else (50, 50, 50)
                cv2.circle(display_frame, (nx, ny), 3, color, -1)

            # --- OSC Safeguard Logic ---
            unique_found = {}
            extras = []
            for name, x, y in cached_detections:
                if name in REQUIRED_CLASSES and name not in unique_found:
                    unique_found[name] = (x, y)
                else:
                    extras.append((x, y))

            if state["button_triggered"]:
                if len(cached_detections) > 0 and state["detection_start_time"] is None:
                    state["detection_start_time"] = time.time()

                elapsed = 0.0
                if state["detection_start_time"] is not None:
                    elapsed = time.time() - state["detection_start_time"]

                should_trigger = False
                trigger_reason = ""

                if len(unique_found) == 5:
                    should_trigger = True
                    trigger_reason = "All 5 classes detected"
                elif elapsed > 10.0:
                    should_trigger = True
                    trigger_reason = f"Timeout ({elapsed:.1f}s)"
                    logging.info(f"Safeguard timeout ({elapsed:.1f}s): filling missing classes.")

                if should_trigger and not state["sent_start_signal"]:
                    logging.info(f"!!! TRIGGER: {trigger_reason} !!!")
                    logging.info(f"Classes found ({len(unique_found)}): {list(unique_found.keys())}")

                    msg_args = []
                    for name in REQUIRED_CLASSES:
                        if name in unique_found:
                            x, y = unique_found[name]
                            msg_args.extend([name, x, y])
                        else:
                            logging.warning(f"  Missing '{name}', filling in...")
                            if extras:
                                ex, ey = extras.pop(0)
                                msg_args.extend([name, ex, ey])
                                logging.info(f"    -> Used extra at ({ex}, {ey})")
                            else:
                                cx, cy = warped_size[0] // 2, warped_size[1] // 2
                                msg_args.extend([name, cx, cy])
                                logging.info(f"    -> Used center default ({cx}, {cy})")

                    logging.info(f"OSC SENDING: {msg_args}")
                    osc_client.send_message("/pendulum/start", msg_args)
                    logging.info("OSC SENT: /pendulum/start. Waiting for ACK...")
                    state["sent_start_signal"] = True

                elif not state["sent_start_signal"]:
                    print(f"Waiting... Found: {len(unique_found)}/5 {list(unique_found.keys())} | Time: {elapsed:.1f}s   ", end='\r')

            # --- Status Overlay ---
            if not state["button_triggered"]:
                cv2.putText(display_frame, "WAITING FOR BUTTON...", (20, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
            else:
                cv2.putText(display_frame, "DETECTION ACTIVE", (20, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                if state["sent_start_signal"]:
                    cv2.putText(display_frame, "SIGNAL SENT - WAITING FOR RESET...", (20, 80),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            # --- FPS Display ---
            curr_time = time.time()
            fps = 1.0 / max(curr_time - prev_time, 1e-6)
            prev_time = curr_time
            cv2.putText(display_frame, f"FPS: {int(fps)}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)

            cv2.imshow("Jetson View", display_frame)
            if cv2.waitKey(1) == ord('q'):
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()
        led_stop.set()
        t_led.join(timeout=1.0)   # wait for thread to turn LED off cleanly
        GPIO.cleanup()
        logging.info("Shutdown complete.")


if __name__ == "__main__":
    main()
