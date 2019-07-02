# command line interface

import os
import sys
import asyncclick as click
from pprint import pprint
import json
from functools import partial
from collections.abc import Mapping

import anyio
import asyncari

from .util import attrdict, combine_dict
from .model import gen_links, gen_calls
from .default import CFG

import logging
from logging.config import dictConfig

logger = logging.getLogger(__name__)


def cmd():
    """
    The main command entry point, as declared in ``setup.py``.
    """
    try:
        main(standalone_mode=False)
    except click.exceptions.MissingParameter as exc:
        print("You need to provide an argument '%s'.\n" % (exc.param.name.upper()), file=sys.stderr)
        print(exc.cmd.get_help(exc.ctx), file=sys.stderr)
        sys.exit(2)
    except click.exceptions.UsageError as exc:
        try:
            s = str(exc)
        except TypeError:
            logger.exception(repr(exc), exc_info=exc)
        else:
            print(s, file=sys.stderr)
        sys.exit(2)
    except click.exceptions.Abort:
        print("Aborted.", file=sys.stderr)
        pass
    except EnvironmentError as exc:
        print(type(exc).__name__ + ":", *exc.args, file=sys.stderr)
        sys.exit(1)
    except BaseException as exc:
        raise
        # print(exc)
        # sys.exit(1)


@click.group()
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Enable debugging. Use twice for more verbosity.",
)
@click.option(
    "-l", "--log", multiple=True, help="Adjust log level. Example: '--log asyncserf.actor=DEBUG'."
)
@click.option(
    "-q", "--quiet", count=True, help="Disable debugging. Opposite of '--verbose'."
)
@click.option("-c", "--cfg", type=click.File("r"), default=None, help="Configuration file (YAML).")
@click.option("-C", "--conf", multiple=True, help="Override a config entry. Example: '-C server.bind_default.port=57586'")
@click.pass_context
async def main(ctx, verbose, quiet, log, cfg, conf):
    """
    "calltest" periodically runs calls to verify that a phone
    line is operational.

    See the "help" subcommand for details.
    """
    ctx.ensure_object(attrdict)
    ctx.obj.debug = max(verbose - quiet + 1, 0)
    
    if cfg:
        logger.debug("Loading %s", cfg)
        import yaml

        ctx.obj.cfg = combine_dict(yaml.safe_load(cfg), CFG, cls=attrdict)
        cfg.close()
    else:
        ctx.obj.cfg = CFG

    # One-Shot-Hack the config file.
    for k in conf:
        try:
            k,v = k.split('=')
        except ValueError:
            v = NotGiven
        else:
            try:
                v = eval(v)
            except Exception:
                pass
        c = ctx.obj.cfg
        *sl, s = k.split('.')
        for k in sl:
            c = c[k]
        if v is NotGiven:
            del c[s]
        else:
            c[s] = v

    # Configure logging. This is a somewhat arcane art.
    lcfg = ctx.obj.cfg.logging
    lcfg['root']['level'] = "DEBUG" if verbose > 2 else "INFO" if verbose > 1 else "WARNING" if verbose else "ERROR"
    for k in log:
        k,v = k.split('=')
        lcfg['loggers'].setdefault(k, {})['level'] = v
    dictConfig(lcfg)
    logging.captureWarnings(verbose > 0)

    ctx.obj.links = gen_links(ctx.obj.cfg)
    ctx.obj.calls = gen_calls(ctx.obj.links, ctx.obj.cfg)


@main.command(short_help="Import the debugger",
        help="Imports PDB and then continues to process arguments.")
@click.argument("args", nargs=-1)
async def pdb(args):  # safe
    import pdb

    pdb.set_trace()  # safe
    if not args:
        return
    return await main.main(args)

@main.command()
@click.option("-l","--list","as_list", is_flag=True, help="List testcases")
@click.argument("checks", nargs=-1)
@click.pass_obj
async def run(obj, checks, as_list):
    """
    Run a one-shot call.
    """
    if not checks:
        checks = list(k for k,v in obj.calls.items() if as_list or not v.test.skip)
    if not checks:
        raise click.UsageError("No tests known. Missing config file?")

    if as_list:
        for c in checks:
            c = obj.calls[c]
            print(c.name, "m" if c.test.skip else "-", c.info, sep="\t")
        return

    ast = obj.cfg.asterisk
    url = "http://%s:%d/" % (ast.host,ast.port)
    async with asyncari.connect(url, ast.app, username=ast.username, password=ast.password) as client:
        client._calltest_config = obj.cfg
        async with anyio.create_task_group() as tg:
            for c in checks:
                await tg.spawn(obj.calls[c], client)

@main.command()
@click.pass_obj
async def server(obj):
    """
    Run a server with all checks.
    """
    from calltest.server import serve
    await serve(obj.cfg, obj.calls)

@main.command()
@click.pass_obj
async def dumpcfg(obj):
    """emit the current configuration as a YAML file."""
    import yaml
    yaml.safe_dump(obj.cfg, stream=sys.stdout)
