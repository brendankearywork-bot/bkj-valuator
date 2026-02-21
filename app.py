"""
BKJ Valuation Tool — Backend Server
Automatically fetches the lowest dealer price from Carzone.ie
"""

from flask import Flask, render_template, jsonify, request
import cloudscraper
from bs4 import BeautifulSoup
import json, re, os

app = Flask(__name__)
scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "darwin"})

# ── Carzone Scraper ──────────────────────────────────────────
def get_lowest_carzone_price(make, model, year, max_mileage):
    """Search Carzone.ie for the cheapest dealer listing and return the price."""
    make_enc = make.replace(" ", "%20")
    model_enc = model.replace(" ", "%20")
    url = (
        f"https://www.carzone.ie/search?make={make_enc}&model={model_enc}"
        f"&minYear={year}&maxYear={year}&maxMileage={max_mileage}"
        f"&sellerType=Trade&sort=PriceAsc"
    )

    try:
        resp = scraper.get(url, timeout=15)
        html = resp.text
    except Exception as e:
        return None, url, str(e)

    # ── Strategy 1: JSON-LD structured data (most reliable) ──
    listings = []
    for script in re.findall(
        r'<script[^>]+type=["\'\']application/ld\+json["\'\'][^>]*>(.*?)</script>',
        html, re.S
    ):
        try:
            data = json.loads(script)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") == "Car":
                    price = float(item.get("offers", {}).get("price", 0))
                    km = float(item.get("mileageFromOdometer", {}).get("value", 0))
                    car_year = int(item.get("vehicleModelDate", 0))
                    name = item.get("name", "")
                    if (
                        price > 1000
                        and km <= max_mileage
                        and car_year == int(year)
                    ):
                        listings.append({
                            "price": price,
                            "km": int(km),
                            "name": name,
                            "year": car_year,
                        })
        except Exception:
            pass

    if listings:
        listings.sort(key=lambda x: x["price"])
        return listings[0], url, None

    # ── Strategy 2: Regex parsing of HTML ──
    year_str = str(year)
    pattern = re.compile(
        year_str + r'\s*[•·]\s*([\d,]+)\s*km[\s\S]{0,400}?€([\d,]+)', re.I
    )
    for m in pattern.finditer(html):
        km = int(m.group(1).replace(",", ""))
        price = int(m.group(2).replace(",", ""))
        if km <= max_mileage and 1000 < price < 300000:
            return {
                "price": price,
                "km": km,
                "name": f"{year} {make} {model}",
                "year": int(year),
            }, url, None

    pattern2 = re.compile(
        r'€([\d,]+)[\s\S]{0,400}?' + year_str + r'\s*[•·]\s*([\d,]+)\s*km', re.I
    )
    for m in pattern2.finditer(html):
        price = int(m.group(1).replace(",", ""))
        km = int(m.group(2).replace(",", ""))
        if km <= max_mileage and 1000 < price < 300000:
            return {
                "price": price,
                "km": km,
                "name": f"{year} {make} {model}",
                "year": int(year),
            }, url, None

    return None, url, "No matching listings found"


# ── Routes ───────────────────────────────────────────────────
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


# ── Run ──────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
