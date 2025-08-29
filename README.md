# Serial Parameter Logger

This project is a Python-based application for communicating with a BUSCH MV0800 over a serial connection to request parameter data, process responses, and sends results to server via udp. It uses asynchronous I/O to handle serial communication, perform handshakes, validate messages with CRC-8-Maxim, and log data for multiple iterations.

## Features

- Performs a handshake with the device to establish communication.
- Sends parameter requests for 18 predefined channels (e.g., Output Freq, Motor Temperature).
- Processes 2-byte payloads with configurable multipliers (0.01, 0.1, or 1) for float or integer output.
- Exports valid responses to `parameter_data.csv` with columns: `iteration`, `channel_id`, `channel_name`, `payload`, `unit`.
- Supports 10 iterations with a 1-second delay between iterations.
- Includes comprehensive logging for debugging and monitoring.
- Terminates cleanly after completing iterations by closing the serial connection.
- Fully documented with Doxygen-style comments for code clarity.

## Requirements

- Python 3.7+
- Required packages:
  - `pyserial-asyncio` for asynchronous serial communication
  - `crcmod` for CRC-8-Maxim calculation

## Installation

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/yourusername/serial-parameter-logger.git
   cd serial-parameter-logger
   ```

2. **Install Dependencies**:
   ```bash
   pip install pyserial-asyncio crcmod
   ```

3. **Verify Python Version**:
   Ensure Python 3.7 or higher is installed:
   ```bash
   python --version
   ```

## Usage

1. **Configure the Serial Port**:
   - Edit `main.py` to set the correct serial port for your device (e.g., `COM8` on Windows or `/dev/ttyUSB0` on Linux/Mac).
   - Example:
     ```python
     PORT = "COM8"  # Update this to your serial port
     ```

2. **Run the Script**:
   ```bash
   python main.py
   ```

3. **Output**:
   - The script performs 10 iterations, sending a handshake and 12 parameter requests per iteration.
   - Valid responses are logged and saved to `parameter_data.csv` in the project directory.
   - Example CSV content:
     ```
     iteration,channel_id,channel_name,payload,unit
     1,1,Output Freq,108.60,Hz
     1,25,Freq Ref.,46.60,Hz
     1,2,Motor shaft speed,10860,rpm
     1,3,Motor Current,12.34,A
     1,4,Motor Torque,1086.00,%
     1,5,Motor Power,1234.50,%
     1,6,Motor Voltage,567.80,V
     1,9,Motor Temperature,10860,°C
     1,7,DC-link Volatage,10860,V
     1,8,Unit Temperature,10860,°C
     1,1825,Board Temp,10860,°C
     1,1899,Service counter,10860,h
     ```
   - Logs are output to the console with timestamps, including handshake status, sent/received messages, and errors.

4. **Generate Doxygen Documentation** (Optional):
   - Install Doxygen: `pip install doxygen` or use your system package manager.
   - Create a Doxygen configuration file:
     ```bash
     doxygen -g Doxyfile
     ```
   - Edit `Doxyfile` to set:
     ```
     INPUT = paramiter_request_handler.py package_handler_async.py
     GENERATE_HTML = YES
     ```
   - Run Doxygen:
     ```bash
     doxygen Doxyfile
     ```
   - Open `html/index.html` in a browser to view the documentation.

## File Structure

- `main.py`: Entry point, initializes and runs the `ParameterRequestManager`.
- `paramiter_request_handler.py`: Manages parameter requests, processes responses, and exports data to CSV. Includes channel configurations and payload processing logic.
- `package_handler_async.py`: Handles low-level serial communication, including handshake, message encoding/decoding, and CRC validation.
- `parameter_data.csv`: Output file containing collected parameter data (generated after running the script).

## Channel Configuration

The script requests data for 12 channels, each with a unique ID, name, unit, and multiplier for payload processing:

| Channel ID | Name                 | Unit | Multiplier | Output Format |
|------------|----------------------|------|------------|---------------|
| 1          | Output Freq          | Hz   | 0.01       | Float (2 decimals) |
| 25         | Freq Ref.            | Hz   | 0.01       | Float (2 decimals) |
| 2          | Motor shaft speed    | rpm  | 1          | Integer       |
| 3          | Motor Current        | A    | 0.01       | Float (2 decimals) |
| 4          | Motor Torque         | %    | 0.1        | Float (2 decimals) |
| 5          | Motor Power          | %    | 0.1        | Float (2 decimals) |
| 6          | Motor Voltage        | V    | 0.1        | Float (2 decimals) |
| 9          | Motor Temperature    | °C   | 1          | Integer       |
| 7          | DC-link Volatage     | V    | 1          | Integer       |
| 8          | Unit Temperature     | °C   | 1          | Integer       |
| 1825       | Board Temp           | °C   | 1          | Integer       |
| 1899       | Service counter      | h    | 1          | Integer       |

- **Multiplier**:
  - `0.01`: Divide payload by 100 (e.g., `10860` → `108.60`).
  - `0.1`: Divide payload by 10 (e.g., `10860` → `1086.00`).
  - `1`: Keep payload as integer (e.g., `10860` → `10860`).

## Notes

- **Serial Port**: Ensure the device is connected and the port is correct in `main.py`. Common ports include `COM1`-`COMn` (Windows) or `/dev/ttyUSB0`, `/dev/ttyACM0` (Linux/Mac).
- **Baud Rate**: Set to 57600 in `main.py`. Modify if your device uses a different rate.
- **Error Handling**: The script logs timeouts, CRC mismatches, and invalid messages. Check the console output for debugging.
- **Filename Typo**: The file `paramiter_request_handler.py` contains a typo (`paramiter`). Consider renaming to `parameter_request_handler.py` for clarity.
- **Payload Format**: Assumes 2-byte, big-endian payloads. If your device uses a different format (e.g., signed integers), update the payload processing in `paramiter_request_handler.py`.
- **Termination**: The script terminates after 10 iterations by closing the serial connection and exiting.

## Example Log Output

```
[2025-07-22 07:09:00] INFO: Connection established at 57600 baud.
[2025-07-22 07:09:01] INFO: Starting iteration 1/10
[2025-07-22 07:09:01] INFO: Received during handshake: 1002870000100318
[2025-07-22 07:09:01] INFO: Valid handshake message.
[2025-07-22 07:09:01] INFO: Sent ACK
[2025-07-22 07:09:01] INFO: Set receive_counter_val to 7 from handshake Byte 3: 87
[2025-07-22 07:09:01] INFO: Sent handshake message: 10028400001003FC
[2025-07-22 07:09:01] INFO: Iteration 1 - Sent parameter request: 1002450B01000100011003CE
[2025-07-22 07:09:01] INFO: Decoded message: type=C4, byte6=0B, byte7=03, payload=2A6C, receive_counter=4 (prev=7)
[2025-07-22 07:09:01] INFO: Iteration 1 - Received reply 1: 10061002C40B032A6C1003AD
[2025-07-22 07:09:01] INFO: Sent ACK
[2025-07-22 07:09:01] INFO: Iteration 1 - Reply 1 valid, channel_id: 1, channel: Output Freq, payload: 108.60, unit: Hz
...
[2025-07-22 07:09:10] INFO: Starting iteration 10/10
...
[2025-07-22 07:09:11] INFO: Data exported to parameter_data.csv
[2025-07-22 07:09:11] INFO: Serial connection closed, terminating script.
```

## Contributing

1. Fork the repository.
2. Create a feature branch: `git checkout -b feature-name`.
3. Commit changes: `git commit -m "Add feature-name"`.
4. Push to the branch: `git push origin feature-name`.
5. Submit a pull request.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.

## Contact

For issues or questions, open an issue on GitHub or contact [yourusername]@example.com.