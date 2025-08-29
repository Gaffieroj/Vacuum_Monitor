from dataclasses import dataclass
import asyncio
import logging
import socket
import sys
import os 
import serial_asyncio
from package_handler_async import PackageHandler

@dataclass
class ChannelConfig:
    id_high: int
    id_low: int
    channel_id: int
    channel_name: str
    unit: str
    multiplier: float

class ParameterRequestManager:
    """Manages parameter requests and data transmission over a serial connection and UDP."""

    def __init__(self, port, baudrate):
        self.port = port
        self.baudrate = baudrate
        self.handler = None
        self.data = []
        self.channels = [
            ChannelConfig(0x03, 0x42, 834, "Power SW version", "", 1),
            ChannelConfig(0x00, 0x01, 1, "Output Freq", "Hz", 0.01),
            ChannelConfig(0x00, 0x19, 25, "Freq Ref.", "Hz", 0.01),
            ChannelConfig(0x00, 0x02, 2, "Motor shaft speed", "rpm", 1),
            ChannelConfig(0x00, 0x03, 3, "Motor Current", "A", 0.01),
            ChannelConfig(0x00, 0x04, 4, "Motor Torque", "%", 0.1),
            ChannelConfig(0x00, 0x05, 5, "Motor Power", "%", 0.1),
            ChannelConfig(0x00, 0x06, 6, "Motor Voltage", "V", 0.1),
            ChannelConfig(0x00, 0x09, 9, "Motor Temperature", "°C", 1),
            ChannelConfig(0x00, 0x07, 7, "DC-link Voltage", "V", 1),
            ChannelConfig(0x00, 0x08, 8, "Unit Temperature", "°C", 1),
            ChannelConfig(0x07, 0x21, 1825, "Board Temp", "°C", 1),
            ChannelConfig(0x07, 0x6B, 1899, "Service counter", "h", 1),
            ChannelConfig(0x00, 0x0E, 14, "Reservoir Vacuum Level", "%", 1),
            ChannelConfig(0x03, 0x3B, 827, "MWh Counter", "MW", 0.001),
            ChannelConfig(0x03, 0x3C, 828, "Power On Time:Days", "Days", 1),
            ChannelConfig(0x03, 0x3D, 829, "Power On Time:Hours", "Hours", 1),
            ChannelConfig(0x03, 0x48, 840, "Unit Run Time:Days", "Days", 1),
            ChannelConfig(0x03, 0x49, 841, "Unit Run Time:Hours", "Hours", 1)
        ]
        self.messages = [(c.id_high, c.id_low, 0x00, 0x01) for c in self.channels]

    async def send_parameter_requests(self):
        """
        Sends requests for all configured channels.
        Returns a boolean indicating if a counter sync error was detected.
        """
        self.data.clear()
        sync_error_detected = False
        
        for i, (id_high, id_low, payload_high, payload_low) in enumerate(self.messages, 1):
            self.handler.send_msg(id_high, id_low, payload_high, payload_low)
            try:
                received_msg = await asyncio.wait_for(self.handler.message_queue.get(), timeout=5)
                
                # --- NEW: Check for counter sync error specifically ---
                if not received_msg.get('is_valid_type', False):
                    sync_error_detected = True

                received_bytes = received_msg['full_message']
                # The main validation remains lenient on the counter to finish the loop
                is_valid = (len(received_bytes) >= 6 and
                            received_bytes[0:2] == self.handler.ack and
                            received_bytes[2:4] == self.handler.header and
                            received_bytes[4] in range(0xC4, 0xC8) and
                            self.handler.msg_done in received_bytes[5:-1])

                logging.info(f"Received reply {i}: {received_bytes.hex().upper()}")
                self.handler.send_ack()
                if is_valid:
                  payload_int = int.from_bytes(received_msg['payload'], byteorder='big')
                  channel = next((c for c in self.channels if c.id_high == id_high and c.id_low == id_low), None)
                  payload_value = payload_int * (channel.multiplier if channel else 1)
                  self.data.append({'payload': payload_value})
                else:
                    logging.warning(f"Reply {i} invalid: {received_msg}")
                    break
            except asyncio.TimeoutError:
                logging.error(f"Timeout waiting for reply {i}. Aborting polling cycle.")
                break
            except KeyError as e:
                logging.error(f"Key error in reply {i}: {e}. Aborting polling cycle.")
                break
        
        return sync_error_detected

    async def run(self):
        """Runs the parameter request process in a continuous loop with robust error recovery."""
        loop = asyncio.get_running_loop()

        while True:
            transport = None
            try:
                logging.info("Attempting to establish serial connection...")
                transport, self.handler = await serial_asyncio.create_serial_connection(
                    loop, lambda: PackageHandler(), self.port, baudrate=self.baudrate
                )

                if not await self.handler.handshake():
                    raise ConnectionAbortedError("Handshake failed")

                logging.info("Handshake successful. Starting continuous data polling.")

                while True:
                    self.handler.buffer.clear()
                    self.handler.message_queue = asyncio.Queue()

                    sync_error = await self.send_parameter_requests()

                    # --- NEW: Check the sync error flag after the poll is complete ---
                    if sync_error:
                        logging.warning("Counter sync error detected in cycle. Discarding data and restarting handshake.")
                        break

                    if len(self.data) < 19:
                        logging.warning("Communication failed: Incomplete data set received. Restarting handshake.")
                        break

                    payloads = [str(int(row['payload'])) for row in self.data]

                    if payloads[0] != "8":
                        logging.warning(f"Invalid data: First payload is '{payloads[0]}', expected '8'. Restarting handshake.")
                        break

                    message = "VAC;PUMP1;" + ";".join(payloads)
                    logging.info(f"Successfully polled valid data packet: {message}")
                    
                    file_path = r"C:\temp\UDPTest\UDP1.txt"
                    try:
                        os.makedirs(os.path.dirname(file_path), exist_ok=True)
                        with open(file_path, 'a', encoding='utf-8') as f:
                            f.write(message + "\n")
                        logging.debug(f"Appended message to {file_path}")
                    except OSError as e:
                        logging.error(f"Failed to write to file: {e}")

            except (serial_asyncio.serial.SerialException, OSError, ConnectionAbortedError) as e:
                logging.error(f"Connection error: {e}. Retrying...")
            except Exception as e:
                logging.critical(f"An unexpected error occurred: {e}. Retrying...")
            finally:
                if transport:
                    logging.info("Closing serial port to ensure it's released.")
                    transport.close()
                transport = None
                self.handler = None
                await asyncio.sleep(10)