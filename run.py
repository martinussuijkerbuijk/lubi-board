import cv2
import numpy as np
import json
import os
from ultralytics import YOLO
import math

# --- CONFIGURATION ---
# Board Topology (Change these to match your physical board!)
GRID_ROWS = 9       # Number of horizontal lines (intersections)
GRID_COLS = 5       # Number of vertical lines (intersections)

# Calibration Settings (Must match dataset_collector.py)
CALIBRATION_FILE = "../calibration_matrix.json"
BLEED_PADDING = 60  # Must match the padding used during data collection

# Distance Threshold
# If a coin is more than this many pixels away from a node, ignore it.
SNAP_THRESHOLD = 40 

# Load your trained model
MODEL_PATH = "runs/detect/coin_model_v12/weights/best.pt" 

def load_calibration():
    if not os.path.exists(CALIBRATION_FILE):
        print("Error: Calibration file not found.")
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
    # 1. Setup
    print("Loading calibration...")
    matrix, warped_size = load_calibration()
    if matrix is None: return

    print("Generating Grid...")
    grid_nodes = generate_grid_nodes(warped_size[0], warped_size[1], GRID_ROWS, GRID_COLS)

    print(f"Loading Model: {MODEL_PATH}...")
    try:
        model = YOLO(MODEL_PATH)
    except Exception as e:
        print(f"Error loading model: {e}")
        print("Did you run train_model.py successfully?")
        return

    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    print("--- INFERENCE RUNNING ---")
    print("Press 'q' to quit.")

    while True:
        ret, frame = cap.read()
        if not ret: break
        
        # 2. Preprocessing: Warp the frame
        # We perform detection on the FLAT board, just like training
        warped_frame = cv2.warpPerspective(frame, matrix, warped_size)
        display_frame = warped_frame.copy()
        
        # 3. Inference
        results = model(warped_frame, verbose=False, conf=0.5)
        
        current_board_state = {} # format: {(row, col): "class_name"}

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