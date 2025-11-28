import cv2
import numpy as np
import json
import os
from ultralytics import YOLO
import math
import time

# --- CONFIGURATION ---
GRID_ROWS = 5       
GRID_COLS = 9       
SNAP_THRESHOLD = 40 
BLEED_PADDING = 60  

# Files
CALIBRATION_FILE = "calibration_matrix.json"
# IMPORTANT: On Jetson, we use the TensorRT engine we exported in Step 5
MODEL_PATH = "best.engine" 

def load_calibration():
    if not os.path.exists(CALIBRATION_FILE):
        print("Error: Calibration file not found. Please copy it from your PC.")
        return None, None
    
    with open(CALIBRATION_FILE, 'r') as f:
        data = json.load(f)
        matrix = np.array(data["homography_matrix"])
        base_size = tuple(data["warped_size"])
        
        # Re-apply bleed padding
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
    print("--- JETSON COIN DETECTOR ---")
    
    # 1. Load Calibration
    matrix, warped_size = load_calibration()
    if matrix is None: return

    # 2. Generate Grid
    grid_nodes = generate_grid_nodes(warped_size[0], warped_size[1], GRID_ROWS, GRID_COLS)

    # 3. Load Model
    if not os.path.exists(MODEL_PATH):
        print(f"Error: {MODEL_PATH} not found.")
        print("Did you run 'yolo export model=best.pt format=engine device=0'?")
        return
        
    print(f"Loading TensorRT Engine: {MODEL_PATH}...")
    # 'task=detect' is explicit for engine loading
    model = YOLO(MODEL_PATH, task='detect') 

    # 4. Camera Setup
    # Use index 0 for USB, or use a GStreamer pipeline string for CSI cameras
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    
    # FPS Counter
    prev_time = 0

    while True:
        ret, frame = cap.read()
        if not ret: break
        
        # Warp Perspective
        warped_frame = cv2.warpPerspective(frame, matrix, warped_size)
        display_frame = warped_frame.copy()
        
        # Inference
        # stream=True is efficient for video loops
        # device=0 ensures GPU usage
        results = model(warped_frame, verbose=False, conf=0.5, device=0, stream=True)
        
        current_board_state = {}

        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                cls_id = int(box.cls[0])
                class_name = result.names[cls_id] # result.names handles engine mappings
                
                center_x = int((x1 + x2) / 2)
                center_y = int((y1 + y2) / 2)
                
                node_key, dist = get_closest_node((center_x, center_y), grid_nodes)
                
                if dist < SNAP_THRESHOLD:
                    row, col = node_key
                    current_board_state[node_key] = class_name
                    
                    # Visuals
                    grid_x, grid_y = grid_nodes[node_key]
                    cv2.line(display_frame, (center_x, center_y), (grid_x, grid_y), (0, 255, 0), 2)
                    cv2.rectangle(display_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(display_frame, f"{class_name}", (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                else:
                    cv2.rectangle(display_frame, (x1, y1), (x2, y2), (0, 0, 255), 1)

        # Draw Grid
        for key, (nx, ny) in grid_nodes.items():
            color = (0, 255, 0) if key in current_board_state else (50, 50, 50)
            cv2.circle(display_frame, (nx, ny), 3, color, -1)

        # FPS Display
        curr_time = time.time()
        fps = 1 / (curr_time - prev_time)
        prev_time = curr_time
        cv2.putText(display_frame, f"FPS: {int(fps)}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 2)

        cv2.imshow("Jetson View", display_frame)
        if cv2.waitKey(1) == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()