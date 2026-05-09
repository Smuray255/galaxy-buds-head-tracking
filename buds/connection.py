"""Bluetooth connection to Galaxy Buds (macOS native)."""

import platform
import struct
import time
from typing import Optional, Callable, List, Tuple

objc = None

from .protocol import MsgIds, MsgConstants, SpatialAudioControl
from .message import SppMessage
from .quaternion import Quaternion, parse_grv_data

# Import macOS IOBluetooth framework only on Darwin
if platform.system() == "Darwin":
    try:
        import objc
        from Foundation import NSObject, NSRunLoop, NSDate, NSDefaultRunLoopMode
        from IOBluetooth import IOBluetoothDevice
        HAS_IOBLUETOOTH = True
    except ImportError:
        HAS_IOBLUETOOTH = False
else:
    HAS_IOBLUETOOTH = False


try:
    import serial
    HAS_PYSERIAL = True
except ImportError:
    HAS_PYSERIAL = False


def find_galaxy_buds() -> List[Tuple[str, str]]:
    """
    Find paired Galaxy Buds devices.
    Returns list of (name, address) tuples.
    """
    if not HAS_IOBLUETOOTH:
        return []
    
    buds_found = []
    
    try:
        # Get all paired devices
        paired = IOBluetoothDevice.pairedDevices()
        if not paired:
            return []
        
        for device in paired:
            name = device.name()
            address = device.addressString()
            
            if name and address:
                # Check if it's Galaxy Buds
                name_lower = name.lower()
                if 'galaxy buds' in name_lower or 'buds' in name_lower:
                    buds_found.append((name, address))
    except Exception as e:
        print(f"Error scanning devices: {e}")
    
    return buds_found


def auto_detect_buds() -> Optional[Tuple[str, str]]:
    """
    Auto-detect Galaxy Buds and return (name, address).
    Returns None if not found.
    """
    print("Scanning for Galaxy Buds...")
    buds = find_galaxy_buds()
    
    if not buds:
        print("No Galaxy Buds found in paired devices.")
        return None
    
    if len(buds) == 1:
        name, addr = buds[0]
        print(f"Found: {name} ({addr})")
        return (name, addr)
    
    # Multiple buds found, let user choose
    print(f"\nFound {len(buds)} Galaxy Buds devices:")
    for i, (name, addr) in enumerate(buds, 1):
        print(f"  {i}. {name} ({addr})")
    
    try:
        choice = input(f"\nSelect device [1-{len(buds)}]: ").strip()
        idx = int(choice) - 1 if choice else 0
        if 0 <= idx < len(buds):
            return buds[idx]
    except:
        pass
    
    return buds[0]


if HAS_IOBLUETOOTH:
    class RFCOMMChannelDelegate(NSObject):
        """Delegate for RFCOMM channel events."""
        
        def init(self):
            self = objc.super(RFCOMMChannelDelegate, self).init()
            if self is None:
                return None
            self.received_data = b''
            self.connected = False
            self.channel = None
            self.on_data = None
            return self
        
        def rfcommChannelOpenComplete_status_(self, channel, status):
            if status == 0:
                print("Connected!")
                self.connected = True
                self.channel = channel
            else:
                pass  # Silently fail, we'll try next channel
        
        def rfcommChannelClosed_(self, channel):
            self.connected = False
        
        def rfcommChannelData_data_length_(self, channel, data, length):
            raw_bytes = bytes(data)
            self.received_data += raw_bytes
            if self.on_data:
                self.on_data(raw_bytes)
        
        def rfcommChannelWriteComplete_refcon_status_(self, channel, refcon, status):
            pass


class GalaxyBudsConnection:
    """Manages RFCOMM connection using IOBluetooth (macOS)."""
    
    # Standard UUID for Serial Port Profile (SPP)
    SPP_UUID = "00001101-0000-1000-8000-00805F9B34FB"
     
    # Service ID for Spatial Audio endpoint
    SPATIAL_SENSOR_UUID = "DA1D3D7D-2E5F-4A9E-9F95-C94E03493E44"
    
    def __init__(self, device_address: str, channel: int = 27):
        self.device_address = device_address
        self.channel = channel
        self.device = None
        self.rfcomm_channel = None
        self.delegate = None
        self.serial_conn = None
        self.backend = "iobluetooth" if HAS_IOBLUETOOTH else "serial"
        self.connected = False
        self._buffer = b''
        self.latest_quaternion: Optional[Quaternion] = None
        self.on_quaternion: Optional[Callable[[Quaternion], None]] = None
    
    def connect(self) -> bool:
        """Connect to device."""
        if HAS_IOBLUETOOTH:
            self.backend = "iobluetooth"
        else:
            self.backend = "serial"

        if self.backend == "serial":
            if not HAS_PYSERIAL:
                print("pyserial not available. Install: pip install pyserial")
                return False
            try:
                self.serial_conn = serial.Serial(self.device_address, baudrate=115200, timeout=0)
                self.connected = True
                print(f"Connected over serial RFCOMM: {self.device_address}")
                return True
            except Exception as e:
                print(f"Serial connect failed ({self.device_address}): {e}")
                return False

        # Search for Spatial Audio service record
        print(f"Scanning services for {self.device_address}...")
        
        self.device = IOBluetoothDevice.deviceWithAddressString_(self.device_address)
        if not self.device:
            print(f"Device not found: {self.device_address}")
            return False
        
        self.delegate = RFCOMMChannelDelegate.alloc().init()
        self.delegate.on_data = self._on_data_received
        
        # Try primary channel first
        result, channel = self.device.openRFCOMMChannelSync_withChannelID_delegate_(
            None, self.channel, self.delegate
        )
        
        if result == 0:
            self.rfcomm_channel = channel
            self.delegate.channel = channel
            self.connected = True
            return True
        
        # Try common channels
        return self._try_channels()
    
    def _try_channels(self) -> bool:
        """Try common RFCOMM channels."""
        channels = [27, 3, 4, 5, 6, 7, 8, 9, 10, 1, 2]
        
        for ch in channels:
            if ch == self.channel:
                continue  # Already tried
            
            try:
                result, channel = self.device.openRFCOMMChannelSync_withChannelID_delegate_(
                    None, ch, self.delegate
                )
                if result == 0:
                    self.rfcomm_channel = channel
                    self.connected = True
                    self.channel = ch
                    print(f"Connected on channel {ch}")
                    return True
            except:
                continue
        
        print("Could not connect. Make sure Buds are connected in Bluetooth settings.")
        return False
    
    def _on_data_received(self, data: bytes):
        self._buffer += data
        self._process_buffer()
    
    def _process_buffer(self):
        while len(self._buffer) >= 6:
            som_pos = self._buffer.find(bytes([MsgConstants.SOM]))
            if som_pos == -1:
                self._buffer = b''
                break
            
            if som_pos > 0:
                self._buffer = self._buffer[som_pos:]
            
            if len(self._buffer) < 3:
                break
            
            header = struct.unpack('<H', self._buffer[1:3])[0]
            size = header & 0x3FF
            total_size = 1 + 2 + size + 1
            
            if len(self._buffer) < total_size:
                break
            
            packet = self._buffer[:total_size]
            self._buffer = self._buffer[total_size:]
            
            msg = SppMessage.decode(packet)
            if msg:
                self._handle_message(msg)
    
    def _handle_message(self, msg: SppMessage):
        if msg.msg_id == MsgIds.SPATIAL_AUDIO_DATA:
            quat = parse_grv_data(msg.payload)
            if quat:
                self.latest_quaternion = quat
                if self.on_quaternion:
                    self.on_quaternion(quat)
        
        elif msg.msg_id == MsgIds.SPATIAL_AUDIO_CONTROL:
            if len(msg.payload) > 0:
                result = msg.payload[0]
                if result == SpatialAudioControl.ATTACH_SUCCESS:
                    print("Spatial sensor ready")
    
    def send(self, data: bytes) -> bool:
        if not self.connected:
            return False

        if self.backend == "serial":
            if not self.serial_conn:
                return False
            try:
                self.serial_conn.write(data)
                return True
            except Exception:
                return False

        if not self.rfcomm_channel:
            return False
        try:
            result = self.rfcomm_channel.writeSync_length_(data, len(data))
            return result == 0
        except:
            return False
    
    def send_message(self, msg_id: int, payload: bytes = b''):
        msg = SppMessage(msg_id=msg_id, payload=payload)
        return self.send(msg.encode())
    
    def attach_spatial_sensor(self):
        """Send command to enable the IMU sensor stream."""
        # Payload structure derived from traffic sniffing
        self.send_message(MsgIds.SET_SPATIAL_AUDIO, bytes([1]))
        self.run_loop(0.2)
        self.send_message(MsgIds.SPATIAL_AUDIO_CONTROL, bytes([SpatialAudioControl.ATTACH]))
    
    def detach_spatial_sensor(self):
        """Disable spatial audio."""
        self.send_message(MsgIds.SPATIAL_AUDIO_CONTROL, bytes([SpatialAudioControl.DETACH]))
        self.run_loop(0.2)
        self.send_message(MsgIds.SET_SPATIAL_AUDIO, bytes([0]))
    
    def send_keep_alive(self):
        """Send keep-alive message."""
        self.send_message(MsgIds.SPATIAL_AUDIO_CONTROL, bytes([SpatialAudioControl.KEEP_ALIVE]))
    
    def run_loop(self, duration: float):
        """Run the platform event loop to process events."""
        end_time = time.time() + duration

        if self.backend == "serial":
            while time.time() < end_time:
                if self.serial_conn:
                    try:
                        chunk = self.serial_conn.read(4096)
                        if chunk:
                            self._on_data_received(chunk)
                    except Exception:
                        pass
                time.sleep(0.01)
            return

        while time.time() < end_time:
            NSRunLoop.currentRunLoop().runMode_beforeDate_(
                NSDefaultRunLoopMode,
                NSDate.dateWithTimeIntervalSinceNow_(0.01)
            )
    
    def disconnect(self):
        """Disconnect from device."""
        if self.serial_conn:
            try:
                self.serial_conn.close()
            except Exception:
                pass
            self.serial_conn = None

        if self.rfcomm_channel:
            try:
                self.rfcomm_channel.closeChannel()
            except:
                pass
        self.connected = False
