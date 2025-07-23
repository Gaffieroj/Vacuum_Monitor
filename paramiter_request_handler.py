from dataclasses import dataclass
import asyncio
import logging
import socket
import sys
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

    def __init__(self, port, baudrate, iterations=1, delay=1.0):
        self.port = port
        self.baudrate = baudrate
        self.iterations = iterations
        self.delay = delay
        self.handler = None
        self.data = []
        self.channels = [
            ChannelConfig(0x00, 0x01, 1, "Output Freq", "Hz", 0.01),
            ChannelConfig(0x00, 0x19, 25, "Freq Ref.", "Hz", 0.01),
            ChannelConfig(0x00, 0x02, 2, "Motor shaft speed", "rpm", 1),
            ChannelConfig(0x00, 0x03, 3, "Motor Current", "A", 0.01),
            ChannelConfig(0x00, 0x04, 4, "Motor Torque", "%", 0.1),
            ChannelConfig(0x00, 0x05, 5, "Motor Power", "%", 0.1),
            ChannelConfig(0x00, 0x06, 6, "Motor Voltage", "V", 0.1),
            ChannelConfig(0x00, 0x09, 9, "Motor Temperature", "°C", 1),
            ChannelConfig(0x00, 0x07, 7, "DC-link Volatage", "V", 1),
            ChannelConfig(0x00, 0x08, 8, "Unit Temperature", "°C", 1),
            ChannelConfig(0x07, 0x21, 1825, "Board Temp", "°C", 1),
            ChannelConfig(0x07, 0x6B, 1899, "Service counter", "h", 1)
        ]
        self.messages = [(c.id_high, c.id_low, 0x00, 0x01) for c in self.channels]

    async def send_parameter_requests(self, iteration):
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
                logging.info(f"Iteration {iteration} - Received reply {i}: {received_bytes.hex().upper()}")
                self.handler.send_ack()
                if is_valid:
                    payload_int = int.from_bytes(received_msg['payload'], byteorder='big')
                    channel = next((c for c in self.channels if c.id_high == id_high and c.id_low == id_low), None)
                    channel_id = channel.channel_id if channel else 0
                    channel_name = channel.channel_name if channel else "Unknown"
                    unit = channel.unit if channel else "N/A"
                    multiplier = channel.multiplier if channel else 1
                    payload_value = payload_int * multiplier
                    if multiplier < 1:
                        payload_formatted = f"{payload_value:.2f}"
                    else:
                        payload_formatted = int(payload_value)
                    logging.info(f"Iteration {iteration} - Reply {i} valid, channel_id: {channel_id}, channel: {channel_name}, payload: {payload_formatted}, unit: {unit}")
                    self.data.append({
                        'iteration': iteration,
                        'channel_id': channel_id,
                        'channel_name': channel_name,
                        'payload': payload_formatted,
                        'unit': unit
                    })
                else:
                    logging.warning(f"Iteration {iteration} - Reply {i} invalid: {received_msg}")
            except asyncio.TimeoutError:
                logging.error(f"Iteration {iteration} - Timeout waiting for reply {i}")
            except KeyError as e:
                logging.error(f"Iteration {iteration} - Key error in reply {i}: {e}, received_msg: {received_msg}")

    async def run(self):
        """Run the parameter request process for a single iteration."""
        try:
            loop = asyncio.get_running_loop()
            handshake_success = False
            max_handshake_retries = 5
            transport = None

            for attempt in range(1, max_handshake_retries + 1):
                logging.info(f"Handshake attempt {attempt}/{max_handshake_retries}")
                # Open serial connection
                transport, protocol = await serial_asyncio.create_serial_connection(
                    loop, lambda: PackageHandler(), self.port, baudrate=self.baudrate
                )
                self.handler = protocol

                if await self.handler.handshake():
                    handshake_success = True
                    break
                else:
                    logging.warning(f"Handshake attempt {attempt} failed.")
                    transport.close()  # Close COM port before retry
                    await asyncio.sleep(2)  # Wait before retry

            if not handshake_success:
                logging.error("Handshake failed after maximum retries. Exiting.")
                sys.exit(1)

            for iteration in range(1, self.iterations + 1):
                logging.info(f"Starting iteration {iteration}/{self.iterations}")
                await self.send_parameter_requests(iteration)
                payloads = [str(row['payload']) for row in self.data]
                message = "VAC;PUMP1;" + ";".join(payloads)
                logging.info(f"Prepared UDP message: {message}")
                try:
                    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    server_address = ('mtsgwm3ux05ac02.emea.avnet.com', 4041)
                    udp_socket.sendto(message.encode('utf-8'), server_address)
                    logging.info(f"Sent UDP message to {server_address[0]}:{server_address[1]}")
                    udp_socket.close()
                except socket.gaierror as e:
                    logging.error(f"UDP hostname resolution failed: {e}")
                    raise
                except OSError as e:
                    logging.error(f"UDP send error: {e}")
                    raise

            if transport:
                transport.close()
            logging.info("Serial connection closed, terminating script.")
            loop.stop()
            sys.exit(0)

        except Exception as e:
            logging.critical(f"Error: {e}")
            sys.exit(1)