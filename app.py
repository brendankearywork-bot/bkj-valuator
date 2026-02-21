"""
BKJ Valuation Tool â Backend Server
Automatically fetches the lowest dealer price from Carzone.ie REST API
"""

from flask import Flask, render_template, jsonify, request
from curl_cffi import requests as cf_requests
import os

app = Flask(__name__)
# curl_cffi impersonates Chrome's exact TLS fingerprint â bypasses Cloudflare reliably
session = cf_requests.Session(impersonate="chrome120")

# If set, requests are routed through a Cloudflare Worker proxy to bypass IP-level blocking.
# Set CARZONE_PROXY_URL on Render to e.g. https://bkj-proxy.YOUR-SUBDOMAIN.workers.dev
CARZONE_PROXY_URL = os.environ.get("CARZONE_PROXY_URL", "")
CARZONE_DIRECT_URL = "https://www.carzone.ie/rest/1.0/Car/stock"

# ââ Carzone REST API ââââââââââââââââââââââââââââââââââââââââââ
def get_lowest_carzone_price(make, model, year, max_mileage):
    """Call Carzone's internal REST API to get the cheapest dealer listing."""
    api_url = CARZONE_PROXY_URL if CARZONE_PROXY_URL else CARZONE_DIRECT_URL
    params = {
        "make": make,
        "model": model,
        "minYear": year,
        "maxYear": year,
        "maxMileage": max_mileage,
        "sellerType": "Trade",
        "sort": "PriceAsc",
    }
    search_url = (
        f"https://www.carzone.ie/search?make={make.replace(' ', '%20')}"
        f"&model={model.replace(' ', '%20')}&minYear={year}&maxYear={year}"
        f"&maxMileage={max_mileage}&sellerType=Trade&sort=PriceAsc"
    )

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-IE,en;q=0.9",
        "Referer": "https://www.carzone.ie/search",
        "X-Requested-With": "XMLHttpRequest",
    }

    try:
        resp = session.get(api_url, params=params, headers=headers, timeout=20)
        if resp.status_code != 200:
            return None, search_url, f"Carzone returned status {resp.status_code}"
        try:
            data = resp.json()
        except Exception:
            snippet = resp.text[:120].replace('\n', ' ').strip()
            return None, search_url, f"Carzone response not JSON (status {resp.status_code}): {snippet}"
    except Exception as e:
        return None, search_url, f"Could not reach Carzone: {str(e)}"

    # Flatten all listings from all result groups
    listings = []
    for group in data.get("results", []):
        for item in group.get("items", []):
            summary = item.get("summary", {})
            price_detail = summary.get("priceDetail", {})
            vehicle = summary.get("vehicle", {})
            search_detail = summary.get("searchDetailSummary", {})

            euro_price = price_detail.get("euroPrice")
            is_poa = price_detail.get("poa", False)
            mileage_km = (vehicle.get("mileage") or {}).get("mileageKm")
            mmv = search_detail.get("mmv", {})
            derivative = mmv.get("derivative", "")
            clean_make = mmv.get("cleanMake", make)
            clean_model = mmv.get("cleanModel", model)
            name = f"{clean_make} {clean_model} {derivative}".strip()

            if euro_price and not is_poa:
                listings.append({
                    "price": euro_price,
                    "km": mileage_km,
                    "name": name,
                })

    if not listings:
        return None, search_url, "No matching listings found on Carzone.ie"

    listings.sort(key=lambda x: x["price"])
    return listings[0], search_url, None


# ââ Routes âââââââââââââââââââââââââââââââââââââââââââââââââââ
@app.route("/manifest.json")
def manifest():
    return app.response_class(
        response='{"name":"BKJ Valuation Tool","short_name":"BKJ Value","start_url":"/","display":"standalone","background_color":"#F5F7FA","theme_color":"#43174A"}',
        mimetype="application/json"
    )

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/valuation")
def api_valuation():
    make = request.args.get("make", "").strip()
    model = request.args.get("model", "").strip()
    year = request.args.get("year", "").strip()
    mileage = request.args.get("mileage", "").strip()

    if not all([make, model, year, mileage]):
        return jsonify({"error": "Missing parameters"}), 400

    try:
        year_int = int(year)
        mileage_int = int(mileage)
    except ValueError:
        return jsonify({"error": "Invalid year or mileage"}), 400

    max_mileage = mileage_int + 20000
    listing, carzone_url, error = get_lowest_carzone_price(make, model, year_int, max_mileage)

    if listing:
        offer = listing["price"] - 4000
        return jsonify({
            "success": True,
            "dealer_price": listing["price"],
            "offer": offer,
            "listing_name": listing.get("name", ""),
            "listing_km": listing.get("km"),
            "max_mileage": max_mileage,
            "carzone_url": carzone_url,
        })
    else:
        return jsonify({
            "success": False,
            "error": error or "Could not find matching listings",
            "carzone_url": carzone_url,
        })


# ââ Run ââââââââââââââââââââââââââââââââââââââââââââââââââââââ
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
