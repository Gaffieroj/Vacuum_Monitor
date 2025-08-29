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
        self.receive_counter_val = None  # Initialize as None until handshake
        self.message_queue = asyncio.Queue()

    def connection_made(self, transport):
        self.transport = transport
        logging.info("Connection established at 57600 baud.")

    def connection_lost(self, exc):
        logging.warning("Connection lost.")
        self.on_con_lost.set_result(True)

    def data_received(self, data):
        self.buffer.extend(data)
        self.decode_rec_msg()

    def send_data(self, data: bytes):
        if self.transport:
            self.transport.write(data)
            logging.debug(f"Sent: {data.hex().upper()}")

    def send_ack(self):
        self.send_data(self.ack)
        logging.info("Sent ACK")

    def gen_crc(self, msg: bytes):
        try:
            start = len(self.header)
            end = msg.find(self.msg_done)
            payload = msg[start:end]
            return bytes([self.crc8(payload)])
        except Exception as e:
            logging.error(f"CRC gen error: {e}")
            return b'\x00'

    def calc_crc(self, msg: bytes):
        try:
            start = len(self.header)
            end = msg.find(self.msg_done)
            payload = msg[start:end]
            return self.crc8(payload)
        except Exception as e:
            logging.error(f"CRC calc error: {e}")
            return None

    def increment_send_counter(self):
        val_send_cnt = self.send_counter_val
        self.send_counter_val += 1
        if self.send_counter_val > 7:
            self.send_counter_val = 4
        return val_send_cnt
    
    def increment_receive_counter(self):
        if self.receive_counter_val is None:
            return None
        val_rec_cnt = self.receive_counter_val
        self.receive_counter_val += 1
        if self.receive_counter_val > 7:
            self.receive_counter_val = 4
        return val_rec_cnt

    def send_msg(self, id_high: int, id_low: int, payload_high: int, payload_low: int):
        try:
            counter_val = self.increment_send_counter()
            byte3 = int(f"4{counter_val}", 16)

            msg = bytearray()
            msg.extend(self.header)
            msg.append(byte3)
            msg.append(0x0B)
            msg.append(0x01)
            msg.append(id_high)
            msg.append(id_low)
            msg.append(payload_high)
            msg.append(payload_low)
            msg.extend(self.msg_done)
            msg.extend(self.gen_crc(msg))

            self.send_data(bytes(msg))
            logging.info(f"Sent parameter request: {bytes(msg).hex().upper()}")

        except Exception as e:
            logging.error(f"Failed to send message: {e}")

    async def handshake(self, timeout=1):
        try:
            start_time = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start_time < timeout:
                await asyncio.sleep(0.01)

                if self.header in self.buffer and self.msg_done in self.buffer:
                    start = self.buffer.find(self.header)
                    end = self.buffer.find(self.msg_done, start) + len(self.msg_done)

                    if end + 1 > len(self.buffer):
                        continue

                    frame = self.buffer[start:end]
                    crc_byte = self.buffer[end:end + 1]
                    full_msg = frame + crc_byte
                    self.buffer = self.buffer[end + 1:]

                    logging.info(f"Received during handshake: {full_msg.hex().upper()}")

                    expected_crc = self.calc_crc(full_msg)
                    if crc_byte and expected_crc is not None and crc_byte[0] == expected_crc:
                        logging.info("Valid handshake message.")
                        self.send_ack()
                        self.receive_counter_val = frame[2] & 0x0F
                        logging.info(f"Set receive_counter_val to {self.receive_counter_val} from handshake Byte 3: {frame[2]:02X}")
                        counter_val = self.increment_send_counter()
                        byte3 = int(f"8{counter_val}", 16)
                        msg = bytearray()
                        msg.extend(self.header)
                        msg.append(byte3)
                        msg.append(0x00)
                        msg.append(0x00)
                        msg.extend(self.msg_done)
                        payload = msg[2:5]
                        crc = self.crc8(payload)
                        msg.append(crc)
                        self.send_data(msg)
                        logging.info(f"Sent handshake message: {msg.hex().upper()}")
                        return True
                    else:
                        logging.warning("Invalid handshake CRC.")
                        return False
            logging.warning("Handshake timeout.")
            return False
        except Exception as e:
            logging.error(f"Handshake error: {e}")
            return False

    def decode_rec_msg(self):
        try:
            while True:
                ack_index = self.buffer.find(self.ack)
                if ack_index == -1:
                    return

                header_index = ack_index + len(self.ack)
                if len(self.buffer) < header_index + len(self.header):
                    return

                if self.buffer[header_index:header_index + 2] != self.header:
                    self.buffer = self.buffer[ack_index + 1:]
                    continue

                msg_type = self.buffer[header_index + 2]
                if not (0xC4 <= msg_type <= 0xC7):
                    self.buffer = self.buffer[ack_index + 1:]
                    continue
                
                done_index = self.buffer.find(self.msg_done, header_index)
                if done_index == -1:
                    return

                # --- MODIFIED LOGIC ---
                # Calculate the expected position of the CRC byte.
                crc_index = done_index + len(self.msg_done)
                
                # Check if the buffer is long enough to contain the CRC byte.
                if len(self.buffer) <= crc_index:
                    return # The full message (including CRC) has not arrived yet.

                crc = self.buffer[crc_index]
                full_msg_body = self.buffer[header_index:done_index]
                payload_for_crc = full_msg_body[len(self.header):]
                
                calc = self.crc8(payload_for_crc)
                
                if crc != calc:
                    logging.warning(f"CRC mismatch in response: {self.buffer[header_index:crc_index+1].hex().upper()}")
                    self.buffer = self.buffer[crc_index + 1:]
                    continue

                # Extract data now that we know the message is complete and valid
                type_ = self.buffer[header_index + 2]
                byte6 = self.buffer[header_index + 3]
                byte7 = self.buffer[header_index + 4]
                payload = self.buffer[header_index + 5:done_index]
                full_message = self.buffer[ack_index:crc_index + 1]

                prev_counter = self.receive_counter_val
                self.increment_receive_counter()
                expected_type = int(f"C{self.receive_counter_val}", 16)
                
                decoded_msg = {
                    'type': type_, 'byte6': byte6, 'byte7': byte7, 'payload': payload,
                    'full_message': full_message, 'receive_counter': self.receive_counter_val,
                    'is_valid_type': type_ == expected_type
                }
                self.message_queue.put_nowait(decoded_msg)
                
                logging.info(f"Decoded message: type={type_:02X}, byte6={byte6:02X}, byte7={byte7:02X}, payload={payload.hex().upper()}, receive_counter={self.receive_counter_val} (prev={prev_counter})")
                if not decoded_msg['is_valid_type']:
                    logging.warning(f"Unexpected message type: received {type_:02X}, expected {expected_type:02X}, receive_counter={self.receive_counter_val}")

                self.buffer = self.buffer[crc_index + 1:]

        except Exception as e:
            logging.error(f"Error decoding message: {e}")