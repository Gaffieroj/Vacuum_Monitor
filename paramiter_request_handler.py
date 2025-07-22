from dataclasses import dataclass
import asyncio
import logging
import socket
import sys
import serial_asyncio
from package_handler_async import PackageHandler

@dataclass
class ChannelConfig:
    """Configuration for a device channel.

    Stores metadata for a parameter channel, including ID, name, unit, and multiplier
    for payload processing.
    
    @param id_high: High byte of the parameter ID.
    @type id_high: int
    @param id_low: Low byte of the parameter ID.
    @type id_low: int
    @param channel_id: Decimal channel ID (id_high * 256 + id_low).
    @type channel_id: int
    @param channel_name: Human-readable name of the channel.
    @type channel_name: str
    @param unit: Unit of measurement for the channel.
    @type unit: str
    @param multiplier: Multiplier for payload conversion (0.01, 0.1, or 1).
    @type multiplier: float
    """
    id_high: int
    id_low: int
    channel_id: int
    channel_name: str
    unit: str
    multiplier: float

class ParameterRequestManager:
    """Manages parameter requests and data transmission over a serial connection and UDP.

    Handles sending parameter requests, processing responses, and sending payloads
    prefixed with 'VAC;PUMP1;' to a UDP server for a single iteration of requests,
    only if the handshake is successful.
    """

    def __init__(self, port, baudrate, iterations=1, delay=1.0):
        """Initialize the ParameterRequestManager with serial and iteration settings.

        @param port: Serial port identifier (e.g., 'COM8' or '/dev/ttyUSB0').
        @type port: str
        @param baudrate: Serial baud rate (e.g., 57600).
        @type baudrate: int
        @param iterations: Number of iterations to perform (default: 1).
        @type iterations: int
        @param delay: Delay after iteration (seconds, default: 1.0).
        @type delay: float
        """
        self.port = port
        self.baudrate = baudrate
        self.iterations = iterations
        self.delay = delay
        self.handler = None
        self.data = []  # Store iteration, channel_id, channel_name, payload, unit
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
        """Send parameter requests for all channels and process responses.

        @param iteration: Current iteration number (1-based).
        @type iteration: int
        @throws asyncio.TimeoutError: If a response is not received within 5 seconds.
        @throws KeyError: If the received message lacks expected fields.
        """
        for i, (id_high, id_low, payload_high, payload_low) in enumerate(self.messages, 1):
            self.handler.send_msg(id_high, id_low, payload_high, payload_low)
            try:
                received_msg = await asyncio.wait_for(self.handler.message_queue.get(), timeout=5)
                received_bytes = received_msg['full_message']
                # Check structure and validity
                is_valid = (len(received_bytes) >= 6 and
                            received_bytes[0:2] == self.handler.ack and
                            received_bytes[2:4] == self.handler.header and
                            received_bytes[4] in range(0xC4, 0xC8) and
                            self.handler.msg_done in received_bytes[5:-1] and
                            len(received_bytes) >= received_bytes.find(self.handler.msg_done) + len(self.handler.msg_done) + 1 and
                            received_msg.get('is_valid_type', False))
                logging.info(f"Iteration {iteration} - Received reply {i}: {received_bytes.hex().upper()}")
                self.handler.send_ack()  # Send ACK for the reply
                if is_valid:
                    # Convert payload to integer
                    payload_int = int.from_bytes(received_msg['payload'], byteorder='big')
                    # Find the channel config for this id_high, id_low
                    channel = next((c for c in self.channels if c.id_high == id_high and c.id_low == id_low), None)
                    channel_id = channel.channel_id if channel else 0
                    channel_name = channel.channel_name if channel else "Unknown"
                    unit = channel.unit if channel else "N/A"
                    multiplier = channel.multiplier if channel else 1
                    # Process payload based on multiplier
                    payload_value = payload_int * multiplier
                    if multiplier < 1:  # Format floats (0.01 or 0.1)
                        payload_formatted = f"{payload_value:.2f}"
                    else:  # Keep integers (multiplier = 1)
                        payload_formatted = int(payload_value)
                    logging.info(f"Iteration {iteration} - Reply {i} valid, channel_id: {channel_id}, channel: {channel_name}, payload: {payload_formatted}, unit: {unit}")
                    # Store valid reply data (only payload needed for UDP)
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
        """Run the parameter request process for a single iteration.

        Establishes a serial connection, performs handshake, and sends parameter
        requests. If the handshake is successful, sends payloads prefixed with
        'VAC;PUMP1;' to a UDP server. Terminates the script after completion.
        @throws Exception: If serial connection, processing, or UDP transmission fails.
        """
        try:
            loop = asyncio.get_running_loop()
            transport, protocol = await serial_asyncio.create_serial_connection(
                loop, lambda: PackageHandler(), self.port, baudrate=self.baudrate
            )
            self.handler = protocol

            for iteration in range(1, self.iterations + 1):
                logging.info(f"Starting iteration {iteration}/{self.iterations}")
                if await self.handler.handshake():
                    await self.send_parameter_requests(iteration)
                    # Prepare and send UDP message only if handshake succeeds
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
                else:
                    logging.error(f"Iteration {iteration} - Handshake failed, skipping UDP transmission.")

            transport.close()  # Close serial connection
            logging.info("Serial connection closed, terminating script.")
            loop.stop()  # Stop the event loop
            sys.exit(0)  # Exit the script

        except Exception as e:
            logging.critical(f"Error: {e}")
            sys.exit(1)  # Exit with error code on failure