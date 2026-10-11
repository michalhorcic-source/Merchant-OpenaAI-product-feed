#!/usr/bin/env python3
"""Build the CZ buyable OpenAI Ads feed from a Merchant Center TSV export ZIP."""
from __future__ import annotations

import argparse
import csv
import json
import re
import zipfile
from collections import Counter
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

FIELDS = [
    "id", "title", "description", "link", "image_link", "availability", "price", "brand",
    "gtin", "mpn", "identifier_exists", "item_group_id", "color", "size", "material",
    "pattern", "age_group", "gender", "sale_price",
    "custom_label_0", "custom_label_1", "custom_label_2", "custom_label_3", "custom_label_4",
]
SOURCE_LABELS = [f"vlastní štítek {i}" for i in range(5)]
CORE_SOURCE_FIELDS = ["název", "id", "cena", "url", "url obrázku", "značka"]
AVAILABILITY = {"skladem": "in_stock", "doobjednávka": "backorder"}


def clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\x00", " ")).strip()


def money(value: str, *, required: bool = False) -> str:
    value = clean(value)
    if not value:
        if required:
            raise ValueError("missing price")
        return ""
    match = re.fullmatch(r"([0-9]+(?:[.,][0-9]+)?)\s*CZK", value, re.IGNORECASE)
    if not match:
        raise ValueError("invalid CZK price")
    try:
        amount = Decimal(match.group(1).replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("invalid CZK price") from exc
    if amount <= 0:
        raise ValueError("non-positive CZK price")
    return f"{amount:.2f} CZK"


def valid_gtin(value: str) -> str:
    code = re.sub(r"\D", "", clean(value))
    if len(code) not in {8, 12, 13, 14}:
        return ""
    checksum = sum(int(digit) * (3 if index % 2 == 0 else 1)
                   for index, digit in enumerate(reversed(code[:-1])))
    return code if (10 - checksum % 10) % 10 == int(code[-1]) else ""


def transform(source: dict[str, str]) -> tuple[dict[str, str], bool]:
    availability_source = clean(source.get("dostupnost")).casefold()
    if availability_source not in AVAILABILITY:
        raise ValueError("availability is not skladem or doobjednávka")

    title = clean(source.get("název"))
    item_id = clean(source.get("id"))
    link = clean(source.get("url"))
    image_link = clean(source.get("url obrázku"))
    brand = clean(source.get("značka"))
    if not all((title, item_id, link, image_link, brand)):
        raise ValueError("missing required title, id, link, image, or brand")

    parsed_link = urlparse(link)
    if parsed_link.scheme != "https" or parsed_link.hostname != "boschino.cz":
        raise ValueError("offer URL is not the CZ storefront")
    parsed_image = urlparse(image_link)
    if parsed_image.scheme != "https" or not parsed_image.hostname:
        raise ValueError("image URL is not HTTPS")

    price = money(source.get("cena", ""), required=True)
    sale_price = money(source.get("cena v akci", ""))
    if sale_price and Decimal(sale_price.split()[0]) >= Decimal(price.split()[0]):
        sale_price = ""

    gtin = valid_gtin(source.get("gtin", ""))
    mpn = clean(source.get("mpn"))
    exists_value = clean(source.get("identifikátor existuje")).casefold()
    identifier_exists = {"ano": "yes", "ne": "no", "yes": "yes", "no": "no"}.get(exists_value, "yes")
    if not gtin and not mpn and identifier_exists != "no":
        raise ValueError("identifier exists but GTIN and MPN are missing")

    description = clean(source.get("popis"))
    used_title_description = not description
    if used_title_description:
        # The title is present in the source export and adds no unverified facts.
        description = title

    group_id = clean(source.get("id skupiny"))
    if not group_id and parse_qs(parsed_link.query).get("variant"):
        group_id = f"boschino-cz:{parsed_link.path.rstrip('/')}"

    row = {
        "id": item_id,
        "title": title,
        "description": description,
        "link": link,
        "image_link": image_link,
        "availability": AVAILABILITY[availability_source],
        "price": price,
        "brand": brand,
        "gtin": gtin,
        "mpn": mpn,
        "identifier_exists": identifier_exists,
        "item_group_id": group_id,
        "color": clean(source.get("barva")),
        "size": "",
        "material": "",
        "pattern": "",
        "age_group": "",
        "gender": "",
        "sale_price": sale_price,
    }
    for index, field in enumerate(SOURCE_LABELS):
        row[f"custom_label_{index}"] = clean(source.get(field))
    return row, used_title_description


def read_source_zip(path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as archive:
        files = [name for name in archive.namelist() if not name.endswith("/")]
        if len(files) != 1:
            raise RuntimeError(f"Expected exactly one TSV file in ZIP, found {len(files)}")
        with archive.open(files[0]) as stream:
            text = (line.decode("utf-8-sig") for line in stream)
            reader = csv.DictReader(text, delimiter="\t")
            required = set(CORE_SOURCE_FIELDS + ["dostupnost", "gtin", "mpn", "identifikátor existuje"] + SOURCE_LABELS)
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise RuntimeError("TSV is missing expected columns: " + ", ".join(sorted(missing)))
            return list(reader)


def build(products: list[dict[str, str]]) -> tuple[list[dict[str, str]], dict]:
    rows: list[dict[str, str]] = []
    exclusions = Counter()
    descriptions_from_title = 0
    seen_ids: set[str] = set()
    for source in products:
        if clean(source.get("dostupnost")).casefold() not in AVAILABILITY:
            exclusions["availability_not_allowed"] += 1
            continue
        try:
            row, used_title = transform(source)
            if row["id"] in seen_ids:
                raise ValueError("duplicate id")
            seen_ids.add(row["id"])
            rows.append(row)
            descriptions_from_title += int(used_title)
        except ValueError as error:
            exclusions[str(error)] += 1
    if not rows:
        raise RuntimeError("No valid in-stock or backorder products found")
    rows.sort(key=lambda row: row["id"])
    return rows, {
        "source_products": len(products),
        "included": len(rows),
        "availability_in_stock": sum(row["availability"] == "in_stock" for row in rows),
        "availability_backorder": sum(row["availability"] == "backorder" for row in rows),
        "descriptions_filled_from_title": descriptions_from_title,
        "excluded": dict(exclusions),
        "fields": FIELDS,
    }


def write_csv(rows: list[dict[str, str]], path: Path) -> None:
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(buffer.getvalue(), encoding="utf-8", newline="")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-zip", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    products = read_source_zip(args.input_zip)
    rows, report = build(products)
    write_csv(rows, args.output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
