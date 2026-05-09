#!/usr/bin/env python3
"""
Galaxy Buds Spatial Head Tracker
"""

from buds.connection import GalaxyBudsConnection, auto_detect_buds, HAS_IOBLUETOOTH
from buds.visualization import run_terminal_mode, run_visualization
from buds.mouse import run_mouse_mode


def main():
    print("=" * 45)
    print("  Galaxy Buds Spatial Head Tracker")
    print("=" * 45)
    print()
    
    if not HAS_IOBLUETOOTH:
        print("Error: Apple IOBluetooth backend not available")
        print("Windows support is now focused on cursor control only; Buds Bluetooth transport still requires macOS IOBluetooth")
        return
    
    # Auto-detect Galaxy Buds
    result = auto_detect_buds()
    
    if not result:
        addr = input("\nEnter device address manually: ").strip()
        if not addr:
            print("No address provided. Exiting.")
            return
    else:
        name, addr = result
    
    # Connect
    conn = GalaxyBudsConnection(addr, channel=27)
    
    if not conn.connect():
        return
    
    # Mode selection
    print("\nSelect mode:")
    print("  1. Terminal (text output)")
    print("  2. Visualization (3D + Webcam)")
    print("  3. Mouse Control")
    print("  4. Data Logging (CSV)")
    
    mode = input("\nMode [2]: ").strip()
    if not mode:
        mode = "2"
    
    conn.run_loop(0.3)
    conn.attach_spatial_sensor()
    conn.run_loop(0.3)
    
    try:
        if mode == "1":
            from buds.visualization import run_terminal_mode
            run_terminal_mode(conn)
        elif mode == "3":
            from buds.mouse import run_mouse_mode
            run_mouse_mode(conn)
        elif mode == "4":
            from buds.logger import run_logging_mode
            run_logging_mode(conn)
        else:
            from buds.visualization import run_visualization
            run_visualization(conn)
    except KeyboardInterrupt:
        print("\n\nStopping...")
    finally:
        conn.detach_spatial_sensor()
        conn.run_loop(0.2)
        conn.disconnect()
    
    print("Done.")


if __name__ == "__main__":
    main()
