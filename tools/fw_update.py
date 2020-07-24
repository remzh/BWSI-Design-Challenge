#!/usr/bin/env python
"""
Firmware Updater Tool

A frame consists of two sections:
1. Two bytes for the length of the data section
2. A data section of length defined in the length section

[ 0x02 ]  [ variable ]
--------------------
| Length | Data... |
--------------------

In our case, the data is from one line of the Intel Hex formated .hex file

We write a frame to the bootloader, then wait for it to respond with an
OK message so we can write the next frame. The OK message in this case is
just a zero
"""

import argparse
import struct
import time

from serial import Serial

RESP_OK = b'\x00'
RESP_ERR = b'\x01'
FRAME_SIZE = 16
PACKET_SIZE = 1064

error_counter = 0

def send_metadata(ser, metadata, nonce, tag, debug=False):
    version, size = struct.unpack_from('<HH', metadata)
    print(f'Version: {version}\nSize: {size} bytes\n')

    # Handshake for update
    ser.write(b'U')
    
    print('Waiting for bootloader to enter update mode...')
    while ser.read(1).decode() != 'U':
        pass

    # Send the metadata to bootloader.
    if debug:
        print(metadata)

    ser.write(metadata)
    ser.write(nonce)
    ser.write(tag)

    # Wait for an OK from the bootloader.
    resp = ser.read()
    if resp != RESP_OK:
        raise RuntimeError("ERROR: Bootloader responded with {}".format(repr(resp)))

def send_frame(ser, frame, debug=False):
    ser.write(frame)  # Write the frame...

    if debug:
        print(frame)

    resp = ser.read()  # Wait for an OK from the bootloader

    time.sleep(0.1)

    if resp != RESP_OK:
        raise RuntimeError("ERROR: Bootloader responded with {}".format(repr(resp)))

    if debug:
        print("Resp: {}".format(ord(resp)))
        
    #If the bootloader receives a one byte, resend the frame and increment error counter
    if resp == RESP_ERR:
        error_counter += 1
        send_frame(ser, frame, debug=debug)
        

def main(ser, infile, debug):
    # Open serial port. Set baudrate to 115200. Set timeout to 2 seconds.
    with open(infile, 'rb') as fp:
        firmware_blob = fp.read()
    
    error_counter = 0
    
    fw_size  = struct.unpack('<H', firmware_blob[2 : 4])[0]
    chunk_size = struct.unpack('<H', firmware_blob[6 : 8])[0]
    num_chunks = int(fw_size / chunk_size) # maybe
    
    for i in range(num_chunks):
      
        metadata = firmware_blob[i * chunk_size : i * chunk_size + 8]
        nonce = firmware_blob[i * chunk_size + 8 : i * chunk_size + 24]
        tag = firmware_blob[i * chunk_size + 24 : i * chunk_size + 40]
        
        send_metadata(ser, metadata, nonce, tag, debug=debug)
 
        fw_size  = struct.unpack('<H', firmware_blob[i * chunk_size + 2 : i * chunk_size + 4])[0]
        chunk_size = struct.unpack('<H', firmware_blob[i * chunk_size + 6 : i * chunk_size + 8])[0]
        packet_index = struct.unpack('<H', firmware_blob[i * chunk_size + 4 : i * chunk_size + 6])[0]
        
        fw_start = PACKET_SIZE * packet_index + 40
        firmware = firmware_blob[fw_start : fw_start + chunk_size]
  
        for idx, frame_start in enumerate(range(0, len(firmware), FRAME_SIZE)):
            data = firmware[frame_start: frame_start + FRAME_SIZE]

            # Get length of data.
            length = len(data)
            frame_fmt = '<{}s'.format(length)

            # Construct frame.
            frame = struct.pack(frame_fmt, data)

            #If there are more than ten errors in a row, then restart the update.
            if error_counter > 10:
                print("Terminating, restarting update...")
                return

            if debug:
                print("Writing frame {} ({} bytes)...".format(idx, len(frame)))

            send_frame(ser, frame, debug=debug)

    print("Done writing firmware.")

    # Send a zero length payload to tell the bootlader to finish writing its page.
    ser.write(struct.pack('<H', 0x0000))

    return ser


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Firmware Update Tool')

    parser.add_argument("--port", help="Serial port to send update over.",
                        required=True)
    parser.add_argument("--firmware", help="Path to firmware image to load.",
                        required=True)
    parser.add_argument("--debug", help="Enable debugging messages.",
                        action='store_true')
    args = parser.parse_args()

    print('Opening serial port...')
    ser = Serial(args.port, baudrate=115200, timeout=2)
    main(ser=ser, infile=args.firmware, debug=args.debug)
