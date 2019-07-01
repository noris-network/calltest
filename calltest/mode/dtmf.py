# DTMF: exchange calls, 

import anyio

from . import BaseDualWorker
from . import ExpectDTMF, wait_answered, random_dtmf

import logging
logger = logging.getLogger(__name__)

class Worker(BaseDualWorker):
    async def __call__(self):
        async with self.dual_call() as (icm, ocm):
            ok = anyio.create_event()
            sync = anyio.create_event()
            sync2 = anyio.create_event()

            in_dtmf = random_dtmf()
            out_dtmf = random_dtmf()

            async def run_in():
                logger.debug("IN A")
                await icm.channel.ring()
                logger.debug("IN C")
                await anyio.sleep(1)
                logger.debug("IN E")
                await icm.channel.answer()
                logger.debug("IN G")
                await wait_answered(icm)
                logger.debug("IN I")
                await sync.wait()
                logger.debug("IN K")
                await icm.channel.sendDTMF(dtmf=in_dtmf)
                logger.debug("IN M")
                await ExpectDTMF(icm, dtmf=out_dtmf, evt=sync2)
                logger.debug("IN O")
                await ok.set()
                logger.debug("IN Q")

            async def run_out():
                logger.debug("OUT A")
                await wait_answered(ocm)
                logger.debug("OUT C")
                await anyio.sleep(1)
                logger.debug("OUT E")
                await ExpectDTMF(ocm, dtmf=in_dtmf, evt=sync)
                logger.debug("OUT G")
                await sync2.wait()
                logger.debug("OUT I")
                await ocm.channel.sendDTMF(dtmf=out_dtmf)
                logger.debug("OUT K")
                await ok.wait()
                logger.debug("OUT M")
                
            await icm.taskgroup.spawn(run_in)
            await ocm.taskgroup.spawn(run_out)
            await ok.wait()

