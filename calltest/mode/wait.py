"""
Incoming call that waits until it's ringing, then hangs up.
"""

import anyio

from . import BaseInWorker
from . import wait_ringing

import logging
logger = logging.getLogger(__name__)

class Worker(BaseInWorker):
    async def __call__(self):
        async with self.in_call() as icm:

            await self.connect_in(icm, handle_answer=False)

