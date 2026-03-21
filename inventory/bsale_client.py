import time
import logging
from collections import deque

import requests

logger = logging.getLogger(__name__)


class BsaleClient:
    """HTTP client for the Bsale API with auth, pagination, and rate limiting."""

    def __init__(self, token: str, base_url: str = "https://api.bsale.cl"):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "access_token": self.token,
            "Content-Type": "application/json",
        })
        self._request_times: deque = deque(maxlen=8)

    def _rate_limit(self):
        """Sleep if we've made 8 requests within the last second."""
        now = time.monotonic()
        if len(self._request_times) == 8:
            elapsed = now - self._request_times[0]
            if elapsed < 1.0:
                sleep_time = 1.0 - elapsed
                logger.debug(f"Rate limit: sleeping {sleep_time:.2f}s")
                time.sleep(sleep_time)
        self._request_times.append(time.monotonic())

    def _request(self, method: str, path: str, params: dict | None = None) -> dict:
        """Make a single API request with rate limiting and retries."""
        url = f"{self.base_url}{path}"
        last_exc = None

        for attempt in range(4):  # 1 initial + 3 retries
            self._rate_limit()
            try:
                resp = self.session.request(method, url, params=params)
            except requests.RequestException as e:
                last_exc = e
                logger.warning(f"Request error (attempt {attempt + 1}): {e}")
                time.sleep(2 ** attempt)
                continue

            if resp.status_code == 401:
                raise SystemExit(
                    "ERROR: 401 Unauthorized — your BSALE_API_TOKEN is invalid or expired.\n"
                    "Go to https://account.bsale.dev/ to generate a new token,\n"
                    "then update your .env file."
                )

            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 2))
                logger.warning(f"Rate limited (429), retrying after {retry_after}s")
                time.sleep(retry_after)
                continue

            if resp.status_code >= 500:
                logger.warning(f"Server error {resp.status_code} (attempt {attempt + 1})")
                time.sleep(2 ** attempt)
                continue

            resp.raise_for_status()
            return resp.json()

        if last_exc:
            raise last_exc
        raise RuntimeError(f"Failed after retries: {url}")

    def get(self, path: str, params: dict | None = None) -> dict:
        return self._request("GET", path, params=params)

    def get_all(self, path: str, params: dict | None = None) -> list[dict]:
        """Auto-paginate through all results for a given endpoint."""
        all_items = []
        limit = 50
        offset = 0
        base_params = dict(params or {})
        base_params["limit"] = limit

        while True:
            base_params["offset"] = offset
            data = self.get(path, params=base_params)
            count = data.get("count", 0)
            items = data.get("items", [])
            all_items.extend(items)

            total_so_far = len(all_items)
            logger.info(f"  {path}: fetched {total_so_far}/{count}")

            offset += limit
            if offset >= count:
                break

        return all_items

    # --- Convenience methods ---

    def get_products(self) -> list[dict]:
        logger.info("Fetching products...")
        return self.get_all("/v1/products.json", params={"expand": "[product_type]"})

    def get_variants(self) -> list[dict]:
        logger.info("Fetching variants...")
        return self.get_all("/v1/variants.json")

    def get_stocks(self) -> list[dict]:
        logger.info("Fetching stocks...")
        return self.get_all("/v1/stocks.json")

    def get_offices(self) -> list[dict]:
        logger.info("Fetching offices...")
        return self.get_all("/v1/offices.json")

    def get_price_lists(self) -> list[dict]:
        logger.info("Fetching price lists...")
        return self.get_all("/v1/price_lists.json")

    def get_price_list_details(self, price_list_id: int) -> list[dict]:
        logger.info(f"Fetching price list details for list {price_list_id}...")
        return self.get_all(f"/v1/price_lists/{price_list_id}/details.json")

    def get_stocks_by_office(self, office_id: int) -> list[dict]:
        """Fetch stocks filtered to a single office (server-side)."""
        logger.info(f"Fetching stocks for office {office_id}...")
        return self.get_all("/v1/stocks.json", params={"officeid": office_id})

    def get_variants_with_product(self) -> list[dict]:
        """Fetch variants with product data expanded inline."""
        logger.info("Fetching variants (with product expand)...")
        return self.get_all("/v1/variants.json", params={"expand": "[product]"})

    def get_product_types(self) -> list[dict]:
        logger.info("Fetching product types...")
        return self.get_all("/v1/product_types.json")
