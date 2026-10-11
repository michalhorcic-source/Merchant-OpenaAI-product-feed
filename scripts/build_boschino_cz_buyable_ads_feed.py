#!/usr/bin/env python3
"""Generate the CZ in-stock Ads export without altering the existing full feed."""
from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import build_boschino_cz_feed as merchant

CORE_FIELDS = ["id", "title", "description", "link", "image_link", "availability", "price", "brand"]
LABEL_FIELDS = [f"custom_label_{index}" for index in range(5)]
OPTIONAL_FIELDS = ["gtin", "mpn", "identifier_exists", "item_group_id", "color", "size", "material", "pattern", "age_group", "gender", "sale_price"]
FIELDS = CORE_FIELDS + OPTIONAL_FIELDS[:-1] + ["sale_price"] + LABEL_FIELDS


def build(products: list[dict]) -> tuple[list[dict[str, str]], dict]:
    rows = []
    rejected = Counter()
    invalid = []
    seen_ids = set()
    seen_variants = set()
    seen_group_options = set()
    for product in products:
        attributes = merchant.value(product, "productAttributes", "product_attributes", "attributes") or {}
        if merchant.clean(merchant.value(attributes, "availability")).upper() not in {"IN_STOCK", "BACKORDER"}:
            rejected["availability_not_allowed"] += 1
            continue
        try:
            original = merchant.transform(product)
            parsed_link = urlparse(original["url"])
            source_group_id = merchant.clean(merchant.value(attributes, "itemGroupId", "item_group_id"))
            variant_id = parse_qs(parsed_link.query).get("variant", [""])[0]
            group_id = source_group_id
            if variant_id and not group_id:
                group_id = f"boschino-cz:{parsed_link.path.rstrip('/')}"
            identifier_exists = "no" if merchant.value(attributes, "identifierExists", "identifier_exists") is False else "yes"
            row = {
                "id": original["item_id"], "title": original["title"],
                "description": original["description"], "link": original["url"],
                "image_link": original["image_url"], "availability": original["availability"],
                "price": original["price"], "brand": original["brand"],
                "gtin": original["gtin"], "mpn": original["mpn"],
                "identifier_exists": identifier_exists,
                "item_group_id": group_id,
                "color": merchant.clean(merchant.value(attributes, "color")),
                "size": merchant.clean(merchant.value(attributes, "size")),
                "material": merchant.clean(merchant.value(attributes, "material")),
                "pattern": merchant.clean(merchant.value(attributes, "pattern")),
                "age_group": merchant.clean(merchant.value(attributes, "ageGroup", "age_group")),
                "gender": merchant.clean(merchant.value(attributes, "gender")),
                "sale_price": original["sale_price"],
            }
            for index, field in enumerate(LABEL_FIELDS):
                row[field] = merchant.clean(merchant.value(attributes, f"customLabel{index}", field))
            # Google custom labels are optional segmentation metadata. Preserve
            # any populated values, but never use labels to decide inclusion.
            missing = [field for field in CORE_FIELDS if not row[field]]
            if not row["gtin"] and not row["mpn"] and row["identifier_exists"] != "no":
                missing.append("gtin or mpn")
            if missing:
                raise ValueError("missing fields: " + ", ".join(missing))
            if urlparse(row["link"]).hostname not in {"boschino.cz", "www.boschino.cz"}:
                raise ValueError("offer URL is outside the CZ storefront")
            if any(marker in value for value in row.values() for marker in merchant.BAD_TEXT):
                raise ValueError("invalid output text")
            if row["id"] in seen_ids:
                raise ValueError("duplicate item_id")
            if row["item_group_id"] and row["item_group_id"] == row["id"]:
                raise ValueError("item_group_id must differ from variant id")
            option_fields = ["color", "size", "material", "pattern", "age_group", "gender"]
            option_values = tuple(row[field] for field in option_fields if row[field])
            if row["item_group_id"] and not option_values:
                raise ValueError("grouped variant is missing selected variant attributes")
            parsed = urlparse(row["link"])
            variant = parse_qs(parsed.query).get("variant", [""])[0]
            if variant and not row["item_group_id"]:
                raise ValueError("variant URL requires item_group_id for variant grouping")
            if variant:
                key = (parsed.hostname, variant)
                if key in seen_variants:
                    raise ValueError("duplicate storefront variant")
                seen_variants.add(key)
            if row["item_group_id"] and (row["item_group_id"], option_values) in seen_group_options:
                raise ValueError("duplicate option combination in item_group_id")
            if row["item_group_id"]:
                seen_group_options.add((row["item_group_id"], option_values))
            seen_ids.add(row["id"])
            rows.append(row)
        except (ValueError, KeyError) as error:
            invalid.append({"item_id": merchant.clean(merchant.value(product, "offerId", "offer_id")), "reason": str(error)})
    failures = Counter(item["reason"] for item in invalid)
    if not rows:
        raise RuntimeError("Refusing empty buyable CZ feed; invalid_row_reasons=" + json.dumps(dict(failures), ensure_ascii=False, sort_keys=True))
    rows.sort(key=lambda row: row["id"])
    return rows, {"generated_at": datetime.now(timezone.utc).isoformat(), "source_products": len(products), "included": len(rows), "excluded_by_availability": dict(rejected), "excluded_invalid_rows": len(invalid), "invalid_row_reasons": dict(failures), "fields": FIELDS}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--offline-products", type=Path)
    args = parser.parse_args()
    if args.offline_products:
        products = json.loads(args.offline_products.read_text(encoding="utf-8"))
    else:
        encoded = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON_B64", "")
        if not encoded:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON_B64 is required for a fresh Merchant API read")
        products = merchant.fetch_products(merchant.load_token(encoded))
    if not isinstance(products, list):
        raise RuntimeError("Expected a products list")
    try:
        rows, report = build(products)
    except RuntimeError as error:
        merchant.write_utf8(args.report, json.dumps({"status": "validation_failed", "error": str(error), "source_products": len(products)}, ensure_ascii=False, indent=2) + "\n")
        raise
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    merchant.write_utf8(args.report, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    merchant.write_utf8(args.output, buffer.getvalue())
    print(f"Validated {len(rows)} in-stock CZ offers with price and all five Google labels")


if __name__ == "__main__":
    main()
