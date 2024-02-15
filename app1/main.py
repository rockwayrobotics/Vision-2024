import asyncio
import logging
import os
from pathlib import Path
import signal
import sys

from . import vision, web
from .net_tables import NT
from .utils import log_uncaught

logging.basicConfig(level=logging.DEBUG)


#-----------------------------

class Core:
    def __init__(self):
        self.log = logging.getLogger('core')
        self.task = None

    def running(self):
        return not self._shutdown.is_set()

    def shutdown(self):
        return self._shutdown.wait()

    async def shut_down(self):
        self.log.warning('shutting down')
        try:
            self._shutdown.set()

            await self.web.stop()

            if self.task:
                self.task.cancel()

        except Exception:
            self.log.exception('shutdown')
        finally:
            await asyncio.sleep(0.3)    # give things time to exit

            tasks = asyncio.all_tasks()
            if len(tasks) > 1:
                self.log.debug('tasks (%s):\r%s', len(tasks),
                    '\n'.join(f'#{i}: {x}' for (i, x) in enumerate(tasks))
                )
                await asyncio.sleep(1)
                self.log.info('dirty shutdown')
                sys.exit(1)

            self.log.info('clean shutdown')


    def handle_sig(self, *_sig):
        self.log.warning('terminate!')

        vision.output.running = False
        vision.output.ready.set()

        # print(dir(self.loop))
        self.loop.create_task(self.shut_down())


    async def run(self, args):
        self.task = asyncio.create_task(self._run(args))
        await self.task

    @log_uncaught
    async def _run(self, args):
        self.loop = asyncio.get_running_loop()
        self._shutdown = asyncio.Event()

        vision.output.ready = asyncio.Event()
        for sig in [signal.SIGINT, signal.SIGTERM]:
            self.loop.add_signal_handler(sig, self.handle_sig)
            # self.log.debug('installed handler for', sig)

        self.web = await web.start(args)

        try:
            await vision.run(args, web.send_all)
        finally:
            await self.web.stop()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--debug', action='store_true')
    parser.add_argument('--nodraw', action='store_false')
    parser.add_argument('-c', '--cam', type=int, default=0)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('-r', '--res', default='640x480')
    parser.add_argument('--dec', type=int, default=2)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--fps', type=float, default=60.0)
    # parser.add_argument('--time', type=float, default=10.0)
    parser.add_argument('--team', type=int, default=8089)
    parser.add_argument('--mocknt', action='store_true')

    args = parser.parse_args()

    if not args.mocknt:
        NT.start(args)

    core = Core()
    try:
        asyncio.run(core.run(args))
        # web.run_app(app)
    except (SystemExit, KeyboardInterrupt):
        pass
    finally:
        if not args.mocknt:
            NT.running.set(False)
            NT.stop()

