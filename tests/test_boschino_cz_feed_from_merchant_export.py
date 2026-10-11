import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_boschino_cz_feed_from_merchant_export as feed


class MerchantExportFeedTest(unittest.TestCase):
    def setUp(self):
        self.product = {
            "název": "Šnek do mlýnku Bosch",
            "id": "shopify_ZZ_123_456",
            "cena": "528.00 CZK",
            "cena v akci": "499.00 CZK",
            "dostupnost": "skladem",
            "barva": "stříbrná",
            "gtin": "8757521715808",
            "identifikátor existuje": "ano",
            "id skupiny": "",
            "mpn": "12024514",
            "popis": "",
            "url": "https://boschino.cz/products/snek?variant=456&country=CZ&currency=CZK",
            "url obrázku": "https://cdn.shopify.com/s/files/image.jpg",
            "vlastní štítek 0": "label-zero",
            "vlastní štítek 1": "label-one",
            "vlastní štítek 2": "label-two",
            "vlastní štítek 3": "label-three",
            "vlastní štítek 4": "label-four",
            "značka": "Bosch",
        }

    def test_maps_buyable_availability_prices_labels_and_variant_group(self):
        rows, report = feed.build([self.product])
        row = rows[0]
        self.assertEqual(feed.FIELDS, list(row))
        self.assertEqual("in_stock", row["availability"])
        self.assertEqual("528.00 CZK", row["price"])
        self.assertEqual("499.00 CZK", row["sale_price"])
        self.assertEqual("Bosch", row["brand"])
        self.assertEqual("boschino-cz:/products/snek", row["item_group_id"])
        self.assertEqual("label-four", row["custom_label_4"])
        self.assertEqual("Šnek do mlýnku Bosch", row["description"])
        self.assertEqual(1, report["descriptions_filled_from_title"])

    def test_only_stock_and_backorder_are_included_and_labels_are_optional(self):
        backorder = copy.deepcopy(self.product)
        backorder["id"] = "backorder-id"
        backorder["dostupnost"] = "doobjednávka"
        backorder["vlastní štítek 4"] = ""
        out_of_stock = copy.deepcopy(self.product)
        out_of_stock["id"] = "out-of-stock-id"
        out_of_stock["dostupnost"] = "není skladem"
        rows, report = feed.build([self.product, backorder, out_of_stock])
        self.assertEqual(2, len(rows))
        self.assertEqual({"in_stock", "backorder"}, {row["availability"] for row in rows})
        self.assertEqual("", next(row["custom_label_4"] for row in rows if row["id"] == "backorder-id"))
        self.assertEqual(1, report["excluded"]["availability_not_allowed"])

    def test_invalid_sale_price_is_omitted_and_missing_identifiers_excluded(self):
        bad_sale = copy.deepcopy(self.product)
        bad_sale["cena v akci"] = "600.00 CZK"
        no_identifier = copy.deepcopy(self.product)
        no_identifier["id"] = "no-identifier"
        no_identifier["gtin"] = ""
        no_identifier["mpn"] = ""
        rows, report = feed.build([bad_sale, no_identifier])
        self.assertEqual(1, len(rows))
        self.assertEqual("", rows[0]["sale_price"])
        self.assertIn("identifier exists but GTIN and MPN are missing", report["excluded"])


if __name__ == "__main__":
    unittest.main()
