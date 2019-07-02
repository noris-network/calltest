# DTMF: exchange calls, 

import anyio

from . import BaseOutWorker
from . import wait_ringing
from . import SyncPlay

import logging
logger = logging.getLogger(__name__)

class Worker(BaseOutWorker):
    async def __call__(self):
        async with self.out_call() as ocm:

            await self.connect_out(ocm)
            out = self.call.audio['src_out']
            if out is not None:
                await SyncPlay(ocm, out)
                
