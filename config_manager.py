#!/usr/bin/env python3
"""
Pendulum Configuration Manager
===============================
View and edit saved pendulum configuration without running the full system.

Usage:
    python config_manager.py view             # Show current settings
    python config_manager.py reset            # Reset to defaults
    python config_manager.py set <key> <value>  # Change a setting
    python config_manager.py get <key>        # Get a setting value

Examples:
    python config_manager.py view
    python config_manager.py set latency_s 0.06
    python config_manager.py set serial_port /dev/cu.usbserial-1220
    python config_manager.py set pull_strength 255
    python config_manager.py get center_x_px
"""

import json
import sys
from pathlib import Path

# Config file in same directory as script
CONFIG_FILE = Path(__file__).parent / "pendulum_config.json"

def load_config():
    """Load configuration from file."""
    if not CONFIG_FILE.exists():
        print(f"No config file found at {CONFIG_FILE}")
        print("Run the pendulum controller with --calibrate to create one.")
        return None
    
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def save_config(cfg):
    """Save configuration to file."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)
    print(f"Configuration saved to {CONFIG_FILE}")

def view_config():
    """Display all configuration settings."""
    cfg = load_config()
    if cfg is None:
        return
    
    print("\n" + "="*60)
    print("PENDULUM CONFIGURATION")
    print("="*60)
    print(f"Config file: {CONFIG_FILE}\n")
    
    categories = {
        "Camera Settings": ["camera_index", "frame_width", "frame_height", "target_fps"],
        "Color Tracking": ["hsv_lower", "hsv_upper", "min_blob_area"],
        "Geometry": ["center_x_px", "dead_band_px", "hysteresis_px"],
        "Arduino/Serial": ["serial_port", "serial_baud"],
        "Electromagnet": ["pull_strength", "push_strength"],
        "Latency": ["latency_s", "history_len"],
        "OSC": ["osc_listen_ip", "osc_listen_port", "osc_feedback_ip", "osc_feedback_port"]
    }
    
    for category, keys in categories.items():
        print(f"\n{category}:")
        print("-" * 40)
        for key in keys:
            if key in cfg:
                value = cfg[key]
                if isinstance(value, list) and len(value) == 3:
                    # Format HSV arrays nicely
                    print(f"  {key:20s} : [{value[0]:3d}, {value[1]:3d}, {value[2]:3d}]")
                elif isinstance(value, tuple) or isinstance(value, list):
                    print(f"  {key:20s} : {value}")
                else:
                    print(f"  {key:20s} : {value}")
    print("\n" + "="*60 + "\n")

def get_value(key):
    """Get a specific configuration value."""
    cfg = load_config()
    if cfg is None:
        return
    
    if key not in cfg:
        print(f"Error: Key '{key}' not found in configuration")
        print(f"Available keys: {', '.join(sorted(cfg.keys()))}")
        return
    
    value = cfg[key]
    print(f"{key} = {value}")

def set_value(key, value):
    """Set a specific configuration value."""
    cfg = load_config()
    if cfg is None:
        return
    
    if key not in cfg:
        print(f"Error: Key '{key}' not found in configuration")
        print(f"Available keys: {', '.join(sorted(cfg.keys()))}")
        return
    
    # Try to convert value to the correct type
    old_value = cfg[key]
    
    try:
        if isinstance(old_value, bool):
            new_value = value.lower() in ('true', '1', 'yes')
        elif isinstance(old_value, int):
            new_value = int(value)
        elif isinstance(old_value, float):
            new_value = float(value)
        elif isinstance(old_value, list):
            # Assume comma-separated values
            new_value = [int(x.strip()) for x in value.split(',')]
        elif old_value is None:
            # Try int first, then float, then string
            try:
                new_value = int(value)
            except ValueError:
                try:
                    new_value = float(value)
                except ValueError:
                    new_value = value
        else:
            new_value = value
        
        cfg[key] = new_value
        save_config(cfg)
        print(f"✓ {key} changed from {old_value} to {new_value}")
        
    except ValueError as e:
        print(f"Error: Could not convert '{value}' to type {type(old_value).__name__}")
        print(f"Original error: {e}")

def reset_config():
    """Reset to default configuration."""
    defaults = {
        "camera_index": 0,
        "frame_width": 1280,
        "frame_height": 720,
        "target_fps": 60,
        "hsv_lower": [5, 150, 150],
        "hsv_upper": [25, 255, 255],
        "min_blob_area": 100,
        "center_x_px": None,
        "dead_band_px": 30,
        "hysteresis_px": 50,
        "serial_port": None,
        "serial_baud": 115200,
        "pull_strength": 255,
        "push_strength": 255,
        "latency_s": 0.09,
        "history_len": 12,
        "osc_listen_ip": "0.0.0.0",
        "osc_listen_port": 9000,
        "osc_feedback_ip": "127.0.0.1",
        "osc_feedback_port": 9001
    }
    
    save_config(defaults)
    print("✓ Configuration reset to defaults")

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "view":
        view_config()
    
    elif command == "reset":
        response = input("Reset configuration to defaults? (y/n): ")
        if response.lower() == 'y':
            reset_config()
        else:
            print("Cancelled")
    
    elif command == "get":
        if len(sys.argv) < 3:
            print("Usage: config_manager.py get <key>")
            sys.exit(1)
        get_value(sys.argv[2])
    
    elif command == "set":
        if len(sys.argv) < 4:
            print("Usage: config_manager.py set <key> <value>")
            sys.exit(1)
        set_value(sys.argv[2], sys.argv[3])
    
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)

if __name__ == "__main__":
    main()
