import asyncio
import logging
from crcmod.predefined import mkPredefinedCrcFun

class PackageHandler(asyncio.Protocol):
    def __init__(self):
        super().__init__()
        self.transport = None
        self.buffer = bytearray()
        self.ack = b'\x10\x06'
        self.header = b'\x10\x02'
        self.msg_done = b'\x10\x03'
        self.crc8 = mkPredefinedCrcFun('crc-8-maxim')
        self.on_con_lost = asyncio.get_event_loop().create_future()
        self.send_counter_val = 4
        self.receive_counter_val = None
        self.message_queue = asyncio.Queue()

    def connection_made(self, transport):
        self.transport = transport
        logging.info("Connection established at 57600 baud.")

    def connection_lost(self, exc):
        logging.warning("Connection lost.")
        self.on_con_lost.set_result(True)

    def data_received(self, data):
        logging.debug(f"RAW RECV: {data.hex().upper()}")
        self.buffer.extend(data)
        self.decode_rec_msg()

    def send_data(self, data: bytes):
        if self.transport:
            self.transport.write(data)
            logging.info(f"SENT: {data.hex().upper()}")

    def send_ack(self):
        self.send_data(self.ack)
        logging.debug("Sent ACK")

    def gen_crc(self, msg_body: bytes):
        try:
            payload_for_crc = msg_body[len(self.header):]
            return bytes([self.crc8(payload_for_crc)])
        except Exception as e:
            logging.error(f"CRC gen error: {e}")
            return b'\x00'

    def increment_send_counter(self):
        if self.send_counter_val > 7:
            self.send_counter_val = 4
        val_send_cnt = self.send_counter_val
        self.send_counter_val += 1
        return val_send_cnt
    
    def increment_receive_counter(self):
        if self.receive_counter_val is not None:
            if self.receive_counter_val > 7:
                self.receive_counter_val = 4
            self.receive_counter_val += 1

    def send_custom_message(self, prefix_nibble: int, payload: bytes):
        """Builds and sends a message with a custom payload, handling counter and CRC."""
        try:
            counter_val = self.increment_send_counter()
            byte3 = int(f"{prefix_nibble}{counter_val}", 16)
            
            msg_body = bytearray()
            msg_body.extend(self.header)
            msg_body.append(byte3)
            msg_body.extend(payload)
            
            full_msg = msg_body + self.msg_done + self.gen_crc(msg_body)
            self.send_data(full_msg)
            logging.debug(f"Queued custom message for sending: {full_msg.hex().upper()}")
        except Exception as e:
            logging.error(f"Failed to send custom message: {e}")

    def send_msg(self, id_high: int, id_low: int, payload_high: int, payload_low: int):
        """Sends a standard parameter request message."""
        payload = bytes([0x0B, 0x01, id_high, id_low, payload_high, payload_low])
        self.send_custom_message(prefix_nibble=4, payload=payload)

    async def handshake(self, timeout=1):
        """Performs the initial handshake to synchronize counters."""
        try:
            start_time = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start_time < timeout:
                await asyncio.sleep(0.01)

                if self.header in self.buffer and self.msg_done in self.buffer:
                    start = self.buffer.find(self.header)
                    end = self.buffer.find(self.msg_done, start) + len(self.msg_done)

                    if len(self.buffer) < end + 1:
                        continue

                    frame = self.buffer[start:end]
                    crc_byte = self.buffer[end:end + 1]
                    
                    # --- MODIFIED LOGIC ---
                    # Find the footer within the frame to correctly isolate the payload.
                    footer_pos_in_frame = frame.find(self.msg_done)
                    # The payload for CRC is BETWEEN the header and the footer.
                    calc_crc_payload = frame[len(self.header):footer_pos_in_frame]
                    expected_crc = self.crc8(calc_crc_payload)
                    # --- END OF MODIFICATION ---

                    if crc_byte and crc_byte[0] == expected_crc:
                        logging.info(f"HANDSHAKE RECV: Valid message received: {frame.hex().upper()}{crc_byte.hex().upper()}")
                        self.send_ack()
                        self.receive_counter_val = frame[2] & 0x0F
                        logging.info(f"HANDSHAKE: Set receive_counter_val to {self.receive_counter_val}.")
                        
                        payload = bytes([0x00, 0x00])
                        self.send_custom_message(prefix_nibble=8, payload=payload)
                        self.buffer = self.buffer[end + 1:]
                        return True
                    else:
                        logging.warning(f"HANDSHAKE: Invalid CRC. Got {crc_byte.hex().upper()}, expected {expected_crc:02X}")
                        self.buffer = self.buffer[end + 1:]
                        return False
            logging.warning("Handshake timeout.")
            return False
        except Exception as e:
            logging.error(f"Handshake error: {e}")
            return False

    def decode_rec_msg(self):
        """Decodes incoming messages from the buffer."""
        try:
            while True:
                ack_index = self.buffer.find(self.ack)
                if ack_index == -1: return

                header_index = ack_index + len(self.ack)
                if len(self.buffer) < header_index + len(self.header): return

                if self.buffer[header_index:header_index + 2] != self.header:
                    self.buffer = self.buffer[ack_index + 1:]
                    continue

                msg_type = self.buffer[header_index + 2]
                if not (0xC4 <= msg_type <= 0xC7):
                    self.buffer = self.buffer[ack_index + 1:]
                    continue
                
                done_index = self.buffer.find(self.msg_done, header_index)
                if done_index == -1: return

                crc_index = done_index + len(self.msg_done)
                if len(self.buffer) <= crc_index: return

                crc = self.buffer[crc_index]
                full_msg_body = self.buffer[header_index:done_index]
                payload_for_crc = full_msg_body[len(self.header):]
                calc = self.crc8(payload_for_crc)
                
                if crc != calc:
                    logging.warning(f"CRC MISMATCH: Full message: {self.buffer[header_index:crc_index+1].hex().upper()}. Calculated CRC: {calc:02X}, Received CRC: {crc:02X}")
                    self.buffer = self.buffer[crc_index + 1:]
                    continue

                type_ = self.buffer[header_index + 2]
                byte6 = self.buffer[header_index + 3]
                byte7 = self.buffer[header_index + 4]
                payload = self.buffer[header_index + 5:done_index]
                full_message = self.buffer[ack_index:crc_index + 1]

                prev_counter = self.receive_counter_val
                self.increment_receive_counter()
                expected_type = int(f"C{self.receive_counter_val}", 16)
                
                is_valid_type = (type_ == expected_type)
                
                decoded_msg = {
                    'type': type_, 'byte6': byte6, 'byte7': byte7, 'payload': payload,
                    'full_message': full_message, 'receive_counter': self.receive_counter_val,
                    'is_valid_type': is_valid_type
                }
                
                logging.info(f"DECODED MSG: Full message: {full_message.hex().upper()}, Payload: {payload.hex().upper()}")
                
                if not is_valid_type:
                    logging.warning(f"COUNTER MISMATCH: Received type {type_:02X}, but expected {expected_type:02X}.")
                    new_counter = type_ & 0x0F
                    logging.info(f"RE-SYNCING counter from {self.receive_counter_val} to {new_counter}.")
                    self.receive_counter_val = new_counter
                    decoded_msg['is_valid_type'] = True

                self.message_queue.put_nowait(decoded_msg)
                self.buffer = self.buffer[crc_index + 1:]

        except Exception as e:
            logging.error(f"Error decoding message: {e}", exc_info=True)