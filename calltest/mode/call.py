# DTMF: exchange calls, 

import anyio

from . import BaseDualWorker
from . import wait_ringing

import logging
logger = logging.getLogger(__name__)

class Worker(BaseDualWorker):
    async def __call__(self):
        async with self.dual_call() as (icm, ocm):
            # Coordinate between the tasks; DTMF sending must wait
            # until the receiver is listening
            sync1 = anyio.create_event()
            sync3 = anyio.create_event()
            sync2 = anyio.create_event()

            async def run_in():
                await self.connect_in(icm, handle_answer=False)
                await sync1.wait()
                await sync3.set()

            async def run_out():
                await self.connect_out(ocm, handle_answer=False)
                await wait_ringing(ocm)
                await sync1.set()
                await sync3.wait()
                
            await icm.taskgroup.spawn(run_in)
            await ocm.taskgroup.spawn(run_out)
            await sync3.wait()

