#!/usr/bin/env python3
"""Build independent CZ Feed B from the fully validated Merchant-sourced CZ feed."""
import argparse
import csv
from decimal import Decimal, InvalidOperation
import io
from pathlib import Path
import tempfile
from urllib.error import HTTPError
from urllib.request import urlopen

LABEL_1 = {"Náhradní díl", "Spotřební materiál", "Příslušenství"}
LABEL_3 = {"margin_30_40", "margin_40_50", "margin_50_60"}
LABEL_4 = {f"elephant{i}" for i in range(2, 11)}
LABELS = {f"custom_label_{i}" for i in range(5)}
ENCODING_MARKERS = ("\ufffd", "\u00c3", "\u0102", "\u00e2\u20ac", "\ufffd")


def matches(row):
    return (
        row["availability"].strip().casefold() == "in_stock"
        and row["custom_label_0"].strip() == "CZ1"
        and row["custom_label_1"].strip() in LABEL_1
        and row["custom_label_2"].strip() == "Bobr1"
        and row["custom_label_3"].strip() in LABEL_3
        and row["custom_label_4"].strip().casefold() in LABEL_4
    )


def build(input_path, output_path, skip_empty=False):
    with Path(input_path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        needed = LABELS | {"availability", "id"}
        if not needed.issubset(fields):
            raise RuntimeError(f"Source feed missing fields: {sorted(needed - set(fields))}")
        retained = [field for field in fields if field not in LABELS]
        selected = [{field: row[field] for field in retained} for row in reader if matches(row)]
    if not selected:
        if skip_empty:
            return None
        raise RuntimeError("Feed B has zero matching products; existing public feed preserved")
    ids = [row["id"] for row in selected]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Feed B has duplicate product IDs")
    rendered = io.StringIO(newline="")
    writer = csv.DictWriter(rendered, fieldnames=retained, lineterminator="\n")
    writer.writeheader()
    writer.writerows(selected)
    write_validated(input_path, output_path, rendered.getvalue().encode("utf-8"))
    return len(selected)


def validate_bytes(input_path, raw):
    full_path = Path(input_path)
    if raw.startswith(b"\xef\xbb\xbf"):
        raise RuntimeError("Feed B must be UTF-8 without BOM")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("Feed B must be strict UTF-8") from exc
    if any(marker in text for marker in ENCODING_MARKERS):
        raise RuntimeError("Feed B has an encoding corruption marker")
    with full_path.open(encoding="utf-8", newline="") as handle:
        full_headers = csv.DictReader(handle).fieldnames or []
    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = reader.fieldnames or []
    rows = list(reader)
    expected = [field for field in full_headers if field not in LABELS]
    if headers != expected:
        raise RuntimeError("Feed B schema does not match the full feed with labels stripped")
    if not rows:
        raise RuntimeError("Feed B must not publish an empty CSV")
    required = {"id", "title", "description", "link", "image_link", "availability", "price", "brand", "identifier_exists"}
    for row in rows:
        if any(field in headers and not row[field].strip() for field in required):
            raise RuntimeError("Feed B has a blank required field")
        if "price" in headers:
            try:
                amount, currency = row["price"].rsplit(maxsplit=1)
                if currency != "CZK" or Decimal(amount) <= 0:
                    raise ValueError
            except (InvalidOperation, ValueError):
                raise RuntimeError("Feed B has an invalid price") from None
        if row.get("identifier_exists") != "no" and "gtin" in headers and "mpn" in headers:
            if not row["gtin"].strip() and not row["mpn"].strip():
                raise RuntimeError("Feed B has a missing identifier")
    if len({row["id"] for row in rows}) != len(rows):
        raise RuntimeError("Feed B has duplicate product IDs")
    if any(row["availability"] != "in_stock" for row in rows):
        raise RuntimeError("Feed B has unexpected availability")
    return len(rows)


def write_validated(input_path, output_path, raw):
    validate_bytes(input_path, raw)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(dir=output.parent, prefix=f".{output.name}.", delete=False)
    try:
        temporary.write(raw)
        temporary.close()
        if Path(temporary.name).read_bytes() != raw:
            raise RuntimeError("Feed B temporary write did not round-trip")
        validate_bytes(input_path, Path(temporary.name).read_bytes())
        Path(temporary.name).replace(output)
    finally:
        if not temporary.closed:
            temporary.close()
        Path(temporary.name).unlink(missing_ok=True)


def validate_published(input_path, output_path):
    return validate_bytes(input_path, Path(output_path).read_bytes())


def retain_prior(input_path, output_path, url):
    try:
        with urlopen(url, timeout=120) as response:
            if response.status != 200:
                raise RuntimeError(f"Unexpected HTTP {response.status} retrieving previous Feed B")
            raw = response.read()
    except HTTPError as exc:
        if exc.code == 404:
            return False
        raise RuntimeError(f"Could not retrieve previous Feed B (HTTP {exc.code})") from exc
    write_validated(input_path, output_path, raw)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--skip-empty", action="store_true")
    parser.add_argument("--validate-published", action="store_true")
    parser.add_argument("--retain-prior-url")
    args = parser.parse_args()
    if args.validate_published:
        print(f"Validated CZ Feed B: {validate_published(args.input, args.output)} products")
        raise SystemExit(0)
    if args.retain_prior_url:
        retained = retain_prior(args.input, args.output, args.retain_prior_url)
        print("Retained prior CZ Feed B" if retained else "No prior CZ Feed B exists")
        raise SystemExit(0)
    count = build(args.input, args.output, skip_empty=args.skip_empty)
    if count is None:
        print("Feed B skipped: zero matching products; destination unchanged")
    else:
        print(f"Feed B published products: {count}")
