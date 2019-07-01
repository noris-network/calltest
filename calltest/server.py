import anyio
import asyncari
from .util import attrdict
from typing import Optional, Any
from functools import partial
from quart_trio import QuartTrio as Quart
from hypercorn.config import Config as HyperConfig
from hypercorn.trio import serve as hyper_serve
from quart.logging import create_serving_logger
from quart import jsonify

async def run (  # type: ignore
    self, # app
    host: str = "127.0.0.1",
    port: int = 5000,
    debug: Optional[bool] = None,
    use_reloader: bool = True,
    ca_certs: Optional[str] = None,
    certfile: Optional[str] = None,
    keyfile: Optional[str] = None,
    **kwargs: Any,
) -> None:
    """Run this application.
    """
    config = HyperConfig()
    config.access_log_format = "%(h)s %(r)s %(s)s %(b)s %(D)s"
    config.access_logger = create_serving_logger()  # type: ignore
    config.bind = [f"{host}:{port}"]
    config.ca_certs = ca_certs
    config.certfile = certfile
    if debug is not None:
        config.debug = debug
    config.error_logger = config.access_logger  # type: ignore
    config.keyfile = keyfile
    config.use_reloader = use_reloader

    scheme = "http" if config.ssl_enabled is None else "https"

    await hyper_serve(self, config)


async def serve(cfg, checks):
    ast = cfg.asterisk
    url = "http://%s:%d/" % (ast.host,ast.port)

    stats = {}
    app = Quart("calltest.server", root_path="/tmp")
    @app.route("/")
    async def index():
        s = attrdict(details=stats)
        s.fail = list(k for k,v in stats.items() if v.fail_count >= checks[k].test['fail'])
        s.warn = list(k for k,v in stats.items() if checks[k].test['fail'] > v.fail_count >= checks[k].test['warn'])
        s.n_fail = len(s.fail)
        s.n_warn = len(s.warn)
        return jsonify(s)

    async def updated(call):
        stats[call.name] = call.state

    async with asyncari.connect(url, ast.app, username=ast.username, password=ast.password) as client:
        async with anyio.create_task_group() as tg:
            await tg.spawn(partial(run, app, **cfg.server, debug=True))
            for c in checks.values():
                if c.test['skip']:
                    continue
                await tg.spawn(partial(c.run, client, updated=updated))

