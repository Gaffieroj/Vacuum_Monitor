import asyncio
import logging
from parameter_request_handler import ParameterRequestManager

async def main():
    port = 'COM8'
    baudrate = 57600
    # Updated to remove obsolete 'iterations' and 'delay' arguments
    manager = ParameterRequestManager(port, baudrate)
    await manager.run()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    asyncio.run(main())