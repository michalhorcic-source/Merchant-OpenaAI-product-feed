import copy
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_boschino_cz_feed_from_merchant_api as api_feed


class MerchantApiFeedTest(unittest.TestCase):
    def setUp(self):
        attrs = {
            "title": "Náhradní díl Bosch",
            "description": "Popis produktu",
            "link": "https://boschino.cz/products/dil?variant=123&country=CZ&currency=CZK",
            "imageLink": "https://cdn.shopify.com/s/files/image.jpg",
            "availability": "IN_STOCK",
            "price": {"amountMicros": "528000000", "currencyCode": "CZK"},
            "salePrice": {"amountMicros": "499000000", "currencyCode": "CZK"},
            "brand": "Bosch",
            "gtins": ["8757521715808"],
            "mpn": "12024514",
            "identifierExists": True,
            "itemGroupId": "group-1",
            "customLabel0": "l0",
            "customLabel1": "l1",
            "customLabel2": "l2",
            "customLabel3": "l3",
            "customLabel4": "l4",
        }
        self.product = {"offerId": "offer-123", "feedLabel": "CZ", "productAttributes": attrs}

    def test_maps_full_required_fields_prices_and_all_five_labels(self):
        with patch.object(api_feed, "MINIMUM_OFFERS", 1):
            rows, report = api_feed.build([self.product])
        row = rows[0]
        self.assertEqual(api_feed.feed.FIELDS, list(row))
        self.assertEqual("in_stock", row["availability"])
        self.assertEqual("528.00 CZK", row["price"])
        self.assertEqual("499.00 CZK", row["sale_price"])
        self.assertEqual("group-1", row["item_group_id"])
        self.assertEqual(["l0", "l1", "l2", "l3", "l4"], [row[f"custom_label_{i}"] for i in range(5)])
        self.assertEqual(1, report["merchant_api_products"])

    def test_filters_only_noncz_nonczk_and_disallowed_availability(self):
        backorder = copy.deepcopy(self.product)
        backorder["offerId"] = "offer-456"
        backorder["productAttributes"]["availability"] = "BACKORDER"
        out_of_stock = copy.deepcopy(self.product)
        out_of_stock["offerId"] = "offer-789"
        out_of_stock["productAttributes"]["availability"] = "OUT_OF_STOCK"
        other_country = copy.deepcopy(self.product)
        other_country["offerId"] = "offer-other"
        other_country["feedLabel"] = "SK"
        other_country["productAttributes"]["link"] = "https://boschino.sk/products/dil"
        with patch.object(api_feed, "MINIMUM_OFFERS", 1):
            rows, _ = api_feed.build([self.product, backorder, out_of_stock, other_country])
        self.assertEqual({"in_stock", "backorder"}, {row["availability"] for row in rows})
        self.assertEqual({"offer-123", "offer-456"}, {row["id"] for row in rows})

    def test_low_count_guard_rejects_incomplete_api_result(self):
        with self.assertRaisesRegex(RuntimeError, "at least 30000"):
            api_feed.build([self.product])

    def test_low_count_diagnostic_contains_only_aggregate_dimensions(self):
        with self.assertRaises(RuntimeError) as caught:
            api_feed.build([self.product])
        message = str(caught.exception)
        self.assertIn('"feed_label": {"CZ": 1}', message)
        self.assertIn('"store_domain": {"boschino.cz": 1}', message)
        self.assertIn('"currency": {"CZK": 1}', message)
        self.assertNotIn("offer-123", message)


if __name__ == "__main__":
    unittest.main()
