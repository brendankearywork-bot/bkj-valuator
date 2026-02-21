/**
 * BKJ Carzone Proxy â Cloudflare Worker
 *
 * Proxies requests to Carzone's REST API and adds CORS headers so the
 * BKJ Valuation Tool (hosted on Render) can call it without being blocked.
 *
 * Deploy steps (free, ~5 minutes):
 *   1. Go to https://workers.cloudflare.com and sign up / log in
 *   2. Click "Create a Service" â name it "bkj-proxy" â "HTTP handler"
 *   3. Paste this entire file into the editor and click "Save and Deploy"
 *   4. Copy your Worker URL (e.g. https://bkj-proxy.YOUR-SUBDOMAIN.workers.dev)
 *   5. In Render dashboard â your service â Environment â add:
 *        CARZONE_PROXY_URL = https://bkj-proxy.YOUR-SUBDOMAIN.workers.dev
 *   6. Trigger a manual redeploy on Render
 */

const CARZONE_API = "https://www.carzone.ie/rest/1.0/Car/stock";

export default {
  async fetch(request) {
    // Pass through query params straight to Carzone's API
    const incomingUrl = new URL(request.url);
    const carzoneUrl = new URL(CARZONE_API);
    for (const [key, value] of incomingUrl.searchParams) {
      carzoneUrl.searchParams.set(key, value);
    }

    const resp = await fetch(carzoneUrl.toString(), {
      headers: {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-IE,en;q=0.9",
        "Referer": "https://www.carzone.ie/search",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      },
    });

    const body = await resp.text();
    return new Response(body, {
      status: resp.status,
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
      },
    });
  },
};
