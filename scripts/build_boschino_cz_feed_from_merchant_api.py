#!/usr/bin/env python3
"""Build the CZ OpenAI Ads feed from all CZ Merchant API products."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import build_boschino_cz_feed_from_merchant_export as feed

ACCOUNT = "5757276720"
API_URL = f"https://merchantapi.googleapis.com/products/v1/accounts/{ACCOUNT}/products"
MINIMUM_OFFERS = 30_000


def pick(obj: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if obj.get(key) is not None:
            return obj[key]
    return default


def api_money(value: Any) -> str:
    if isinstance(value, dict):
        currency = pick(value, "currencyCode", "currency_code", "currency")
        amount = pick(value, "amount", "amountMicros", "amount_micros", "value")
        if "amountMicros" in value or "amount_micros" in value:
            try:
                from decimal import Decimal
                amount = Decimal(str(amount)) / Decimal("1000000")
            except Exception as exc:
                raise ValueError("invalid Merchant API price") from exc
        return f"{amount} {currency}"
    return str(value or "")


def api_product_to_source(product: dict[str, Any]) -> dict[str, str] | None:
    feed_label = str(pick(product, "feedLabel", "feed_label")).upper()
    if feed_label != "CZ":
        return None
    attrs = pick(product, "productAttributes", "product_attributes", "attributes", default={}) or {}
    link = str(pick(attrs, "link", "url"))
    parsed = urlparse(link)
    if parsed.scheme != "https" or parsed.hostname != "boschino.cz":
        return None

    price = api_money(pick(attrs, "price"))
    # The account can contain offers for other countries and currencies. Keep only
    # offers explicitly priced in CZK and linked to the CZ storefront.
    if not price.upper().strip().endswith("CZK"):
        return None

    availability = str(pick(attrs, "availability")).upper()
    source_availability = {"IN_STOCK": "skladem", "BACKORDER": "doobjednávka"}.get(availability)
    if not source_availability:
        return None

    gtins = pick(attrs, "gtins", "gtin", default=[])
    if not isinstance(gtins, list):
        gtins = [gtins]
    gtin = next((str(item) for item in gtins if item), "")
    identifier_exists = pick(attrs, "identifierExists", "identifier_exists", default=True)
    if isinstance(identifier_exists, bool):
        identifier_exists = "yes" if identifier_exists else "no"

    source = {
        "název": str(pick(attrs, "title")),
        "id": str(pick(product, "offerId", "offer_id")),
        "cena": price,
        "cena v akci": api_money(pick(attrs, "salePrice", "sale_price")),
        "dostupnost": source_availability,
        "barva": str(pick(attrs, "color")),
        "gtin": gtin,
        "identifikátor existuje": str(identifier_exists),
        "id skupiny": str(pick(attrs, "itemGroupId", "item_group_id")),
        "mpn": str(pick(attrs, "mpn")),
        "popis": str(pick(attrs, "description")),
        "url": link,
        "url obrázku": str(pick(attrs, "imageLink", "image_link")),
        "značka": str(pick(attrs, "brand")),
    }
    for index in range(5):
        source[f"vlastní štítek {index}"] = str(pick(attrs, f"customLabel{index}", f"custom_label_{index}"))
    return source


def fetch_products(token: str) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    page_token = ""
    seen_tokens: set[str] = set()
    while True:
        params = {"pageSize": "1000"}
        if page_token:
            params["pageToken"] = page_token
        request = Request(API_URL + "?" + urlencode(params), headers={"Authorization": f"Bearer {token}"})
        try:
            with urlopen(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            api_status = "unknown"
            try:
                error = json.loads(exc.read().decode("utf-8")).get("error", {})
                candidate = str(error.get("status", "unknown"))
                if candidate.replace("_", "").isalnum():
                    api_status = candidate
            except Exception:
                pass
            raise RuntimeError(f"Merchant API products.list failed (HTTP {exc.code}; API status {api_status})") from None
        except Exception as exc:
            raise RuntimeError(f"Merchant API products.list failed ({type(exc).__name__})") from None
        batch = payload.get("products")
        if not isinstance(batch, list):
            raise RuntimeError("Merchant API response has no products list")
        products.extend(item for item in batch if isinstance(item, dict))
        page_token = str(payload.get("nextPageToken") or "").strip()
        if not page_token:
            break
        if page_token in seen_tokens:
            raise RuntimeError("Merchant API pagination repeated a page token")
        seen_tokens.add(page_token)
    if not products:
        raise RuntimeError("refusing empty Merchant API products.list result")
    return products


def load_token(encoded_service_account: str) -> str:
    try:
        info = json.loads(base64.b64decode(encoded_service_account, validate=True))
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as GoogleRequest
        credentials = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/content"]
        )
        credentials.refresh(GoogleRequest())
    except Exception as exc:
        raise RuntimeError(f"could not obtain Merchant API OAuth token ({type(exc).__name__})") from None
    if not credentials.token:
        raise RuntimeError("service account did not return an OAuth token")
    return credentials.token


def build(products: list[dict[str, Any]]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    sources = [source for product in products if (source := api_product_to_source(product)) is not None]
    rows, report = feed.build(sources)
    report["merchant_api_products"] = len(products)
    report["cz_store_czk_stock_or_backorder"] = len(sources)
    # Protect the established 35k-scale feed against incomplete API access,
    # pagination regressions, or a mistakenly narrowed account result.
    if len(rows) < MINIMUM_OFFERS:
        raise RuntimeError(f"refusing to publish only {len(rows)} offers; expected at least {MINIMUM_OFFERS}")
    return rows, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    secret = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON_B64", "")
    if not secret:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON_B64 is required")
    products = fetch_products(load_token(secret))
    rows, report = build(products)
    feed.write_csv(rows, args.output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
