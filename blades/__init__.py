"""
A blade is a generic aiohttp server wrapper that insure different endpoints.

Blades are sub-classed with different endpoint and properties depending on the
specific task.
"""

import dataclasses
import time
import argparse
import asyncio
from aiohttp import web
import json
import logging

"""
here blade is 1 blade configuration eg

  - name: scraper_one
    blade: scraper
    managed: true
    host: 127.0.0.1
    port: 8002
    venv: "./venvs/scraper_one"

weheras topology is the complete configuration file

"""

async def start_blade(blade, topology):
    # If params are provided, set them in the app's shared state
    app['topology'] = topology
    app['blade'] = blade
    await web._run_app(
        app, 
        host=blade['host'], 
        port=blade['port'], 
        print=lambda *args, **kwargs: None
    )

def app_serializer(obj):
    """This is used to return a full status of the app on /"""
    # Converts any non-serializable object to its string representation
    if isinstance(obj, web.Application):
        # Perform specific serialization for aiohttp web.Application, if needed
        # For example, return a dict of routes. This is just a placeholder.
        return {"routes": list(obj.router.routes())}
    elif callable(obj):
        # Convert callables to their string representation
        return (
            f"Callable: {obj.__name__}" 
                if hasattr(obj, '__name__') 
                else "Unnamed callable"
            )
    else:
        # Default: convert to string
        return str(obj)


"""
Overclassing the blades is done by importing their app definition and 
overwriting it here.

Each blade should be launched using this script.
"""
async def load_intent(request):
    """
    The intent endpoint is used by the orchestrator to inform intent and
    retrieve feedback from the blade

    This wrapper is responsible for managing the internal's blade version and
    propagates the call to the blade's internal `load_intent` function.
    """
    if request.app.get('load_intent', None):
        try:
            # we define the interface using request.app internal dict 
            return await request.app['load_intent'](request)
        except:
            pass
    # if there is no overwrite we simply return the blade's status
    return web.json_response(request.app['blade'])

async def status(request):
    """Returns a json of the current app's memory including tasks & conf"""
    app_json = json.dumps(dict(request.app), default=app_serializer)
    return web.Response(text=app_json, content_type='application/json')

def dataclass_to_dict(obj):
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


class JsonFormatter(logging.Formatter):
    def __init__(self, *__args__, **kwargs):
        self.host = kwargs["host"]

    LEVEL_MAP = {
        logging.INFO: 1,
        logging.DEBUG: 2,
        logging.ERROR: 3,
        logging.CRITICAL: 4,
    }

    def format(self, record):
        """
        Complex & tries to do multiple things at the same time.
        Goal is to be able to log what we want where we want.

        So this is a logging router

        - LogTest compatible (custom logging state) (logtest field, should not
                                                     be sent to OVH)
        - should be OVH format compatible (base_log_record + _details) (not 
                                                                        impl atm)
        - with a PrintOnly field (print only in the logs)

        This does not handle splitting out the logs appropriately ATM and would
        require further tinkering to send data to OVH.
            - create multiple log stream
                -- OVH (with _details and no logtest and printonly)
                -- logtest (logtest and printonly)

        so OVH is ignored atm in favor of Grafana & Prom that do not rely on 
        logs, so no additional logstream is required.
        """
        logtest:dict = getattr(record, 'logtest', {})

        if record.exc_info:
            # does not save the error
            logtest['exception'] = self.formatException(record.exc_info)

        base_log_record = {
            "host": self.host,
            "full_message": record.getMessage(),
            "timestamp": time.time(),
            "level": self.LEVEL_MAP.get(record.levelno, 1),
            "_details": {}, # reserved for OVH
            "logtest": logtest
        }

        printonly = getattr(record, 'printonly', None)
        if printonly:
            base_log_record['printonly'] = printonly

        return json.dumps(base_log_record, default=dataclass_to_dict)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Exorde blade manager"
    )
    parser.add_argument(
        "--blade", 
        type=json.loads, 
        default={}, 
        help="JSON string of blade configuration"
    )
    parser.add_argument(
        "--topology", 
        type=json.loads, 
        default={}, 
        help="JSON string of topology"
    )
    parser.add_argument(
        "--jlog", 
        action="store_true",
        help="Format logs in JSON"
    )
    args = parser.parse_args()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(JsonFormatter(host="{}:{}".format(
        args.blade['host'], args.blade['port']
    )))

    # Configure logger for 'blade'
    blade_logger = logging.getLogger('blade')
    # Set the minimum log level
    blade_logger.setLevel(logging.DEBUG)  

    # Determine the log format based on the --jlog argument
    if args.jlog:
        handler = stream_handler
    else:
        handler = logging.StreamHandler()
    # Add the handler to the 'blade' logger
    blade_logger.addHandler(handler)
    blade_logger.info('Hello World !')

    # Dynamically load the appropriate aiohttp app from the subblade
    mod = __import__(args.blade['blade'], fromlist=['app'])
    app = getattr(mod, 'app')
    app['blade'] = args.blade
    app['topology'] = args.topology
    app.router.add_get('/', status)
    app.router.add_post('/', load_intent)
    asyncio.run(start_blade(args.blade, args.topology))
