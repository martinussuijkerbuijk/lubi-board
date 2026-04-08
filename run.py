import cv2
import numpy as np
import json
import os
import time
import threading
import serial
import logging
from pythonosc.udp_client import SimpleUDPClient
from pythonosc import dispatcher, osc_server
from ultralytics import YOLO
import math

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- CONFIGURATION ---
# Board Topology (Change these to match your physical board!)
GRID_ROWS = 9       # Number of horizontal lines (intersections)
GRID_COLS = 5       # Number of vertical lines (intersections)

# Calibration Settings (Must match dataset_collector.py)
CALIBRATION_FILE = "./calibration_matrix.json"
BLEED_PADDING = 60  # Must match the padding used during data collection

# Distance Threshold
# If a coin is more than this many pixels away from a node, ignore it.
SNAP_THRESHOLD = 40 

# Load your trained model
MODEL_PATH = "runs/detect/coin_model_v13/weights/best.pt" 

# Button Arduino Config
BUTTON_PORT = "COM5"
BUTTON_BAUD = 9600

def load_calibration():
    if not os.path.exists(CALIBRATION_FILE):
        logging.error("Error: Calibration file not found.")
        return None, None
    
    with open(CALIBRATION_FILE, 'r') as f:
        data = json.load(f)
        matrix = np.array(data["homography_matrix"])
        base_size = tuple(data["warped_size"]) # This is the original 640x640
        
        # Re-apply the bleed padding logic from the collector script
        translation_matrix = np.array([
            [1, 0, BLEED_PADDING],
            [0, 1, BLEED_PADDING],
            [0, 0, 1]
        ])
        final_matrix = np.dot(translation_matrix, matrix)
        final_size = (base_size[0] + 2 * BLEED_PADDING, base_size[1] + 2 * BLEED_PADDING)
        
        return final_matrix, final_size

def generate_grid_nodes(total_w, total_h, rows, cols):
    """
    Generates a dictionary of grid nodes.
    Keys: (row, col) tuples
    Values: (x, y) pixel coordinates
    """
    nodes = {}
    
    # The grid area starts at PADDING and ends at WIDTH - PADDING
    start_x = BLEED_PADDING
    end_x = total_w - BLEED_PADDING
    
    start_y = BLEED_PADDING
    end_y = total_h - BLEED_PADDING
    
    # Calculate spacing
    # Avoid division by zero if rows/cols are 1
    step_x = (end_x - start_x) / (cols - 1) if cols > 1 else 0
    step_y = (end_y - start_y) / (rows - 1) if rows > 1 else 0
    
    for r in range(rows):
        for c in range(cols):
            x = int(start_x + c * step_x)
            y = int(start_y + r * step_y)
            nodes[(r, c)] = (x, y)
            
    return nodes

def get_closest_node(point, nodes):
    """
    Finds the grid node closest to the given point (x, y).
    Returns: node_key, distance
    """
    px, py = point
    best_node = None
    min_dist = float('inf')
    
    for key, (nx, ny) in nodes.items():
        # Euclidean distance
        dist = math.sqrt((px - nx)**2 + (py - ny)**2)
        if dist < min_dist:
            min_dist = dist
            best_node = key
            
    return best_node, min_dist

def main():
    # OSC Configuration
    osc_client = SimpleUDPClient("127.0.0.1", 9000)
    required_classes = ["gold", "spice", "deer", "man", "tree"]
    
    # System State (Thread-safe container)
    state = {
        "button_triggered": False,
        "sent_start_signal": False,
        "detection_start_time": None,
        "button_released": True
    }
    
    last_retry_time = 0

    # Serial Setup for Button
    ser_button = None
    try:
        ser_button = serial.Serial(BUTTON_PORT, BUTTON_BAUD, timeout=0.1)
        logging.info(f"Connected to Button Arduino on {BUTTON_PORT}")
    except Exception as e:
        logging.warning(f"Could not connect to Button Arduino on {BUTTON_PORT}: {e}")
    
    # OSC Receiver Setup (Listen for ACK)
    def on_back_received(address, *args):
        logging.info(f"--- BACK RECEIVED: Resetting State ---")
        # Reset everything to wait for next button press
        state["button_triggered"] = False
        state["sent_start_signal"] = False
        state["detection_start_time"] = None

    osc_dispatcher = dispatcher.Dispatcher()
    osc_dispatcher.map("/pendulum/back", on_back_received)
    # Listen on 9001 (Default feedback port of the controller)
    receive_server = osc_server.ThreadingOSCUDPServer(("0.0.0.0", 9001), osc_dispatcher)
    threading.Thread(target=receive_server.serve_forever, daemon=True).start()

    # 1. Setup
    logging.info("Loading calibration...")
    matrix, warped_size = load_calibration()
    if matrix is None: return

    logging.info("Generating Grid...")
    grid_nodes = generate_grid_nodes(warped_size[0], warped_size[1], GRID_ROWS, GRID_COLS)

    logging.info(f"Loading Model: {MODEL_PATH}...")
    try:
        model = YOLO(MODEL_PATH)
    except Exception as e:
        logging.error(f"Error loading model: {e}")
        logging.info("Did you run train_model.py successfully?")
        return

    cap = cv2.VideoCapture(1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    logging.info("--- INFERENCE RUNNING ---")
    logging.info("Press 'q' to quit.")

    while True:
        ret, frame = cap.read()
        if not ret: break

        # 2. Preprocessing: Warp the frame
        # We perform detection on the FLAT board, just like training
        warped_frame = cv2.warpPerspective(frame, matrix, warped_size)
        display_frame = warped_frame.copy()
        
        # --- AUTO-RECONNECT LOGIC ---
        if ser_button is None or not ser_button.is_open:
            # Try to reconnect every 2 seconds if disconnected
            if time.time() - last_retry_time > 2.0:
                last_retry_time = time.time()
                try:
                    ser_button = serial.Serial(BUTTON_PORT, BUTTON_BAUD, timeout=0.1)
                    logging.info(f"Reconnected to Button Arduino on {BUTTON_PORT}")
                except Exception:
                    pass

        # --- BUTTON CHECK ---
        if ser_button and ser_button.in_waiting > 0:
            try:
                # Read available data from buffer
                data = ser_button.read(ser_button.in_waiting)
                decoded = data.decode('utf-8', errors='ignore')

                # Check for release ('1')
                if '1' in decoded:
                    state["button_released"] = True
                
                # Check for press ('0') - Active LOW
                if '0' in decoded:
                    # Only trigger if button was previously released (edge detection)
                    if state["button_released"]:
                        if not state["button_triggered"]:
                            logging.info("Button Pressed (Signal '0' received)")
                            state["button_triggered"] = True
                        # Mark as currently held
                        state["button_released"] = False
            except Exception as e:
                logging.error(f"Serial Error: {e}")

        # Display Button/System Status
        if ser_button is None or not ser_button.is_open:
             cv2.putText(display_frame, f"ERROR: BUTTON NOT CONNECTED ({BUTTON_PORT})", (20, 50), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        else:
            if not state["button_triggered"]:
                cv2.putText(display_frame, "WAITING FOR BUTTON...", (20, 50), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)
            else:
                cv2.putText(display_frame, "DETECTION ACTIVE", (20, 50), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                if state["sent_start_signal"]:
                     cv2.putText(display_frame, "SIGNAL SENT - WAITING FOR RESET...", (20, 80), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
        # 3. Inference
        results = model(warped_frame, verbose=False, conf=0.5)
        
        current_board_state = {} # format: {(row, col): "class_name"}
        frame_detections = []    # list of (class_name, x, y) for OSC logic

        # 4. Process Detections
        for result in results:
            for box in result.boxes:
                # Get Box Info
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                cls_id = int(box.cls[0])
                class_name = model.names[cls_id]
                
                # Calculate Center
                center_x = int((x1 + x2) / 2)
                center_y = int((y1 + y2) / 2)
                
                # Collect for safeguard logic
                frame_detections.append((class_name, center_x, center_y))
                
                # 5. Grid Snapping
                node_key, dist = get_closest_node((center_x, center_y), grid_nodes)
                
                if dist < SNAP_THRESHOLD:
                    # Valid placement!
                    row, col = node_key
                    current_board_state[node_key] = class_name
                    
                    # --- VISUALIZATION ---
                    # Draw connection to grid point
                    grid_x, grid_y = grid_nodes[node_key]
                    cv2.line(display_frame, (center_x, center_y), (grid_x, grid_y), (0, 255, 0), 2)
                    
                    # Draw Label
                    label = f"{class_name} ({row},{col})"
                    cv2.rectangle(display_frame, (x1, y1-20), (x2, y1), (0, 255, 0), -1)
                    cv2.putText(display_frame, label, (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
                    cv2.rectangle(display_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                else:
                    # Floating coin (not on grid)
                    cv2.rectangle(display_frame, (x1, y1), (x2, y2), (0, 0, 255), 1)
                    cv2.putText(display_frame, "?", (center_x, center_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        # --- OSC SAFEGUARD LOGIC ---
        # Check for unique required classes vs extra/duplicate detections
        unique_found = {} # name -> (x, y)
        extras = []       # list of (x, y) for objects available to be re-labeled

        for name, x, y in frame_detections:
            if name in required_classes and name not in unique_found:
                unique_found[name] = (x, y)
            else:
                # This is a duplicate or unknown class; save its position
                extras.append((x, y))

        # Timer Management
        # Only run logic if button has been pressed
        if state["button_triggered"]:
            
            # Start timer on first detection
            if len(frame_detections) > 0 and state["detection_start_time"] is None:
                state["detection_start_time"] = time.time()
            
            elapsed = 0
            if state["detection_start_time"] is not None:
                elapsed = time.time() - state["detection_start_time"]
                
            should_trigger = False
            trigger_reason = ""
            
            # Trigger Condition 1: All 5 classes detected
            if len(unique_found) == 5:
                should_trigger = True
                trigger_reason = "All 5 classes detected"
            # Trigger Condition 2: Timeout (Safeguard)
            elif elapsed > 10.0:
                should_trigger = True
                trigger_reason = f"Timeout ({elapsed:.1f}s)"
                logging.info(f"Safeguard Timeout ({elapsed:.1f}s): Filling in missing classes.")

            if should_trigger and not state["sent_start_signal"]:
                logging.info(f"!!! TRIGGER ACTIVATED: {trigger_reason} !!!")
                logging.info(f"Classes found ({len(unique_found)}): {list(unique_found.keys())}")

                msg_args = []
                # Construct payload: [name, x, y, name, x, y, ...]
                for name in required_classes:
                    if name in unique_found:
                        x, y = unique_found[name]
                        msg_args.extend([name, x, y])
                    else:
                        # Fill in missing class
                        logging.warning(f"  Missing '{name}', filling in...")
                        if extras:
                            # Use the position of an extra object (e.g. detected but wrong class)
                            ex, ey = extras.pop(0)
                            msg_args.extend([name, ex, ey])
                            logging.info(f"    -> Used extra object at ({ex}, {ey})")
                        else:
                            # No objects left to borrow, default to center of board
                            cx, cy = warped_size[0] // 2, warped_size[1] // 2
                            msg_args.extend([name, cx, cy])
                            logging.info(f"    -> Used center default ({cx}, {cy})")
                
                logging.info(f"OSC PAYLOAD SENDING: {msg_args}")
                osc_client.send_message("/pendulum/start", msg_args)
                logging.info(f"OSC SENT: /pendulum/start. Waiting for ACK...")
                state["sent_start_signal"] = True
            elif state["button_triggered"] and not state["sent_start_signal"]:
                # Print status to console (overwrite line) for real-time debugging
                print(f"Waiting... Found: {len(unique_found)}/5 {list(unique_found.keys())} | Time: {elapsed:.1f}s   ", end='\r')
        # ---------------------------

        # 6. Draw Grid (Background)
        for key, (nx, ny) in grid_nodes.items():
            color = (200, 200, 200)
            # Highlight occupied nodes
            if key in current_board_state:
                color = (0, 255, 0)
            cv2.circle(display_frame, (nx, ny), 3, color, -1)

        # 7. Output State (For debugging)
        # In a real app, you might send this via MQTT or API
        # print(current_board_state)

        cv2.imshow("Coin Detector", display_frame)
        if cv2.waitKey(1) == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()