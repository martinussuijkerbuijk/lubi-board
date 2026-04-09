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

# GPIO Button Config (BOARD pin numbering)
# Pin 7 = GPIO9. Change to match your wiring.
BUTTON_PIN = 7

# OSC Config
OSC_TARGET_IP = "127.0.0.1"
OSC_SEND_PORT = 9000
OSC_RECV_PORT = 9001

# Performance: run YOLO every N frames, reuse cached results in between
INFERENCE_EVERY_N_FRAMES = 3

# Required classes
REQUIRED_CLASSES = ["gold", "spice", "deer", "man", "tree"]


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


def main():
    # --- OSC Setup ---
    osc_client = SimpleUDPClient(OSC_TARGET_IP, OSC_SEND_PORT)

    state = {
        "button_triggered": False,
        "sent_start_signal": False,
        "detection_start_time": None,
        "button_released": True,   # tracks release so we detect edges, not levels
    }

    def on_back_received(address, *args):
        logging.info("--- BACK RECEIVED: Resetting State ---")
        state["button_triggered"] = False
        state["sent_start_signal"] = False
        state["detection_start_time"] = None

    osc_dispatcher = dispatcher.Dispatcher()
    osc_dispatcher.map("/pendulum/back", on_back_received)
    receive_server = osc_server.ThreadingOSCUDPServer(("0.0.0.0", OSC_RECV_PORT), osc_dispatcher)
    threading.Thread(target=receive_server.serve_forever, daemon=True).start()
    logging.info(f"OSC receiver listening on port {OSC_RECV_PORT}")

    # --- GPIO Button Setup ---
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)  # Active LOW

    def on_button_press(channel):
        """Called on falling edge (button pressed, active LOW)."""
        if state["button_released"]:
            if not state["button_triggered"]:
                logging.info("Button Pressed (GPIO falling edge)")
                state["button_triggered"] = True
            state["button_released"] = False

    def on_button_release(channel):
        """Called on rising edge (button released)."""
        state["button_released"] = True

    GPIO.add_event_detect(BUTTON_PIN, GPIO.BOTH, callback=lambda ch: (
        on_button_press(ch) if GPIO.input(ch) == GPIO.LOW else on_button_release(ch)
    ), bouncetime=50)

    logging.info(f"GPIO button on BOARD pin {BUTTON_PIN} (active LOW, internal pull-up)")

    # --- Calibration & Grid ---
    logging.info("Loading calibration...")
    matrix, warped_size = load_calibration()
    if matrix is None:
        GPIO.cleanup()
        return

    logging.info("Generating grid...")
    grid_nodes = generate_grid_nodes(warped_size[0], warped_size[1], GRID_ROWS, GRID_COLS)

    # --- Model ---
    if not os.path.exists(MODEL_PATH):
        logging.error(f"Model not found: {MODEL_PATH}")
        logging.info("Run: yolo export model=best.pt format=engine device=0")
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
    cached_board_state = {}     # {(row,col): class_name}
    cached_detections = []      # [(class_name, cx, cy)]
    cached_boxes = []           # [(x1,y1,x2,y2,class_name,node_key_or_None)]

    prev_time = time.time()

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            warped_frame = cv2.warpPerspective(frame, matrix, warped_size)
            display_frame = warped_frame.copy()

            frame_count += 1
            run_inference = (frame_count % INFERENCE_EVERY_N_FRAMES == 0)

            if run_inference:
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

            # --- Button / Status Display ---
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
        GPIO.cleanup()
        logging.info("GPIO cleaned up.")


if __name__ == "__main__":
    main()
