import asyncio
import logging
from paramiter_request_handler import ParameterRequestManager

async def main():
    port = 'COM8'
    baudrate = 57600
    manager = ParameterRequestManager(port, baudrate, iterations=10, delay=1.0)
    await manager.run()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    asyncio.run(main())