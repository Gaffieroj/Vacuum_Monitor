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
    """Manages the state machine for device communication."""

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
    
    async def run_keep_alive_cycle(self):
        """Runs one full 4-step keep-alive sequence to maintain the connection."""
        try:
            logging.debug("Running keep-alive step 1...")
            self.handler.send_custom_message(4, b'\x0B\x00\x02\x75\x00\x00')
            await asyncio.wait_for(self.handler.message_queue.get(), timeout=0.2)
            self.handler.send_ack()
            
            logging.debug("Running keep-alive step 2...")
            self.handler.send_custom_message(4, b'\x0B\x00\x02\x66\x00\x00')
            await asyncio.wait_for(self.handler.message_queue.get(), timeout=0.2)
            self.handler.send_ack()
            
            logging.debug("Running keep-alive step 3...")
            self.handler.send_custom_message(4, b'\x2A\x0C')
            await asyncio.wait_for(self.handler.message_queue.get(), timeout=0.2)
            self.handler.send_ack()
            
            logging.debug("Running keep-alive step 4...")
            self.handler.send_custom_message(4, b'\x0B\x01\x03\x40\x00\x01')
            await asyncio.wait_for(self.handler.message_queue.get(), timeout=0.2)
            self.handler.send_ack()
            
            return True
        except asyncio.TimeoutError:
            logging.warning("Timeout during keep-alive cycle. Connection may be lost.")
            return False

    async def send_parameter_requests(self):
        """Sends requests for all 19 channels as a single block."""
        self.data.clear()
        
        for i, (id_high, id_low, payload_high, payload_low) in enumerate(self.messages, 1):
            logging.debug(f"Requesting parameter {i}/{len(self.messages)}...")
            self.handler.send_msg(id_high, id_low, payload_high, payload_low)
            try:
                received_msg = await asyncio.wait_for(self.handler.message_queue.get(), timeout=5)
                is_valid = (len(received_msg['full_message']) >= 6 and received_msg.get('is_valid_type', False))
                
                self.handler.send_ack()

                if is_valid:
                    payload_int = int.from_bytes(received_msg['payload'], byteorder='big')
                    channel = next((c for c in self.channels if c.id_high == id_high and c.id_low == id_low), None)
                    payload_value = payload_int * (channel.multiplier if channel else 1)
                    
                    if channel and channel.channel_id == 14:
                        final_payload = int(-1000 + payload_value)
                    else:
                        final_payload = payload_value
                    
                    self.data.append({'payload': final_payload, 'channel': channel})
                else:
                    logging.warning(f"Reply {i} marked as invalid: {received_msg}")
                    break
            except asyncio.TimeoutError:
                logging.error(f"Timeout waiting for reply {i}. Aborting polling cycle.")
                break
            except KeyError as e:
                logging.error(f"Key error processing reply {i}: {e}. Aborting polling cycle.")
                break

    async def run(self):
        """Runs the main state machine: keep-alive loop interrupted by data polls."""
        loop = asyncio.get_event_loop()
        last_poll_start_time = 0

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

                logging.info("Handshake successful. Starting main operational loop.")
                last_poll_start_time = loop.time() - 2 # Start the first poll immediately

                while True:
                    logging.info(">>> Entering Keep-Alive phase...")
                    while loop.time() - last_poll_start_time < 1.0:
                        if not await self.run_keep_alive_cycle():
                            raise ConnectionAbortedError("Keep-alive failed")
                        
                        # --- NEW: Delay between keep-alive blocks ---
                        logging.debug("Keep-alive block complete. Waiting 1 second...")
                        await asyncio.sleep(1)

                    logging.info(">>> Timer expired. Transitioning to Data Poll phase...")
                    last_poll_start_time = loop.time()

                    while not self.handler.message_queue.empty():
                        self.handler.message_queue.get_nowait()
                    
                    await self.send_parameter_requests()

                    if len(self.data) < 19:
                        logging.warning("Poll resulted in incomplete data set. Restarting handshake.")
                        break

                    formatted_payloads = []
                    for item in self.data:
                        channel = item['channel']
                        payload_val = item['payload']
                        if channel and channel.multiplier < 1 and channel.channel_id != 14:
                            formatted_payloads.append(f"{payload_val:.2f}")
                        else:
                            formatted_payloads.append(str(int(payload_val)))
                    
                    if formatted_payloads[0] != "8":
                        logging.warning(f"Integrity Check Failed: First payload is '{formatted_payloads[0]}', expected '8'. Restarting handshake.")
                        break
                    
                    message_payloads = formatted_payloads[1:]
                    message = "VAC;PUMP1;" + ";".join(message_payloads)
                    logging.info(f"SUCCESS: Polled valid data packet (18 payloads): {message}")
                    
                    if enable_udp_send:
                        try:
                            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                            server_address = ('mtsgwm3ux05ac02.emea.avnet.com', 4041)
                            udp_socket.sendto(message.encode('utf-8'), server_address)
                            logging.info(f"UDP message sent to {server_address[0]}:{server_address[1]}")
                            udp_socket.close()
                        except Exception as e:
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
                    
                    logging.info(">>> Data Poll phase complete. Transitioning back to Keep-Alive phase...")

            except (serial_asyncio.serial.SerialException, OSError, ConnectionAbortedError) as e:
                logging.error(f"Connection error: {e}. Attempting to reconnect...")
            except Exception as e:
                logging.critical(f"An unexpected error occurred: {e}. Attempting to reconnect...", exc_info=True)
            finally:
                if transport:
                    logging.info("Closing serial port.")
                    transport.close()
                transport = None
                self.handler = None
                await asyncio.sleep(5)