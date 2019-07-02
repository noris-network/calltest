#
# calltest data model

import anyio
import importlib

from contextlib import asynccontextmanager, AsyncExitStack
from functools import partial
import traceback

from .util import attrdict, combine_dict
from .default import DEFAULT

import logging
logger = logging.getLogger(__name__)

class Link:
    def __init__(self, name, channel, number, prio=0, **kw):
        self.name = name
        self.channel = channel
        self.number = number
        self._prio = prio
        for k,v in kw.items():
            setattr(self,k,v)
        self.lock = anyio.create_lock()

    def __repr__(self):
        return "<%s:%s>" % (self.__class__.__name__,self.name)

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if isinstance(other,Link):
            other = other.name
        return self.name == other

    @property
    def prio(self):
        """Relative priority. Used for deadlock avoidance."""
        return (self._prio, self.name)


@asynccontextmanager
async def locked_links(*locks):
    """
    Given a number of :cls:`Link` objects, lock them all in an order that
    prevents deadlocks.

    Usage::
        async with lock(src, dst):
            await process(src,dst)
    """
    async with AsyncExitStack() as s:
        for l in sorted(locks, key=lambda x: x.prio):
            await s.enter_async_context(l.lock)
        yield s


def gen_links(cfg):
    res = attrdict()
    default = cfg['links'][DEFAULT]
    for k,v in cfg['links'].items():
        if k == DEFAULT:
            continue
        v = combine_dict(v, default)
        l = Link(name=k, **v)
        res[k] = l
    return res

class Call:
    error = None
    err_count = 0

    def __init__(self, links, name, *, timeout, mode="dtmf", info="-", src=None, dst=None, **kw):
        self.name = name
        self.mode = importlib.import_module("calltest.mode."+mode).Worker
        self.src = links[src] if src is not None else None
        self.dst = links[dst] if dst is not None else None
        self.info = info
        self.timeout = timeout
        for k,v in kw.items():
            setattr(self,k,v)
        self.lock = anyio.create_lock()

    def __repr__(self):
        return "<%s:%s>" % (self.__class__.__name__,self.name)

    async def __call__(self, client):
        runner = self.mode(client, self)
        async with runner.lock:
            async with anyio.fail_after(self.timeout):
                await runner()

    async def run(self, client, updated=None):
        """
        Background task runner for this test, stores exceptions.

        :param updated: Callback that's fired when this test's status
                        changes.
        The accumulated test status is in the ``state`` attribute.
        """
        if updated is None:
            async def updated():
                pass
        else:
            updated = partial(updated, self)

        self.state = state = attrdict(
            total_run = 0, # total
            total_fail = 0, # total

            running = False,
            last_exc = None,
            fail_map = [], # last 20 or whatever
            fail_count = 0,
        )

        while True:
            state.running = True
            await updated()
            try:
                await self(client)
            except Exception as exc:
                state.exc = traceback.format_exc()
                state.total_fail += 1
                state.fail_count += 1
                state.fail_map.append(True)
            else:
                state.fail_count = 0 
                state.fail_map.append(False)
            finally:
                state.total_run += 1
                state.running = False

                if any(state.fail_map):
                    del state.fail_map[:-20]
                else:
                    state.fail_map = []
                    # zero out after 20 successes in sequence

            await updated()
            if state.fail_count:
                await anyio.sleep(self.test['retry'])
            else:
                await anyio.sleep(self.test['repeat'])


def gen_calls(links, cfg):
    res = attrdict()
    default = cfg['calls'][DEFAULT]
    for k,v in cfg['calls'].items():
        if k == DEFAULT:
            continue
        v = combine_dict(v, default)
        c = Call(links, name=k, **v)
        res[k] = c
    return res


