#!/usr/bin/env python3
"""Build independent CZ Feed A from the fully validated Merchant-sourced CZ feed."""
import argparse
import csv
from pathlib import Path

LABEL_1 = {"Náhradní díl", "Spotřební materiál", "Příslušenství"}
LABEL_3 = {"margin_30_40", "margin_40_50", "margin_50_60"}
LABEL_4 = {f"elephant{i}" for i in range(2, 11)}
LABELS = {f"custom_label_{i}" for i in range(5)}

def matches(row):
    return (
        row["availability"].strip().casefold() == "in_stock"
        and row["custom_label_0"].strip() == "CZ1"
        and row["custom_label_1"].strip() in LABEL_1
        and row["custom_label_2"].strip() == "Bobr0"
        and row["custom_label_3"].strip() in LABEL_3
        and row["custom_label_4"].strip().casefold() in LABEL_4
    )

def build(input_path, output_path):
    with Path(input_path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        needed = LABELS | {"availability", "id"}
        if not needed.issubset(fields):
            raise RuntimeError(f"Source feed missing fields: {sorted(needed - set(fields))}")
        retained = [field for field in fields if field not in LABELS]
        selected = [{field: row[field] for field in retained} for row in reader if matches(row)]
    if not selected:
        raise RuntimeError("Feed A has zero matching products; existing public feed preserved")
    ids = [row["id"] for row in selected]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Feed A has duplicate product IDs")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=retained, lineterminator="\n")
        writer.writeheader()
        writer.writerows(selected)
    return len(selected)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(f"Feed A published products: {build(args.input, args.output)}")
