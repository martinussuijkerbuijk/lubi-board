"""
OSC Remote Control – Pendulum System
======================================
Send OSC messages to the running pendulum_controller.py process.
Run this from a second terminal to test commands without needing
an external OSC tool like TouchOSC or Max/MSP.

Usage:
  python osc_remote.py start             # Start with startup sequence
  python osc_remote.py continue          # Continue without startup
  python osc_remote.py stop              # Stop
  python osc_remote.py brake             # Brake to center
  python osc_remote.py push [strength]   # Direct PUSH (optional strength 0-255)
  python osc_remote.py pull [strength]   # Direct PULL (optional strength 0-255)
  python osc_remote.py off               # Turn off magnet
  python osc_remote.py gui show          # Show video feed
  python osc_remote.py gui hide          # Hide video feed (saves CPU)
  python osc_remote.py gui toggle        # Toggle video feed
  python osc_remote.py latency <seconds> # Set latency compensation
  python osc_remote.py strength <pull> <push>  # Set strengths

Requires: pip install python-osc
"""

import sys
from pythonosc.udp_client import SimpleUDPClient

TARGET_IP   = "127.0.0.1"
TARGET_PORT = 9000

client = SimpleUDPClient(TARGET_IP, TARGET_PORT)

def usage():
    print(__doc__)
    sys.exit(1)

def main():
    if len(sys.argv) < 2:
        usage()

    cmd = sys.argv[1].lower()

    if cmd == "start":
        client.send_message("/pendulum/start", [])
        print("Sent: /pendulum/start (with startup sequence)")

    elif cmd == "continue":
        client.send_message("/pendulum/continue", [])
        print("Sent: /pendulum/continue (resume perpetual motion)")

    elif cmd == "stop":
        client.send_message("/pendulum/stop", [])
        print("Sent: /pendulum/stop")

    elif cmd == "brake":
        client.send_message("/pendulum/brake", [])
        print("Sent: /pendulum/brake (catch to center)")

    elif cmd == "push":
        strength = int(sys.argv[2]) if len(sys.argv) > 2 else None
        if strength:
            client.send_message("/pendulum/push", [strength])
            print(f"Sent: /pendulum/push {strength}")
        else:
            client.send_message("/pendulum/push", [])
            print("Sent: /pendulum/push (default strength)")

    elif cmd == "pull":
        strength = int(sys.argv[2]) if len(sys.argv) > 2 else None
        if strength:
            client.send_message("/pendulum/pull", [strength])
            print(f"Sent: /pendulum/pull {strength}")
        else:
            client.send_message("/pendulum/pull", [])
            print("Sent: /pendulum/pull (default strength)")

    elif cmd == "off":
        client.send_message("/pendulum/off", [])
        print("Sent: /pendulum/off")

    elif cmd == "gui":
        if len(sys.argv) < 3:
            print("Usage: osc_remote.py gui [show|hide|toggle]"); sys.exit(1)
        subcmd = sys.argv[2].lower()
        if subcmd == "show":
            client.send_message("/pendulum/gui/show", [])
            print("Sent: /pendulum/gui/show (enable video feed)")
        elif subcmd == "hide":
            client.send_message("/pendulum/gui/hide", [])
            print("Sent: /pendulum/gui/hide (disable video feed, saves CPU)")
        elif subcmd == "toggle":
            client.send_message("/pendulum/gui/toggle", [])
            print("Sent: /pendulum/gui/toggle")
        else:
            print(f"Unknown gui command: {subcmd}"); sys.exit(1)

    elif cmd == "disrupt":
        pol = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        dur = float(sys.argv[3]) if len(sys.argv) > 3 else 0.3
        client.send_message("/pendulum/disrupt", [pol, dur])
        print(f"DEPRECATED: Use 'push' or 'pull' instead")
        print(f"Sent: /pendulum/disrupt polarity={pol:+d} duration={dur}s")

    elif cmd == "latency":
        if len(sys.argv) < 3:
            print("Usage: osc_remote.py latency <seconds>"); sys.exit(1)
        lat = float(sys.argv[2])
        client.send_message("/pendulum/latency", [lat])
        print(f"Sent: /pendulum/latency {lat}s")

    elif cmd == "strength":
        if len(sys.argv) < 4:
            print("Usage: osc_remote.py strength <pull 0-255> <push 0-255>"); sys.exit(1)
        pull = int(sys.argv[2])
        push = int(sys.argv[3])
        client.send_message("/pendulum/strength", [pull, push])
        print(f"Sent: /pendulum/strength pull={pull} push={push}")

    else:
        usage()

if __name__ == "__main__":
    main()
