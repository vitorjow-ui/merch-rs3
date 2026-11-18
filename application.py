"""Shared application routes for the local server and the browser worker."""

import csv
import io
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from ledger import MAX_QUANTITY, integer
from opportunities import craft_projection, decision_board, operation_metrics


class RouteNotFound(LookupError):
    pass


class Application:
    def __init__(self, ledger, market):
        self.ledger = ledger
        self.market = market
        self.guide_cache = {}

    def get(self, address):
        url = urlsplit(address)
        path = url.path
        if path == "/api/state":
            return self.ledger.state()
        if path in {"/api/market", "/api/opportunities"}:
            filters = {key: values[0] for key, values in parse_qs(url.query).items()}
            if path == "/api/market":
                return self.market.snapshot(filters)
            return decision_board(self.market, self.ledger, filters)
        if path.startswith("/api/history/"):
            item_id = integer(path.split("/")[-1], "o ID do item")
            return self.market.history(item_id)
        if path.startswith("/api/guide/"):
            item_id = integer(path.split("/")[-1], "o ID do item")
            return self.guide(item_id)
        if path == "/api/exports/trades.csv":
            return self.export()
        raise RouteNotFound(path)

    def post(self, path, data):
        if not isinstance(data, dict):
            raise ValueError("Envie um objeto JSON.")
        ledger = self.ledger
        if path == "/api/settings":
            ledger.settings(data)
        elif path == "/api/offers":
            ledger.new_offer(data, self.market.catalogue())
        elif path.startswith("/api/offers/"):
            offer_id = integer(path.split("/")[-1], "o ID da oferta")
            ledger.change_offer(offer_id, data)
        elif path == "/api/watchlist":
            item_id = integer(data.get("id"), "o ID do item")
            ledger.watch(item_id, data.get("enabled") is True)
        elif path == "/api/calculate":
            buy = integer(data.get("buy"), "a compra")
            sell = integer(data.get("sell"), "a venda")
            qty = integer(data.get("qty"), "a quantidade", maximum=MAX_QUANTITY)
            instant = integer(data["instant"], "a saída instantânea") if data.get("instant") else None
            return operation_metrics(buy, sell, qty, data.get("exempt") is True, instant)
        elif path == "/api/craft-projection":
            return craft_projection(data)
        else:
            raise RouteNotFound(path)
        return ledger.state()

    def export(self):
        contents = io.StringIO()
        writer = csv.writer(contents, delimiter=";")
        writer.writerow(["Data UTC", "Item", "Lado", "Quantidade", "Preço unitário (GP)",
                         "Tarifa total (GP)", "Custo (GP)", "Lucro realizado (GP)"])
        for fill in self.ledger.state()["fills"]:
            selling = fill["side"] == "sell"
            profit = fill["qty"] * int(fill["price"]) - int(fill["fee"]) - int(fill["cost"]) if selling else ""
            name = fill["name"]
            if name.lstrip().startswith(("=", "+", "-", "@")):
                name = "'" + name
            writer.writerow([datetime.fromtimestamp(fill["created"], timezone.utc).isoformat(), name,
                             "Venda" if selling else "Compra", fill["qty"], fill["price"],
                             fill["fee"], fill["cost"], profit])
        return contents.getvalue()

    def guide(self, item_id):
        now = time.time()
        cached = self.guide_cache.get(item_id)
        if cached and now - cached[0] < 900:
            return cached[1]
        url = f"https://api.weirdgloop.org/exchange/history/rs/latest?id={item_id}"
        try:
            record = self.market.request_json(url).get(str(item_id), {})
            result = {"price": str(record["price"]) if record.get("price") is not None else None,
                      "time": record.get("timestamp")}
        except (OSError, TimeoutError, ValueError, AttributeError) as error:
            print(f"Preço-guia RS3 /{item_id}: {error}", flush=True)
            return cached[1] if cached else {"price": None, "time": None}
        if len(self.guide_cache) >= 200:
            self.guide_cache.clear()
        self.guide_cache[item_id] = now, result
        return result
