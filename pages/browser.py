"""Run the shared application inside the Pages worker."""

import json
import time
from concurrent.futures import Executor, Future

from js import merchRequest
from pyodide.ffi import JsException

from application import Application, RouteNotFound
from ledger import Ledger
from market import Market


class WorkerExecutor(Executor):
    def __init__(self, max_workers):
        pass

    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as error:
            future.set_exception(error)
        return future


class BrowserMarket(Market):
    def save(self, key, payload):
        # A visitor's saved journal contains no bulk market data.
        self.cache[key] = int(time.time()), payload
        return payload


def request_json(url):
    try:
        return json.loads(merchRequest(url))
    except JsException as error:
        raise OSError(str(error)) from error


ledger = Ledger("/tmp/merch.sqlite3")
app = Application(ledger, BrowserMarket(ledger, request_json, WorkerExecutor))


def route(path, body):
    try:
        result = app.get(path) if body is None else app.post(path, json.loads(body))
        return json.dumps({"result": result}, ensure_ascii=False, allow_nan=False)
    except RouteNotFound:
        return json.dumps({"error": "Endereço inexistente."})
    except (ValueError, TypeError) as error:
        return json.dumps({"error": str(error)}, ensure_ascii=False)
