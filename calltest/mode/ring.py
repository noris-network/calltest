"""
Outgoing call that simply rings the other side, then hangs up.
"""

import anyio

from . import BaseOutWorker
from . import wait_ringing

import logging
logger = logging.getLogger(__name__)

class Worker(BaseOutWorker):
    async def __call__(self):
        async with self.out_call() as ocm:

            await self.connect_out(ocm, handle_ringing=True)

