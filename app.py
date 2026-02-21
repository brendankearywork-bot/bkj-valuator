"""
BKJ Valuation Tool â Backend Server
Automatically fetches the lowest dealer price from Carzone.ie REST API,
with DoneDeal.ie as automatic fallback when Carzone is blocked.
"""

from flask import Flask, render_template, jsonify, request
from curl_cffi import requests as cf_requests
import os
import json
import re

app = Flask(__name__)

# curl_cffi impersonates Chrome's exact TLS fingerprint â bypasses Cloudflare reliably
session = cf_requests.Session(impersonate="chrome120")

# If set, requests are routed through a Cloudflare Worker proxy to bypass IP-level blocking
# Set CARZONE_PROXY_URL on Render to e.g. https://bkj-proxy.YOUR-SUBDOMAIN.workers.dev
CARZONE_PROXY_URL = os.environ.get("CARZONE_PROXY_URL", "")
CARZONE_DIRECT_URL = "https://www.carzone.ie/rest/1.0/Car/stock"


# ââ Carzone REST API âââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

def get_lowest_carzone_price(make, model, year, max_mileage):
    """Fetch lowest dealer price from Carzone REST API."""
    params = {
        "make": make,
        "model": model,
        "minYear": year,
        "maxYear": year,
        "maxMileage": max_mileage,
        "sellerType": "Trade",
        "sort": "PriceAsc",
    }
    carzone_search_url = (
        f"https://www.carzone.ie/search?make={make}&model={model}"
        f"&minYear={year}&maxYear={year}&maxMileage={max_mileage}"
        f"&sellerType=Trade&sort=PriceAsc"
    )

    try:
        if CARZONE_PROXY_URL:
            import urllib.parse
            encoded = urllib.parse.urlencode(params)
            target = f"{CARZONE_DIRECT_URL}?{encoded}"
            proxy_url = f"{CARZONE_PROXY_URL}?url={urllib.parse.quote(target)}"
            resp = session.get(proxy_url, timeout=20)
        else:
            resp = session.get(CARZONE_DIRECT_URL, params=params, timeout=20)

        if resp.status_code != 200:
            return None, carzone_search_url, f"Carzone returned status {resp.status_code}"

        data = resp.json()

        # Carzone REST API returns a list or object with a cars/stock key
        if isinstance(data, list):
            cars = data
        else:
            cars = data.get("cars", data.get("stock", data.get("results", [])))

        prices = []
        for car in cars:
            for key in ("price", "Price", "askingPrice", "asking_price", "salePrice"):
                p = car.get(key)
                if p and isinstance(p, (int, float)) and p > 500:
                    prices.append(float(p))
                    break

        if not prices:
            return None, carzone_search_url, "No prices found in Carzone response"

        return min(prices), carzone_search_url, None

    except Exception as e:
        return None, carzone_search_url, f"Carzone error: {str(e)}"


# ââ DoneDeal Fallback ââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

def get_lowest_donedeal_price(make, model, year):
    """
    Fetch lowest dealer price from DoneDeal.ie as fallback.
    Parses the __NEXT_DATA__ JSON blob embedded in the HTML.
    """
    model_url = model.replace(" ", "+")
    url = (
        f"https://www.donedeal.ie/cars?make={make}&model={model_url}"
        f"&year_from={year}&year_to={year}&seller_type=dealer&sort=price_asc"
    )

    try:
        resp = session.get(url, timeout=25)
        if resp.status_code != 200:
            return None, f"DoneDeal returned status {resp.status_code}"

        # Extract the __NEXT_DATA__ JSON blob
        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
            resp.text,
            re.DOTALL,
        )
        if not match:
            return None, "DoneDeal: __NEXT_DATA__ not found in page"

        data = json.loads(match.group(1))
        ads = data.get("props", {}).get("pageProps", {}).get("ads", [])

        if not ads:
            return None, "DoneDeal: no ads in response"

        # Normalise model name for fuzzy title matching
        model_clean = re.sub(r"[\s\-_]", "", model).lower()

        # First pass: only include ads whose title contains the model name
        prices = []
        for ad in ads:
            price_info = ad.get("priceInfo") or {}
            price = price_info.get("priceInEuro")
            if not price or not isinstance(price, (int, float)) or price < 500:
                continue

            # DoneDeal ad title lives at different paths depending on API version
            title = (
                ad.get("title")
                or ad.get("header", {}).get("displayName", "")
                or " ".join(str(v) for v in (ad.get("displayAttributes") or []))
            ).lower()

            title_clean = re.sub(r"[\s\-_]", "", title)
            if model_clean in title_clean:
                prices.append(float(price))

        # Second pass: if no model match found, use all prices (better than nothing)
        if not prices:
            for ad in ads:
                price_info = ad.get("priceInfo") or {}
                price = price_info.get("priceInEuro")
                if price and isinstance(price, (int, float)) and price > 500:
                    prices.append(float(price))

        if not prices:
            return None, "DoneDeal: no valid prices found"

        return min(prices), None

    except Exception as e:
        return None, f"DoneDeal error: {str(e)}"


# ââ Flask Routes âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/valuation")
def valuation():
    make = request.args.get("make", "").strip()
    model = request.args.get("model", "").strip()
    year = request.args.get("year", "").strip()
    mileage = request.args.get("mileage", "0").strip()

    if not make or not model or not year:
        return jsonify({"success": False, "error": "Missing make, model or year"}), 400

    try:
        mileage_int = int(mileage)
    except ValueError:
        mileage_int = 0

    max_mileage = mileage_int + 20000

    # ââ Try Carzone first ââââââââââââââââââââââââââââââââââââââââââââââââââââ
    lowest_price, carzone_url, carzone_err = get_lowest_carzone_price(
        make, model, year, max_mileage
    )

    if lowest_price is not None:
        return jsonify(
            {
                "success": True,
                "lowest_price": lowest_price,
                "carzone_url": carzone_url,
                "source": "carzone",
            }
        )

    # ââ Fallback: try DoneDeal âââââââââââââââââââââââââââââââââââââââââââââââ
    dd_price, dd_err = get_lowest_donedeal_price(make, model, year)

    if dd_price is not None:
        return jsonify(
            {
                "success": True,
                "lowest_price": dd_price,
                "carzone_url": carzone_url,   # still include for manual-lookup button
                "source": "donedeal",
            }
        )

    # ââ Both sources failed ââââââââââââââââââââââââââââââââââââââââââââââââââ
    return jsonify(
        {
            "success": False,
            "carzone_url": carzone_url,
            "error": carzone_err,
            "donedeal_error": dd_err,
        }
    ), 503


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
