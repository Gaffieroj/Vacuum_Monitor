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
        self.data.clear()
        
        for i, (id_high, id_low, payload_high, payload_low) in enumerate(self.messages, 1):
            self.handler.send_msg(id_high, id_low, payload_high, payload_low)
            try:
                received_msg = await asyncio.wait_for(self.handler.message_queue.get(), timeout=5)
                received_bytes = received_msg['full_message']
                is_valid = (len(received_bytes) >= 6 and
                            received_bytes[0:2] == self.handler.ack and
                            received_bytes[2:4] == self.handler.header and
                            received_bytes[4] in range(0xC4, 0xC8) and
                            self.handler.msg_done in received_bytes[5:-1] and
                            len(received_bytes) >= received_bytes.find(self.handler.msg_done) + len(self.handler.msg_done) + 1 and
                            received_msg.get('is_valid_type', False))
                logging.info(f"Received reply {i}: {received_bytes.hex().upper()}")
                self.handler.send_ack()
                
                # --- RESTORED LOGIC BLOCK ---
                if is_valid:
                    payload_int = int.from_bytes(received_msg['payload'], byteorder='big')
                    channel = next((c for c in self.channels if c.id_high == id_high and c.id_low == id_low), None)
                    channel_id = channel.channel_id if channel else 0
                    channel_name = channel.channel_name if channel else "Unknown"
                    unit = channel.unit if channel else "N/A"
                    multiplier = channel.multiplier if channel else 1
                    payload_value = payload_int * multiplier
                
                    # For UDP message: Reservoir Vacuum Level is -1000 + percentage
                    if channel_id == 14:
                        udp_payload = int(-1000 + payload_value)
                        payload_formatted = f"{udp_payload}"
                        unit = "mbar"
                    elif multiplier < 1:
                        payload_formatted = f"{payload_value:.2f}"
                        udp_payload = payload_formatted
                    else:
                        payload_formatted = int(payload_value)
                        udp_payload = payload_formatted
                
                    logging.info(f"Reply {i} valid, channel_id: {channel_id}, channel: {channel_name}, payload: {payload_formatted}, unit: {unit}")
                    self.data.append({
                        'channel_id': channel_id,
                        'channel_name': channel_name,
                        'payload': udp_payload,
                        'unit': unit
                    })
                # --- END OF RESTORED LOGIC ---
                else:
                    logging.warning(f"Reply {i} invalid: {received_msg}")
                    break
            except asyncio.TimeoutError:
                logging.error(f"Timeout waiting for reply {i}. Aborting polling cycle.")
                break
            except KeyError as e:
                logging.error(f"Key error in reply {i}: {e}. Aborting polling cycle.")
                break

    async def run(self):
        """Runs the parameter request process in a continuous loop with robust error recovery."""
        loop = asyncio.get_running_loop()

        while True:
            transport = None
            try:
                enable_udp_send = True

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

                    await self.send_parameter_requests()

                    if len(self.data) < 19:
                        logging.warning("Communication failed: Incomplete data set received. Restarting handshake.")
                        break
                    
                    # MODIFIED: Simplified to str() to handle pre-formatted floats and integers
                    payloads = [str(row['payload']) for row in self.data]

                    if payloads[0] != "8":
                        logging.warning(f"Invalid data: First payload is '{payloads[0]}', expected '8'. Restarting handshake.")
                        break
                    
                    message_payloads = payloads[1:]
                    message = "VAC;PUMP1;" + ";".join(message_payloads)
                    
                    logging.info(f"Successfully polled valid data packet (18 payloads): {message}")
                    
                    if enable_udp_send:
                        try:
                            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                            server_address = ('mtsgwm3ux05ac02.emea.avnet.com', 4041)
                            udp_socket.sendto(message.encode('utf-8'), server_address)
                            logging.info(f"Sent UDP message to {server_address[0]}:{server_address[1]}")
                            udp_socket.close()
                        except socket.gaierror as e:
                            logging.error(f"UDP hostname resolution failed: {e}")
                        except OSError as e:
                            logging.error(f"UDP send error: {e}")
                    else:
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
                await asyncio.sleep(5)