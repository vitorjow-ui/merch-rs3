"""Dados públicos e estimativas de flip para o mercado principal de RS3."""

import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from urllib.request import Request, urlopen

from ledger import MAX_GP, economics, is_bond, tax

API = "https://prices.runescape.wiki/api/v2/rs"
USER_AGENT = "SistemaMerchRS3/1.0 (local Grand Exchange tracker for RuneScape 3)"
FEEDS = {"mapping": 86400, "latest": 180, "5m": 180, "1h": 600}


def get_json(url):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=8) as response:
        return json.load(response)


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value <= MAX_GP


class Market:
    def __init__(self, ledger, request_json=get_json, executor=ThreadPoolExecutor):
        self.ledger = ledger
        self.request_json = request_json
        self.executor = executor
        self.lock = threading.RLock()
        with closing(ledger.connect()) as db:
            self.cache = {key: (timestamp, json.loads(payload)) for key, timestamp, payload in
                          db.execute("SELECT key, fetched, payload FROM feed_cache")}
        self.errors = {}

    def save(self, key, payload):
        stamp = int(time.time())
        with self.ledger.write() as db:
            db.execute("""
                INSERT INTO feed_cache(key, fetched, payload) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET fetched=excluded.fetched, payload=excluded.payload
            """, (key, stamp, json.dumps(payload, separators=(",", ":"), ensure_ascii=False)))
        self.cache[key] = stamp, payload
        return payload

    def catalogue(self):
        return self.cache.get("mapping", (0, {}))[1]

    def fetch_feed(self, key):
        payload = self.request_json(f"{API}/{key}")
        if key == "mapping" and isinstance(payload, list):
            catalogue = {str(item["id"]): item for item in payload if isinstance(item, dict)
                         and type(item.get("id")) is int and isinstance(item.get("name"), str)
                         and type(item.get("members")) is bool}
            if catalogue:
                return catalogue
        if key != "mapping" and isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            if key == "latest" or type(payload.get("timestamp")) is int:
                return payload
        raise ValueError(f"Formato inesperado em /{key}")

    def refresh(self, force=False):
        with self.lock:
            now = time.time()
            missing = [key for key, ttl in FEEDS.items()
                       if now - self.cache.get(key, (0, None))[0]
                       >= (30 if force and key in {"latest", "5m"} else ttl)
                       and now - self.errors.get(key, (0, None))[0] >= 30]
            if not missing:
                return
            with self.executor(max_workers=len(missing)) as pool:
                requests = {key: pool.submit(self.fetch_feed, key) for key in missing}
                for key, future in requests.items():
                    try:
                        payload = future.result()
                    except (OSError, TimeoutError, ValueError) as error:
                        print(f"Feed RS3 /{key}: {error}", flush=True)
                        self.errors[key] = (int(time.time()), str(error))
                    else:
                        self.save(key, payload)
                        self.errors.pop(key, None)

    def decision_data(self, force=False):
        self.refresh(force)
        with self.lock:
            now = int(time.time())
            latest_at, latest = self.cache.get("latest", (0, {}))
            five = self.cache.get("5m", (0, {}))[1]
            hour = self.cache.get("1h", (0, {}))[1]
            wanted = [("1h", now // 3600 * 3600 - 3600 * i) for i in range(1, 7)]
            if five.get("timestamp") and 0 <= now - five["timestamp"] <= 1200:
                wanted += [("5m", five["timestamp"] - 300 * i) for i in range(6)]
            old = self.cache.get("decision-windows", (0, {}))[1]
            cached = {key: old[key] for period, start in wanted
                      if (key := f"{period}:{start}") in old}
            for period, record in (("1h", hour), ("5m", five)):
                if (period, record.get("timestamp")) in wanted:
                    cached[f"{period}:{record['timestamp']}"] = record
            missing = [(period, start) for period, start in wanted if f"{period}:{start}" not in cached
                       and now - self.errors.get(f"{period}:{start}", (0, None))[0] >= 60]
            if missing and latest_at and "latest" not in self.errors:
                with self.executor(max_workers=2) as pool:
                    for key, record in pool.map(self.decision_window, missing):
                        if record:
                            cached[key] = record
                            self.errors.pop(key, None)
                        else:
                            self.errors[key] = (now, "Janela indisponível")
            if cached.keys() != old.keys():
                self.save("decision-windows", cached)
            wanted_keys = {f"{period}:{start}" for period, start in wanted}
            self.errors = {key: value for key, value in self.errors.items()
                           if key in FEEDS or key in wanted_keys}
            return {
                "now": now, "latestAt": latest_at,
                "online": bool(latest_at and now - latest_at <= 360 and "latest" not in self.errors),
                "catalogue": self.catalogue(), "latest": latest.get("data", {}),
                "hourly": [cached[key] for period, start in wanted
                           if period == "1h" and (key := f"{period}:{start}") in cached],
                "recent": [cached[key] for period, start in wanted
                           if period == "5m" and (key := f"{period}:{start}") in cached],
                "latestHour": wanted[0][1],
            }

    def decision_window(self, request):
        period, start = request
        key = f"{period}:{start}"
        try:
            result = self.request_json(f"{API}/{period}?timestamp={start}")
            if result.get("timestamp") == start and isinstance(result.get("data"), dict) and result["data"]:
                return key, result
        except (OSError, ValueError, AttributeError) as error:
            print(f"Feed RS3 /{key}: {error}", flush=True)
        return key, None

    def snapshot(self, filters):
        self.refresh()
        state = self.ledger.state()
        with self.lock:
            latest_at, latest = self.cache.get("latest", (0, {}))
            five = self.cache.get("5m", (0, {}))[1]
            hour = self.cache.get("1h", (0, {}))[1]
            catalogue = self.catalogue()
            errors = sorted(key for key in self.errors if key in FEEDS)
        now = int(time.time())
        unavailable = not latest_at or not catalogue or not five or not hour
        degraded = bool(errors) or now - latest_at > 360
        meta = {
            "status": "offline" if unavailable else "cached" if degraded else "online",
            "lastSync": latest_at, "errors": errors, "catalogueCount": len(catalogue),
            "fiveTime": five.get("timestamp"), "hourTime": hour.get("timestamp"),
        }
        search = filters.get("q", "").strip().casefold()
        mode = filters.get("mode", "eligible")
        membership = filters.get("membership", "all")
        selected = filters.get("item")
        watchlist = set(state["watchlist"])
        names = {}
        for item in catalogue.values():
            normalized = item["name"].casefold()
            names[normalized] = names.get(normalized, 0) + 1
        rows = []
        for key, item in catalogue.items():
            if selected and selected != key:
                continue
            if mode == "watch" and item["id"] not in watchlist:
                continue
            if (membership == "free" and item["members"]) or (membership == "members" and not item["members"]):
                continue
            if search and search not in item["name"].casefold() and search != key:
                continue
            quote = latest.get("data", {}).get(key) or {}
            recent = five.get("data", {}).get(key) or {}
            baseline = hour.get("data", {}).get(key) or {}
            alias = f"manual:{item['name'].casefold()}" if names[item["name"].casefold()] == 1 else None
            row = assess(item, quote, recent, baseline, now, state, meta, alias)
            if mode != "eligible" or row["eligible"]:
                rows.append(row)
        sort = filters.get("sort")
        if sort == "roi":
            rows.sort(key=lambda r: (not r["eligible"], -(r["roi"] or 0), r["name"]))
        elif sort == "volume":
            rows.sort(key=lambda r: (-min(r["hourHighVolume"], r["hourLowVolume"]), r["name"]))
        elif sort == "name":
            rows.sort(key=lambda r: r["name"].casefold())
        else:
            rows.sort(key=lambda r: (not r["eligible"], -int(r["profit"] or 0),
                                     -int(r["margin"] or 0), r["name"]))
        try:
            page = max(1, min(1000, int(filters.get("page", "1"))))
        except ValueError:
            page = 1
        start = (page - 1) * 30
        return {"market": meta, "items": rows[start:start + 30], "count": len(rows), "page": page}

    def history(self, item_id):
        key = f"history:{item_id}"
        with self.lock:
            now = time.time()
            cached = self.cache.get(key)
            if cached and now - cached[0] < 600:
                return {"points": cached[1], "cached": False}
        try:
            payload = self.request_json(f"{API}/timeseries?id={item_id}&lookback=24h")
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ValueError("Formato inesperado no histórico")
            points = [{
                "time": row["timestamp"], "high": row.get("avgHighPrice"), "low": row.get("avgLowPrice"),
            } for row in payload["data"] if isinstance(row, dict) and type(row.get("timestamp")) is int]
            points.sort(key=lambda point: point["time"])
        except (OSError, TimeoutError, ValueError) as error:
            print(f"Histórico RS3 /{item_id}: {error}", flush=True)
            return {"points": cached[1] if cached else [], "cached": True}
        with self.lock:
            if key not in self.cache:
                histories = [(entry[0], name) for name, entry in self.cache.items() if name.startswith("history:")]
                if len(histories) >= 50:
                    _, oldest = min(histories)
                    with self.ledger.write() as db:
                        db.execute("DELETE FROM feed_cache WHERE key=?", (oldest,))
                    del self.cache[oldest]
            return {"points": self.save(key, points), "cached": False}


def assess(item, quote, five, hour, now, state, meta, alias=None):
    key = str(item["id"])
    low, high = quote.get("low"), quote.get("high")
    low_at, high_at = quote.get("lowTime"), quote.get("highTime")
    one_high, one_low = hour.get("avgHighPrice"), hour.get("avgLowPrice")
    five_high, five_low = five.get("avgHighPrice"), five.get("avgLowPrice")
    buy = max(low, math.ceil(five_low)) if positive(low) and positive(five_low) else low
    sell = min(high, math.floor(five_high)) if positive(high) and positive(five_high) else high
    data_issue = None
    volume_high = hour.get("highPriceVolume") or 0
    volume_low = hour.get("lowPriceVolume") or 0
    exempt = is_bond(item["name"])
    if meta["status"] != "online":
        data_issue = "Feed indisponível ou com dados em cache"
    elif not all(positive(value) for value in (low, high, low_at, high_at)):
        data_issue = "Falta execução de um dos lados"
    elif (max(now - low_at, now - high_at) > 1800 or max(low_at, high_at) > now + 60
          or abs(low_at - high_at) > 1200):
        data_issue = "Preços antigos ou de horários muito distantes"
    elif now - meta["fiveTime"] > 1200 or now - meta["hourTime"] > 10800:
        data_issue = "Janelas de volume desatualizadas"
    elif not all(positive(value) for value in (five_high, five_low, one_high, one_low)):
        data_issue = "Janela de 5 min ou 1 h sem preço dos dois lados"
    elif min(volume_high, volume_low) < 20:
        data_issue = "Menos de 20 unidades em um lado da janela de 1 h"
    elif sell - tax(sell, exempt) <= buy:
        data_issue = "Margem líquida ausente com preços conservadores"
    elif math.floor(one_high) - tax(math.floor(one_high), exempt) <= math.ceil(one_low):
        data_issue = "A janela de 1 h não confirma a margem líquida"
    elif not positive(item.get("limit")):
        data_issue = "Buy limit indisponível"
    elif item["members"] and state["settings"]["profile"] == "free":
        data_issue = "Item exclusivo para membros"
    windows = [state["windows"].get(item_key, {}) for item_key in (key, alias)]
    position_limit = int(state["settings"]["capital"]) * state["settings"]["allocation"] // 100
    pending = sum(state["pendingBuys"].get(item_key, 0) for item_key in (key, alias))
    limit = item.get("limit") or 0
    limit_left = max(0, limit - sum(window.get("used", 0) for window in windows) - pending)
    liquidity = min(volume_high, volume_low) // 20
    quantity = 0
    if not data_issue:
        exposure = sum(int(state["exposure"].get(item_key, 0)) for item_key in (key, alias))
        budget = max(0, min(int(state["available"]), position_limit - exposure))
        quantity = min(budget // buy, limit_left, liquidity)
        if state["slots"] >= (8 if state["settings"]["profile"] == "members" else 3):
            quantity = 0
    result = economics(buy, sell, quantity, exempt) if positive(buy) and positive(sell) else None
    if not data_issue and not quantity:
        reason = "Sem quantidade disponível pelo caixa, limites ou slots"
    else:
        reason = data_issue or "Preços recentes e margem confirmada na janela de 1 h"
    return {
        "id": item["id"], "name": item["name"], "members": item["members"],
        "limit": limit, "limitLeft": limit_left,
        "limitReset": max((window.get("reset", 0) for window in windows), default=0) or None,
        "quantity": quantity,
        "low": str(low) if positive(low) else None, "high": str(high) if positive(high) else None,
        "buy": str(buy) if positive(buy) else None, "sell": str(sell) if positive(sell) else None,
        "lowTime": low_at, "highTime": high_at, "hourHighVolume": volume_high,
        "hourLowVolume": volume_low, "eligible": data_issue is None, "reason": reason,
        "profit": result["profit"] if result and quantity else None,
        "roi": result["roi"] if result else None,
        "margin": result["margin"] if result else None,
    }
