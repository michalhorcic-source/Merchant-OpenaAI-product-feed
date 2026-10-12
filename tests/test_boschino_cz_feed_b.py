import csv
import sys
import tempfile
import unittest
from urllib.error import HTTPError
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_boschino_cz_feed_b as feed_b


HEADERS = [
    "id", "title", "availability", "custom_label_0", "custom_label_1",
    "custom_label_2", "custom_label_3", "custom_label_4", "tail",
]


def product(identifier, **overrides):
    row = {
        "id": identifier,
        "title": "Náhradní díl příslušenství",
        "availability": "in_stock",
        "custom_label_0": " CZ1 ",
        "custom_label_1": "Náhradní díl",
        "custom_label_2": " Bobr1 ",
        "custom_label_3": "margin_30_40",
        "custom_label_4": " ELEPHANT2 ",
        "tail": "zachovat",
    }
    row.update(overrides)
    return row


class FeedBTest(unittest.TestCase):
    def write_source(self, path, rows, headers=HEADERS):
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def test_selects_all_categories_and_margins_and_elephant_bounds_then_strips_labels(self):
        rows = [
            product("part", custom_label_1="Náhradní díl", custom_label_3="margin_30_40", custom_label_4="Elephant2"),
            product("consumable", custom_label_1="Spotřební materiál", custom_label_3="margin_40_50", custom_label_4="elephant10"),
            product("accessory", custom_label_1="Příslušenství", custom_label_3="margin_50_60", custom_label_4="ELEPHANT5"),
            product("too-low", custom_label_4="elephant1"),
            product("too-high", custom_label_4="elephant11"),
            product("feed-a", custom_label_2="Bobr0"),
            product("wrong-stock", availability="backorder"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            destination = Path(directory) / "feed-b.csv"
            self.write_source(source, rows)

            self.assertEqual(3, feed_b.build(source, destination))
            raw = destination.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertEqual(raw, raw.decode("utf-8").encode("utf-8"))
            self.assertEqual(3, feed_b.validate_published(source, destination))
            with destination.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(["id", "title", "availability", "tail"], reader.fieldnames)
                selected = list(reader)
                self.assertEqual(["part", "consumable", "accessory"], [row["id"] for row in selected])
                self.assertEqual("Náhradní díl příslušenství", selected[0]["title"])

    def test_invalid_input_preserves_existing_destination(self):
        cases = {
            "duplicate": [product("same"), product("same")],
            "empty": [product("feed-a", custom_label_2="Bobr0")],
            "missing-column": [product("one")],
        }
        with tempfile.TemporaryDirectory() as directory:
            for name, rows in cases.items():
                with self.subTest(name=name):
                    source = Path(directory) / f"{name}.csv"
                    destination = Path(directory) / f"{name}-destination.csv"
                    headers = [header for header in HEADERS if header != "custom_label_4"] if name == "missing-column" else HEADERS
                    source_rows = [{key: value for key, value in row.items() if key in headers} for row in rows]
                    self.write_source(source, source_rows, headers)
                    destination.write_text("known-good\n", encoding="utf-8", newline="")

                    with self.assertRaises(RuntimeError):
                        feed_b.build(source, destination)

                    self.assertEqual("known-good\n", destination.read_text(encoding="utf-8"))

    def test_skip_empty_preserves_destination_without_creating_a_fake_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            destination = Path(directory) / "feed-b.csv"
            self.write_source(source, [product("feed-a", custom_label_2="Bobr0")])
            destination.write_text("previous-valid-feed\n", encoding="utf-8", newline="")

            self.assertIsNone(feed_b.build(source, destination, skip_empty=True))

            self.assertEqual("previous-valid-feed\n", destination.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            destination = Path(directory) / "not-created.csv"
            self.write_source(source, [product("feed-a", custom_label_2="Bobr0")])

            self.assertIsNone(feed_b.build(source, destination, skip_empty=True))

            self.assertFalse(destination.exists())

    def test_retained_feed_validation_rejects_empty_wrong_schema_and_encoding(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            candidate = Path(directory) / "prior-b.csv"
            self.write_source(source, [product("one")])

            candidate.write_text("id,title,availability,tail\n", encoding="utf-8", newline="")
            with self.assertRaisesRegex(RuntimeError, "must not publish an empty"):
                feed_b.validate_published(source, candidate)

            candidate.write_text("id,title,availability\none,Náhradní díl,in_stock\n", encoding="utf-8", newline="")
            with self.assertRaisesRegex(RuntimeError, "schema"):
                feed_b.validate_published(source, candidate)

            candidate.write_bytes(b"\xef\xbb\xbfid,title,availability,tail\none,Nahradni,in_stock,zachovat\n")
            with self.assertRaisesRegex(RuntimeError, "without BOM"):
                feed_b.validate_published(source, candidate)

            candidate.write_text(
                f"id,title,availability,tail\none,{chr(0x00C3)},in_stock,zachovat\n",
                encoding="utf-8",
                newline="",
            )
            with self.assertRaisesRegex(RuntimeError, "corruption marker"):
                feed_b.validate_published(source, candidate)

    def test_retain_prior_404_and_invalid_bytes_preserve_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            destination = Path(directory) / "prior-b.csv"
            self.write_source(source, [product("one")])
            destination.write_text("known-good\n", encoding="utf-8", newline="")
            with patch.object(feed_b, "urlopen", side_effect=HTTPError("https://example.invalid/b", 404, "not found", {}, None)):
                self.assertFalse(feed_b.retain_prior(source, destination, "https://example.invalid/b"))
            self.assertEqual("known-good\n", destination.read_text(encoding="utf-8"))
            with self.assertRaisesRegex(RuntimeError, "strict UTF-8"):
                feed_b.write_validated(source, destination, b"\xff")
            self.assertEqual("known-good\n", destination.read_text(encoding="utf-8"))

    def test_retain_prior_rejects_blank_required_title_and_preserves_destination(self):
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b"id,title,availability,tail\none,,in_stock,zachovat\n"

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            destination = Path(directory) / "prior-b.csv"
            self.write_source(source, [product("one")])
            destination.write_text("known-good\n", encoding="utf-8", newline="")
            with patch.object(feed_b, "urlopen", return_value=Response()):
                with self.assertRaisesRegex(RuntimeError, "blank required field"):
                    feed_b.retain_prior(source, destination, "https://example.invalid/b")
            self.assertEqual("known-good\n", destination.read_text(encoding="utf-8"))

    def test_retained_feed_rejects_invalid_price(self):
        headers = HEADERS + ["price"]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.csv"
            candidate = Path(directory) / "prior-b.csv"
            self.write_source(source, [product("one", price="1.00 CZK")], headers)
            candidate.write_text("id,title,availability,tail,price\none,Náhradní díl,in_stock,zachovat,0 CZK\n", encoding="utf-8", newline="")
            with self.assertRaisesRegex(RuntimeError, "invalid price"):
                feed_b.validate_published(source, candidate)


if __name__ == "__main__":
    unittest.main()
