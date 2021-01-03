import os
import sys
import logging
import psutil

from RobOto.core.extention import RawClient

LOG = logging.getLogger(__name__)


class Restart(RawClient):
    async def restart(self, update_req: bool = False) -> None:
        LOG.info("Restarting RobOto")
        await self.stop()
        try:
            c_p = psutil.Process(os.getpid())
            for handler in c_p.open_files() + c_p.connections():
                os.close(handler.fd)
        except Exception as c_e:
            print(c_e)
        if update_req:
            print("Installing Requirements...")
            os.system("pip3 install -U pip && pip3 install -r requirements.txt")
        os.execl(sys.executable, sys.executable, '-m', 'RobOto')
        sys.exit()
