"""
Perpetual Pendulum Controller
==============================
Controls an electromagnet via Arduino to keep a permanent-magnet pendulum
swinging indefinitely.

System overview:
  - Webcam tracks the pendulum magnet (coloured marker or blob detection)
  - Position history is used to predict where the pendulum will be,
    compensating for camera + serial latency
  - Arduino receives simple serial commands to set electromagnet polarity
  - OSC server lets external software start/stop and send disruption commands

Dependencies (install with pip):
  pip install opencv-python numpy pyserial python-osc

Arduino sketch: pendulum_arduino.ino  (included separately)
"""

import cv2
import numpy as np
import serial
import serial.tools.list_ports
import threading
import time
import argparse
import logging
import json
from pathlib import Path
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Optional, Tuple

# OSC
from pythonosc import dispatcher as osc_dispatcher
from pythonosc import osc_server
from pythonosc.udp_client import SimpleUDPClient

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("pendulum")

# Config file location (in the same directory as the script)
CONFIG_FILE = Path(__file__).parent / "pendulum_config.json"


# ---------------------------------------------------------------------------
# Configuration – tweak these without touching the logic
# ---------------------------------------------------------------------------
@dataclass
class Config:
    # --- Camera ---
    camera_index: int = 0
    frame_width: int = 1280
    frame_height: int = 720
    target_fps: int = 60          # request from camera; actual may differ

    # --- Tracking: HSV colour range for the pendulum marker ---
    # Default: bright orange (adjust via calibration mode)
    hsv_lower: np.ndarray = field(
        default_factory=lambda: np.array([5, 150, 150])
    )
    hsv_upper: np.ndarray = field(
        default_factory=lambda: np.array([25, 255, 255])
    )
    min_blob_area: int = 100      # pixels²; ignore smaller blobs

    # --- Geometry ---
    # X pixel column that corresponds to the centre (electromagnet axis).
    # Set to None to auto-detect as frame centre.
    center_x_px: Optional[int] = None
    center_y_px: Optional[int] = None  # Y center (calibrated during calibration)
    # Dead-band around centre (pixels) – no force applied inside this zone
    dead_band_px: int = 20
    # Hysteresis zone (pixels) – once in dead-band, must exit this far before re-engaging
    # This prevents rapid on/off flickering at the boundary
    hysteresis_px: int = 30

    # --- Electromagnet control ---
    # Serial port of the Arduino; None → auto-detect first Arduino found
    serial_port: Optional[str] = None
    serial_baud: int = 115200

    # Electromagnet strength 0–255 (PWM)
    pull_strength: int = 200      # strength when pulling toward centre
    push_strength: int = 180      # strength when pushing away from centre

    # --- Latency compensation ---
    # Total round-trip latency (camera + processing + serial) in seconds.
    # The predictor will extrapolate this far into the future.
    latency_s: float = 0.08       # 80 ms default; tune via --latency flag

    # History depth for the velocity estimator (number of frames)
    history_len: int = 12

    # --- OSC ---
    osc_listen_ip: str = "0.0.0.0"
    osc_listen_port: int = 9000
    osc_feedback_ip: str = "127.0.0.1"
    osc_feedback_port: int = 9001

    def save(self, filepath: Path = CONFIG_FILE) -> None:
        """Save configuration to JSON file."""
        # Convert dataclass to dict
        data = {
            "camera_index": self.camera_index,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "target_fps": self.target_fps,
            "hsv_lower": self.hsv_lower.tolist(),
            "hsv_upper": self.hsv_upper.tolist(),
            "min_blob_area": self.min_blob_area,
            "center_x_px": self.center_x_px,
            "center_y_px": self.center_y_px,
            "dead_band_px": self.dead_band_px,
            "hysteresis_px": self.hysteresis_px,
            "serial_port": self.serial_port,
            "serial_baud": self.serial_baud,
            "pull_strength": self.pull_strength,
            "push_strength": self.push_strength,
            "latency_s": self.latency_s,
            "history_len": self.history_len,
            "osc_listen_ip": self.osc_listen_ip,
            "osc_listen_port": self.osc_listen_port,
            "osc_feedback_ip": self.osc_feedback_ip,
            "osc_feedback_port": self.osc_feedback_port,
        }
        
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            log.info("Configuration saved to %s", filepath)
        except Exception as e:
            log.error("Failed to save config: %s", e)

    @classmethod
    def load(cls, filepath: Path = CONFIG_FILE) -> 'Config':
        """Load configuration from JSON file, or return defaults if file doesn't exist."""
        if not filepath.exists():
            log.info("No config file found at %s, using defaults", filepath)
            return cls()
        
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            cfg = cls()
            cfg.camera_index = data.get("camera_index", cfg.camera_index)
            cfg.frame_width = data.get("frame_width", cfg.frame_width)
            cfg.frame_height = data.get("frame_height", cfg.frame_height)
            cfg.target_fps = data.get("target_fps", cfg.target_fps)
            cfg.hsv_lower = np.array(data.get("hsv_lower", cfg.hsv_lower.tolist()))
            cfg.hsv_upper = np.array(data.get("hsv_upper", cfg.hsv_upper.tolist()))
            cfg.min_blob_area = data.get("min_blob_area", cfg.min_blob_area)
            cfg.center_x_px = data.get("center_x_px", cfg.center_x_px)
            cfg.center_y_px = data.get("center_y_px", cfg.center_y_px)
            cfg.dead_band_px = data.get("dead_band_px", cfg.dead_band_px)
            cfg.hysteresis_px = data.get("hysteresis_px", cfg.hysteresis_px)
            cfg.serial_port = data.get("serial_port", cfg.serial_port)
            cfg.serial_baud = data.get("serial_baud", cfg.serial_baud)
            cfg.pull_strength = data.get("pull_strength", cfg.pull_strength)
            cfg.push_strength = data.get("push_strength", cfg.push_strength)
            cfg.latency_s = data.get("latency_s", cfg.latency_s)
            cfg.history_len = data.get("history_len", cfg.history_len)
            cfg.osc_listen_ip = data.get("osc_listen_ip", cfg.osc_listen_ip)
            cfg.osc_listen_port = data.get("osc_listen_port", cfg.osc_listen_port)
            cfg.osc_feedback_ip = data.get("osc_feedback_ip", cfg.osc_feedback_ip)
            cfg.osc_feedback_port = data.get("osc_feedback_port", cfg.osc_feedback_port)
            
            log.info("Configuration loaded from %s", filepath)
            return cfg
            
        except Exception as e:
            log.error("Failed to load config: %s, using defaults", e)
            return cls()


# ---------------------------------------------------------------------------
# Arduino serial interface
# ---------------------------------------------------------------------------
class ArduinoInterface:
    """
    Thin wrapper around a serial connection to the Arduino.

    Protocol (ASCII, newline-terminated):
        PULL,<strength>   – energise magnet to attract pendulum (0–255)
        PUSH,<strength>   – energise magnet to repel pendulum  (0–255)
        OFF               – de-energise magnet
        PING              – Arduino replies PONG (latency check)
    """

    CMD_PULL = "PULL"
    CMD_PUSH = "PUSH"
    CMD_OFF  = "OFF"

    def __init__(self, port: Optional[str], baud: int):
        self._lock = threading.Lock()
        self._ser: Optional[serial.Serial] = None
        self._connect(port, baud)

    def _connect(self, port: Optional[str], baud: int) -> None:
        if port is None:
            port = self._auto_detect_port()
        if port is None:
            log.warning("No Arduino found – running in DRY-RUN mode (no serial)")
            return
        try:
            self._ser = serial.Serial(port, baud, timeout=1)
            time.sleep(2)  # allow Arduino bootloader to settle
            log.info("Connected to Arduino on %s @ %d baud", port, baud)
        except serial.SerialException as exc:
            log.error("Could not open %s: %s – running dry-run", port, exc)

    @staticmethod
    def _auto_detect_port() -> Optional[str]:
        for p in serial.tools.list_ports.comports():
            desc = (p.description or "").lower()
            if any(k in desc for k in ("arduino", "ch340", "ftdi", "usb serial")):
                log.info("Auto-detected Arduino on %s (%s)", p.device, p.description)
                return p.device
        return None

    def _send(self, cmd: str) -> None:
        if self._ser is None:
            log.debug("DRY-RUN: %s", cmd)
            return
        with self._lock:
            try:
                self._ser.write((cmd + "\n").encode())
            except serial.SerialException as exc:
                log.error("Serial write failed: %s", exc)

    def pull(self, strength: int = 200) -> None:
        self._send(f"{self.CMD_PULL},{strength}")

    def push(self, strength: int = 180) -> None:
        self._send(f"{self.CMD_PUSH},{strength}")

    def off(self) -> None:
        self._send(self.CMD_OFF)

    def close(self) -> None:
        if self._ser and self._ser.is_open:
            self.off()
            self._ser.close()


# ---------------------------------------------------------------------------
# Position predictor
# ---------------------------------------------------------------------------
class PositionPredictor:
    """
    Estimates future pendulum X position using a rolling velocity window.

    The pendulum follows approximately simple-harmonic motion, but we don't
    assume that; instead we do a local linear extrapolation which is accurate
    enough over the short latency window (~80 ms).
    """

    def __init__(self, history_len: int = 12):
        self._times: deque = deque(maxlen=history_len)
        self._positions: deque = deque(maxlen=history_len)

    def update(self, t: float, x: float) -> None:
        self._times.append(t)
        self._positions.append(x)

    def predict(self, ahead_s: float) -> Optional[float]:
        """Return predicted X position `ahead_s` seconds from now."""
        if len(self._times) < 3:
            return None
        # Weighted linear regression (recent points weighted higher)
        times = np.array(self._times, dtype=float)
        pos   = np.array(self._positions, dtype=float)
        weights = np.linspace(0.3, 1.0, len(times))

        t_now = times[-1]
        dt = times - t_now          # relative time
        # Least-squares fit: pos = a*dt + b
        W = np.diag(weights)
        A = np.column_stack([dt, np.ones(len(dt))])
        try:
            coeffs, *_ = np.linalg.lstsq(W @ A, W @ pos, rcond=None)
        except np.linalg.LinAlgError:
            return None
        a, b = coeffs
        return b + a * ahead_s      # extrapolate

    def velocity(self) -> Optional[float]:
        """Pixels/second estimate."""
        if len(self._times) < 2:
            return None
        dt = self._times[-1] - self._times[-2]
        if dt < 1e-6:
            return None
        return (self._positions[-1] - self._positions[-2]) / dt


# ---------------------------------------------------------------------------
# Webcam tracker
# ---------------------------------------------------------------------------
class PendulumTracker:
    """
    Finds the pendulum blob in each frame using HSV colour thresholding.
    Falls back to the previous position if detection fails.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._cap = cv2.VideoCapture(cfg.camera_index)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  cfg.frame_width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.frame_height)
        self._cap.set(cv2.CAP_PROP_FPS, cfg.target_fps)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # minimise buffer lag

        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open camera index {cfg.camera_index}")

        self.frame_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.frame_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        # Center X: use configured value, or default to frame center
        # IMPORTANT: If you change resolution, you MUST recalibrate!
        if cfg.center_x_px is not None:
            self.center_x = cfg.center_x_px
            log.info("Using configured center_x=%d", self.center_x)
        else:
            self.center_x = self.frame_w // 2
            log.info("Using default center_x=%d (frame center)", self.center_x)
        
        log.info("Camera: %dx%d @ %d fps target", 
                 self.frame_w, self.frame_h, cfg.target_fps)

        self._last_pos: Optional[Tuple[int, int]] = None

    def read_frame(self) -> Tuple[Optional[np.ndarray], Optional[Tuple[int, int]]]:
        """
        Returns (frame, (cx, cy)) where cx,cy is the blob centroid in pixels.
        Returns (frame, None) if detection fails.
        """
        ret, frame = self._cap.read()
        if not ret:
            return None, self._last_pos

        hsv  = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self.cfg.hsv_lower, self.cfg.hsv_upper)
        mask = cv2.erode(mask,  None, iterations=2)
        mask = cv2.dilate(mask, None, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return frame, self._last_pos

        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) < self.cfg.min_blob_area:
            return frame, self._last_pos

        M = cv2.moments(largest)
        if M["m00"] == 0:
            return frame, self._last_pos

        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        
        self._last_pos = (cx, cy)
        return frame, (cx, cy)

    def release(self) -> None:
        self._cap.release()


# ---------------------------------------------------------------------------
# Magnet state machine
# ---------------------------------------------------------------------------
class MagnetState:
    OFF       = "OFF"
    PULL      = "PULL"
    PUSH      = "PUSH"
    CENTERING = "CENTERING"  # Pulling to center before starting
    LAUNCHING = "LAUNCHING"  # Initial push to start swing
    BRAKING   = "BRAKING"    # Active deceleration to center


class PendulumController:
    """
    Core state machine that decides when to pull / push / turn off the magnet.

    Logic (with latency compensation):
      1. Read current position and predict position `latency_s` ahead.
      2. Use velocity sign to determine travel direction.
      3. If predicted position is approaching centre → PULL
         If predicted position has passed centre → PUSH
         If inside dead-band → OFF (let it coast through)
    """

    def __init__(self, cfg: Config, arduino: ArduinoInterface):
        self.cfg = cfg
        self.arduino = arduino
        self.predictor = PositionPredictor(history_len=cfg.history_len)
        self._state = MagnetState.OFF
        self._running = False
        self._brake_mode = False  # True = brake to center, False = perpetual motion
        self._startup_phase = None  # 'centering', 'launching', or None
        self._startup_timer = 0.0
        self._in_dead_zone = False  # Hysteresis state tracker
        self._disrupted = False      # flag set by OSC disrupt command
        self._disrupt_polarity = 1   # +1 or -1
        self._gui_visible = True     # Toggle for video feed
        self._lock = threading.Lock()
        
        # OSC feedback client
        self.osc_feedback = SimpleUDPClient(cfg.osc_feedback_ip, cfg.osc_feedback_port)

    # ------------------------------------------------------------------
    # OSC-facing controls
    # ------------------------------------------------------------------
    def start(self) -> None:
        """
        Begin startup sequence:
        1. CENTERING: Pull to center for 2 seconds
        2. LAUNCHING: Strong push for 0.3 seconds
        3. Normal perpetual motion
        """
        log.info("Perpetual motion: STARTING (centering phase)")
        self._brake_mode = False
        self._startup_phase = 'centering'
        self._startup_timer = time.monotonic()
        self._running = True
        # Send Acknowledgement back to run.py
        try:
            self.osc_feedback.send_message("/pendulum/back", [])
        except Exception as e:
            log.warning("Failed to send ACK: %s", e)

    def stop(self) -> None:
        log.info("Perpetual motion: STOPPED")
        self._running = False
        self._brake_mode = False
        self._startup_phase = None
        self.arduino.off()
        self._state = MagnetState.OFF

    def brake(self) -> None:
        """
        Brake mode: actively decelerate pendulum to center and hold it there.
        Use this to quickly stop a swinging pendulum.
        """
        log.info("BRAKE mode: catching pendulum")
        self._brake_mode = True
        self._running = True
        self._startup_phase = None

    def set_force(self, force: str, strength: Optional[int] = None) -> None:
        """
        Direct magnet control - bypasses all logic and stops any running mode.
        force: "PUSH", "PULL", or "OFF"
        strength: PWM 0-255 (uses config defaults if not specified)
        """
        force = force.upper()
        
        # Stop any running modes - direct control takes priority
        self._running = False
        self._brake_mode = False
        self._startup_phase = None
        
        if force == "PUSH":
            s = strength if strength is not None else self.cfg.push_strength
            self.arduino.push(s)
            self._state = MagnetState.PUSH
            log.info("Direct control: PUSH @ %d (stopped all auto modes)", s)
        elif force == "PULL":
            s = strength if strength is not None else self.cfg.pull_strength
            self.arduino.pull(s)
            self._state = MagnetState.PULL
            log.info("Direct control: PULL @ %d (stopped all auto modes)", s)
        elif force == "OFF":
            self.arduino.off()
            self._state = MagnetState.OFF
            log.info("Direct control: OFF (stopped all auto modes)")
        else:
            log.warning("Invalid force command: %s (use PUSH, PULL, or OFF)", force)
    
    def continue_motion(self) -> None:
        """
        Continue perpetual motion WITHOUT startup sequence.
        Immediately begins pull/push logic based on current position.
        Use this to resume after a disruption or manual control.
        """
        log.info("Perpetual motion: CONTINUING (no startup sequence)")
        self._brake_mode = False
        self._startup_phase = None
        self._running = True

    def show_gui(self) -> None:
        """Show the video feed window."""
        self._gui_visible = True
        log.info("GUI: Video feed ENABLED")

    def hide_gui(self) -> None:
        """Hide the video feed window to save CPU."""
        self._gui_visible = False
        log.info("GUI: Video feed DISABLED (saves CPU)")

    def toggle_gui(self) -> None:
        """Toggle video feed visibility."""
        self._gui_visible = not self._gui_visible
        state = "ENABLED" if self._gui_visible else "DISABLED"
        log.info("GUI: Video feed %s", state)

    def disrupt(self, polarity: int = 1, duration_s: float = 0.3) -> None:
        """
        Briefly energise the magnet in the given polarity to kick the pendulum.
        polarity: +1 → PUSH,  -1 → PULL
        """
        log.info("DISRUPT polarity=%+d duration=%.2fs", polarity, duration_s)
        def _do():
            with self._lock:
                if polarity > 0:
                    self.arduino.push(self.cfg.push_strength)
                else:
                    self.arduino.pull(self.cfg.pull_strength)
            time.sleep(duration_s)
            with self._lock:
                self.arduino.off()
        threading.Thread(target=_do, daemon=True).start()

    def set_latency(self, latency_s: float) -> None:
        self.cfg.latency_s = latency_s
        log.info("Latency compensation set to %.3f s", latency_s)

    def set_strength(self, pull: int, push: int) -> None:
        self.cfg.pull_strength = pull
        self.cfg.push_strength = push
        log.info("Strengths: pull=%d  push=%d", pull, push)

    # ------------------------------------------------------------------
    # Main update  (called for every camera frame)
    # ------------------------------------------------------------------
    def update(self, t: float, pos: Optional[Tuple[int, int]]) -> str:
        """
        Process one frame. Returns the current magnet state label.
        """
        if pos is None:
            return self._state

        cx, cy = pos
        self.predictor.update(t, float(cx))

        # Send OSC feedback with normalized coordinates
        # Calibrated center point maps to (0.5, 0.5)
        # Edges map to 0.0 and 1.0
        frame_w = self.cfg.frame_width
        frame_h = self.cfg.frame_height
        center_x = self.cfg.center_x_px or (frame_w // 2)
        center_y = self.cfg.center_y_px or (frame_h // 2)
        
        # Normalize so that calibrated center = 0.5, 0.5
        # Left edge = 0.0, right edge = 1.0
        # Top edge = 0.0, bottom edge = 1.0
        x_norm = 0.5 + (cx - center_x) / frame_w
        y_norm = 0.5 + (cy - center_y) / frame_h
        
        # Also send displacement from center (-1.0 to +1.0 where 0.0 = center)
        x_displacement = (cx - center_x) / (frame_w / 2.0)
        y_displacement = (cy - center_y) / (frame_h / 2.0)
        
        try:
            self.osc_feedback.send_message("/pendulum/position", [x_norm, y_norm])
            self.osc_feedback.send_message("/pendulum/displacement", [x_displacement])
            self.osc_feedback.send_message("/pendulum/state", [self._state])
            
            # Also send velocity if available
            vel = self.predictor.velocity()
            if vel is not None:
                self.osc_feedback.send_message("/pendulum/velocity", [vel])
        except Exception as e:
            # Don't crash if OSC feedback fails
            log.debug("OSC feedback error: %s", e)

        if not self._running:
            return self._state

        with self._lock:
            # Handle startup sequence
            if self._startup_phase is not None:
                self._handle_startup(t, cx)
            # Brake mode - decelerate to center
            elif self._brake_mode:
                self._brake_to_center(t, cx)
            # Normal perpetual motion
            else:
                self._decide(t, cx)
        return self._state

    def _handle_startup(self, t: float, cx_now: int) -> None:
        """
        Startup sequence state machine:
        1. CENTERING (2.0s): Pull to center with max strength
        2. LAUNCHING (0.3s): Strong push outward
        3. → Normal operation
        """
        elapsed = t - self._startup_timer
        center = float(self.cfg.center_x_px or (self.cfg.frame_width // 2))
        
        if self._startup_phase == 'centering':
            # Phase 1: Pull to center for 2 seconds
            self._set_state(MagnetState.CENTERING)
            self.arduino.pull(255)  # Max strength
            
            if elapsed > 2.0:
                log.info("Startup: CENTERING complete → LAUNCHING")
                self._startup_phase = 'launching'
                self._startup_timer = t
        
        elif self._startup_phase == 'launching':
            # Phase 2: Strong push for 0.3 seconds
            self._set_state(MagnetState.LAUNCHING)
            self.arduino.push(255)  # Max strength push
            
            if elapsed > 0.3:
                log.info("Startup: LAUNCHING complete → perpetual motion")
                self._startup_phase = None
                self._state = MagnetState.OFF

    def _brake_to_center(self, t: float, cx_now: int) -> None:
        """
        Smart brake mode: Actively decelerate then hold at center.
        
        Strategy:
        1. PUSH when moving toward center (oppose momentum, steal energy)
        2. Switch to PULL when close to center (prevent overshoot)
        3. Keep PULLING when velocity drops (hold in place)
        """
        vel = self.predictor.velocity() or 0.0
        center = float(self.cfg.center_x_px or (self.cfg.frame_width // 2))
        disp = cx_now - center
        
        # Thresholds
        velocity_threshold = 20.0   # pixels/second - "stopped"
        position_threshold = 10.0   # pixels from center - "centered"
        close_to_center = 40.0      # pixels - switch from PUSH to PULL
        
        # Check if successfully stopped and centered
        if abs(vel) < velocity_threshold and abs(disp) < position_threshold:
            log.info("BRAKE complete: pendulum captured at center")
            self._set_state(MagnetState.OFF)
            self._brake_mode = False
            self._running = False
            return
        
        # Determine if moving toward center
        moving_toward_center = (disp > 0 and vel < 0) or (disp < 0 and vel > 0)
        
        if moving_toward_center and abs(disp) > close_to_center:
            # Phase 1: PUSH to oppose momentum (active braking)
            self._set_state(MagnetState.BRAKING)
            self.arduino.push(255)  # Max strength to brake hard
        else:
            # Phase 2 & 3: PULL to center and hold
            self._set_state(MagnetState.BRAKING)
            self.arduino.pull(255)  # Max strength to pull and hold

    def _decide(self, t: float, cx_now: int) -> None:
        cx_pred = self.predictor.predict(self.cfg.latency_s)
        if cx_pred is None:
            cx_pred = float(cx_now)

        vel = self.predictor.velocity() or 0.0
        center = float(self.cfg.center_x_px or (self.cfg.frame_width // 2))
        dead   = self.cfg.dead_band_px
        hysteresis = self.cfg.hysteresis_px

        # Displacement from centre (positive = right of centre)
        disp_now  = cx_now  - center
        disp_pred = cx_pred - center

        # Hysteresis logic to prevent flickering:
        # - Enter dead zone when |disp| < dead_band
        # - Stay in dead zone until |disp| > hysteresis
        if abs(disp_pred) < dead:
            self._in_dead_zone = True
        elif abs(disp_pred) > hysteresis:
            self._in_dead_zone = False

        # If in dead zone (with hysteresis), always turn off
        if self._in_dead_zone:
            self._set_state(MagnetState.OFF)
            return

        # Determine direction of travel
        moving_toward_centre = (disp_now > 0 and vel < 0) or (disp_now < 0 and vel > 0)

        if moving_toward_centre:
            # Approaching centre → PULL (attract)
            self._set_state(MagnetState.PULL)
        else:
            # Moving away from centre (or just crossed) → PUSH (repel)
            self._set_state(MagnetState.PUSH)

    def _set_state(self, new_state: str) -> None:
        if new_state == self._state:
            return
        self._state = new_state
        if   new_state == MagnetState.PULL:
            self.arduino.pull(self.cfg.pull_strength)
        elif new_state == MagnetState.PUSH:
            self.arduino.push(self.cfg.push_strength)
        else:
            self.arduino.off()
        log.debug("Magnet → %s", new_state)


# ---------------------------------------------------------------------------
# OSC server
# ---------------------------------------------------------------------------
def build_osc_server(cfg: Config, controller: PendulumController):
    """
    OSC addresses:
        /pendulum/start               – start perpetual motion (with startup sequence)
        /pendulum/continue            – continue perpetual motion (no startup sequence)
        /pendulum/stop                – stop
        /pendulum/brake               – brake to center (catch pendulum)
        /pendulum/push [strength]     – direct PUSH control (0-255, optional)
        /pendulum/pull [strength]     – direct PULL control (0-255, optional)
        /pendulum/off                 – direct OFF control
        /pendulum/gui/show            – show video feed
        /pendulum/gui/hide            – hide video feed (saves CPU)
        /pendulum/gui/toggle          – toggle video feed
        /pendulum/disrupt  [pol dur]  – DEPRECATED: use /push or /pull instead
        /pendulum/latency  <seconds>  – set latency compensation
        /pendulum/strength <pull> <push> – set PWM strengths 0-255
    """
    d = osc_dispatcher.Dispatcher()

    d.map("/pendulum/start",    lambda addr, *a: controller.start())
    d.map("/pendulum/continue", lambda addr, *a: controller.continue_motion())
    d.map("/pendulum/stop",     lambda addr, *a: controller.stop())
    d.map("/pendulum/brake",    lambda addr, *a: controller.brake())
    
    d.map("/pendulum/gui/show",   lambda addr, *a: controller.show_gui())
    d.map("/pendulum/gui/hide",   lambda addr, *a: controller.hide_gui())
    d.map("/pendulum/gui/toggle", lambda addr, *a: controller.toggle_gui())
    
    def _push(addr, *args):
        strength = int(args[0]) if args else None
        controller.set_force("PUSH", strength)
    d.map("/pendulum/push", _push)
    
    def _pull(addr, *args):
        strength = int(args[0]) if args else None
        controller.set_force("PULL", strength)
    d.map("/pendulum/pull", _pull)
    
    d.map("/pendulum/off", lambda addr, *a: controller.set_force("OFF"))

    def _disrupt(addr, *args):
        pol = int(args[0]) if args else 1
        dur = float(args[1]) if len(args) > 1 else 0.3
        controller.disrupt(pol, dur)
    d.map("/pendulum/disrupt", _disrupt)

    def _latency(addr, *args):
        if args:
            controller.set_latency(float(args[0]))
    d.map("/pendulum/latency", _latency)

    def _strength(addr, *args):
        if len(args) >= 2:
            controller.set_strength(int(args[0]), int(args[1]))
    d.map("/pendulum/strength", _strength)

    server = osc_server.ThreadingOSCUDPServer(
        (cfg.osc_listen_ip, cfg.osc_listen_port), d
    )
    log.info("OSC server listening on %s:%d", cfg.osc_listen_ip, cfg.osc_listen_port)
    return server


# ---------------------------------------------------------------------------
# Debug / calibration overlay
# ---------------------------------------------------------------------------
def draw_overlay(frame: np.ndarray, pos: Optional[Tuple[int,int]],
                 center_x: int, state: str, cfg: Config,
                 vel: Optional[float], pred_x: Optional[float]) -> np.ndarray:
    h, w = frame.shape[:2]

    # Centre line
    cv2.line(frame, (center_x, 0), (center_x, h), (0, 255, 255), 1)

    # Dead-band (inner zone - OFF)
    cv2.rectangle(frame,
                  (center_x - cfg.dead_band_px, 0),
                  (center_x + cfg.dead_band_px, h),
                  (0, 180, 180), 1)
    
    # Hysteresis zone (outer boundary - must cross to re-engage)
    cv2.rectangle(frame,
                  (center_x - cfg.hysteresis_px, 0),
                  (center_x + cfg.hysteresis_px, h),
                  (100, 100, 100), 1)

    # Detected position
    if pos:
        cv2.circle(frame, pos, 12, (0, 255, 0), 2)
        cv2.circle(frame, pos,  3, (0, 255, 0), -1)

    # Predicted position
    if pred_x is not None:
        px = int(pred_x)
        cy = h // 2
        cv2.circle(frame, (px, cy), 8, (0, 128, 255), 2)
        cv2.line(frame, pos or (center_x, cy), (px, cy), (0, 128, 255), 1)

    # State label + stats
    colour = {
        "PULL": (255, 100, 0),
        "PUSH": (0, 100, 255),
        "OFF": (180, 180, 180),
        "CENTERING": (255, 200, 0),
        "LAUNCHING": (0, 255, 100),
        "BRAKING": (255, 0, 255)  # Magenta
    }
    cv2.putText(frame, f"State: {state}",
                (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                colour.get(state, (255,255,255)), 2)
    if vel is not None:
        cv2.putText(frame, f"Vel: {vel:+.1f} px/s",
                    (12, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (220,220,220), 1)
    cv2.putText(frame, f"Latency comp: {cfg.latency_s*1000:.0f} ms",
                (12, 88), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (220,220,220), 1)
    cv2.putText(frame, "V=hide  Q=quit  C=cal  S=start  R=continue  B=brake  1/2/3=push/pull/off",
                (12, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200,200,200), 1)
    return frame


# ---------------------------------------------------------------------------
# HSV calibration helper
# ---------------------------------------------------------------------------
def run_calibration(tracker: PendulumTracker, cfg: Config) -> None:
    """
    Interactive HSV picker and center point calibration.
    
    Instructions:
    1. Position pendulum at rest in the center
    2. Click on the pendulum marker to sample colour
    3. Press SPACE to capture center position
    4. Press Q to finish
    """
    log.info("=== CALIBRATION MODE ===")
    log.info("1. Position pendulum at CENTER (resting)")
    log.info("2. Click on the marker to sample colour (multiple times for accuracy)")
    log.info("3. Press SPACE to capture center position")
    log.info("4. Press Q when done")
    
    samples: list = []
    frame_for_click = [None]
    center_captured = False
    
    # Temporarily use very wide HSV range for initial detection
    temp_lower = np.array([0, 50, 50])    # very permissive
    temp_upper = np.array([180, 255, 255])
    original_lower = cfg.hsv_lower.copy()
    original_upper = cfg.hsv_upper.copy()

    def _on_click(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and frame_for_click[0] is not None:
            hsv = cv2.cvtColor(frame_for_click[0], cv2.COLOR_BGR2HSV)
            px  = hsv[y, x]
            samples.append(px)
            log.info("Sampled HSV: %s at pixel (%d, %d)", px, x, y)
            
            # Update HSV range immediately for live feedback
            if samples:
                arr = np.array(samples, dtype=np.float32)
                lo  = arr.min(axis=0).astype(np.uint8)
                hi  = arr.max(axis=0).astype(np.uint8)
                lo  = np.clip(lo - np.array([10, 40, 40]), 0, 255).astype(np.uint8)
                hi  = np.clip(hi + np.array([10, 40, 40]), 0, 255).astype(np.uint8)
                cfg.hsv_lower = lo
                cfg.hsv_upper = hi
                log.info("  → Updated range: H=%d-%d S=%d-%d V=%d-%d", 
                        lo[0], hi[0], lo[1], hi[1], lo[2], hi[2])

    cv2.namedWindow("Calibration")
    cv2.setMouseCallback("Calibration", _on_click)

    while True:
        frame, pos = tracker.read_frame()
        if frame is None:
            continue
        
        frame_for_click[0] = frame.copy()
        
        # Draw current detection
        if pos:
            cv2.circle(frame, pos, 12, (0, 255, 0), 2)
            cv2.circle(frame, pos, 3, (0, 255, 0), -1)
            
            # Show coordinates
            cv2.putText(frame, f"Pos: {pos[0]}, {pos[1]}", 
                       (pos[0] + 15, pos[1] - 10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        
        # Instructions overlay
        cv2.putText(frame, "Click marker to sample color", 
                   (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame, f"Samples collected: {len(samples)}", 
                   (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.putText(frame, "SPACE = capture center position", 
                   (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame, "Q = finish calibration", 
                   (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        
        if center_captured:
            cv2.putText(frame, f"CENTER CAPTURED: x={cfg.center_x_px}", 
                       (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
        cv2.imshow("Calibration", frame)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord(' '):  # Space bar
            if pos:
                cfg.center_x_px = pos[0]
                cfg.center_y_px = pos[1]
                center_captured = True
                log.info("CENTER captured at x=%d, y=%d (will normalize to 0.5, 0.5)", pos[0], pos[1])
            else:
                log.warning("No pendulum detected - cannot capture center")

    cv2.destroyWindow("Calibration")

    # Finalize HSV ranges
    if samples:
        log.info("HSV calibration complete with %d samples", len(samples))
    else:
        log.warning("No HSV samples collected - using defaults")
        cfg.hsv_lower = original_lower
        cfg.hsv_upper = original_upper
    
    if not center_captured:
        log.warning("Center position NOT captured - using default (frame center)")
    else:
        log.info("Calibration complete! Center: X=%d, Y=%d pixels", cfg.center_x_px, cfg.center_y_px)
    
    # Auto-save calibrated settings
    cfg.save()
    log.info("Calibrated settings saved for next run")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Perpetual Pendulum Controller")
    parser.add_argument("--camera",   type=int,   default=None, help="Camera index (overrides config)")
    parser.add_argument("--width",    type=int,   default=None, help="Camera frame width")
    parser.add_argument("--height",   type=int,   default=None, help="Camera frame height")
    parser.add_argument("--fps",      type=int,   default=None, help="Target camera FPS")
    parser.add_argument("--port",     type=str,   default=None, help="Arduino serial port")
    parser.add_argument("--baud",     type=int,   default=None, help="Serial baud rate")
    parser.add_argument("--latency",  type=float, default=None, help="Latency compensation (seconds)")
    parser.add_argument("--pull",     type=int,   default=None, help="Pull PWM strength 0-255")
    parser.add_argument("--push",     type=int,   default=None, help="Push PWM strength 0-255")
    parser.add_argument("--dead",     type=int,   default=None, help="Dead-band half-width (pixels)")
    parser.add_argument("--hysteresis", type=int, default=None, help="Hysteresis zone (pixels)")
    parser.add_argument("--osc-port", type=int,   default=None, help="OSC listen port")
    parser.add_argument("--center",   type=int,   default=None, help="Override centre X pixel")
    parser.add_argument("--calibrate",action="store_true",      help="Run colour calibration first")
    parser.add_argument("--autostart",action="store_true",      help="Start perpetual motion immediately")
    parser.add_argument("--no-gui",   action="store_true",      help="Suppress OpenCV preview window")
    parser.add_argument("--reset-config", action="store_true",  help="Reset to default config (ignore saved settings)")
    args = parser.parse_args()

    # Load saved config (or defaults if no config file exists)
    if args.reset_config:
        log.info("Resetting to default configuration...")
        cfg = Config()
        cfg.save()  # Save defaults
    else:
        cfg = Config.load()
    
    # Apply command-line overrides (these take precedence over saved config)
    if args.camera is not None:
        cfg.camera_index = args.camera
    if args.width is not None:
        cfg.frame_width = args.width
    if args.height is not None:
        cfg.frame_height = args.height
    if args.fps is not None:
        cfg.target_fps = args.fps
    if args.port is not None:
        cfg.serial_port = args.port
    if args.baud is not None:
        cfg.serial_baud = args.baud
    if args.latency is not None:
        cfg.latency_s = args.latency
    if args.pull is not None:
        cfg.pull_strength = args.pull
    if args.push is not None:
        cfg.push_strength = args.push
    if args.dead is not None:
        cfg.dead_band_px = args.dead
    if args.hysteresis is not None:
        cfg.hysteresis_px = args.hysteresis
    if args.osc_port is not None:
        cfg.osc_listen_port = args.osc_port
    if args.center is not None:
        cfg.center_x_px = args.center

    # --- Hardware init ---
    tracker = PendulumTracker(cfg)
    arduino = ArduinoInterface(cfg.serial_port, cfg.serial_baud)
    controller = PendulumController(cfg, arduino)

    # Warn if resolution doesn't match common defaults and center isn't calibrated
    if not args.calibrate and cfg.center_x_px is None:
        if cfg.frame_width != 1280 or cfg.frame_height != 720:
            log.warning("Resolution changed but center not calibrated!")
            log.warning("Run with --calibrate to set center for this resolution")

    if args.calibrate:
        run_calibration(tracker, cfg)

    if args.autostart:
        controller.start()

    # --- OSC server (background thread) ---
    osc_srv = build_osc_server(cfg, controller)
    osc_thread = threading.Thread(target=osc_srv.serve_forever, daemon=True)
    osc_thread.start()

    log.info("Running. OSC commands on port %d.", cfg.osc_listen_port)
    log.info("Keyboard: Q=quit  V=toggle video  C=calibrate  S=start  R=continue  B=brake")
    log.info("          1=push  2=pull  3=off")

    if not args.no_gui:
        cv2.namedWindow("Pendulum", cv2.WINDOW_NORMAL)

    try:
        while True:
            t_frame = time.monotonic()
            frame, pos = tracker.read_frame()

            state = controller.update(t_frame, pos)

            if not args.no_gui and frame is not None and controller._gui_visible:
                pred_x = controller.predictor.predict(cfg.latency_s)
                vel    = controller.predictor.velocity()
                overlay = draw_overlay(frame, pos,
                                       tracker.center_x, state, cfg,
                                       vel, pred_x)
                cv2.imshow("Pendulum", overlay)

                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                elif key == ord("v"):
                    controller.toggle_gui()
                elif key == ord("c"):
                    run_calibration(tracker, cfg)
                elif key == ord("s"):
                    controller.start()
                elif key == ord("r"):
                    controller.continue_motion()
                elif key == ord("b"):
                    controller.brake()
                elif key == ord("1"):
                    controller.set_force("PUSH")
                elif key == ord("2"):
                    controller.set_force("PULL")
                elif key == ord("3"):
                    controller.set_force("OFF")
            elif not args.no_gui and not controller._gui_visible:
                # GUI is hidden, but still need to handle quit key
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                elif key == ord("v"):
                    controller.toggle_gui()

    except KeyboardInterrupt:
        log.info("Interrupted.")
    finally:
        controller.stop()
        arduino.close()
        tracker.release()
        osc_srv.shutdown()
        if not args.no_gui:
            cv2.destroyAllWindows()
        log.info("Shutdown complete.")


if __name__ == "__main__":
    main()
