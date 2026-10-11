import copy
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_boschino_cz_buyable_ads_feed as ads


class BuyableCzAdsTest(unittest.TestCase):
    def setUp(self):
        self.product = json.loads((ROOT / 'tests/fixtures/boschino-cz-products.json').read_text())[0]
        self.product['productAttributes']['customLabel0'] = 'test-label-zero'
        self.product['productAttributes']['itemGroupId'] = 'PARENT-SKU'
        self.product['productAttributes']['color'] = 'Black'

    def test_all_five_labels_and_both_prices(self):
        rows, report = ads.build([self.product])
        self.assertEqual(ads.FIELDS, list(rows[0]))
        self.assertEqual('test-label-zero', rows[0]['custom_label_0'])
        self.assertEqual('1234.00 CZK', rows[0]['price'])
        self.assertEqual('999.00 CZK', rows[0]['sale_price'])
        self.assertEqual('SKU-1', rows[0]['id'])
        self.assertEqual('PARENT-SKU', rows[0]['item_group_id'])
        self.assertEqual('Black', rows[0]['color'])
        self.assertEqual(1, report['included'])

    def test_regular_price_is_retained_without_sale(self):
        self.product['productAttributes'].pop('salePrice')
        row = ads.build([self.product])[0][0]
        self.assertEqual('', row['sale_price'])
        self.assertEqual('1234.00 CZK', row['price'])

    def test_non_buyable_wrong_market_and_other_source_are_excluded(self):
        excluded = []
        for status in ['OUT_OF_STOCK', 'PREORDER', 'BACKORDER']:
            product = copy.deepcopy(self.product)
            product['productAttributes']['availability'] = status
            excluded.append(product)
        wrong_market = copy.deepcopy(self.product)
        wrong_market['productStatus']['destinationStatuses'][0]['approvedCountries'] = ['SK']
        other_source = copy.deepcopy(self.product)
        other_source['dataSource'] = 'another-source'
        rows, report = ads.build([self.product, *excluded, wrong_market, other_source])
        self.assertEqual(1, len(rows))
        self.assertEqual(3, report['excluded']['not_in_stock'])

    def test_every_label_is_required(self):
        for index in range(5):
            with self.subTest(index=index):
                product = copy.deepcopy(self.product)
                product['productAttributes'].pop(f'customLabel{index}')
                with self.assertRaisesRegex(RuntimeError, f'custom_label_{index}'):
                    ads.build([product])

    def test_duplicate_variant_with_distinct_offer_ids_fails(self):
        self.product['productAttributes']['link'] += '?variant=123'
        self.product['productAttributes']['itemGroupId'] = 'PARENT-SKU'
        duplicate = copy.deepcopy(self.product)
        duplicate['offerId'] = 'different-merchant-id'
        with self.assertRaisesRegex(RuntimeError, 'duplicate storefront variant'):
            ads.build([self.product, duplicate])

    def test_bad_price_and_wrong_storefront_fail(self):
        product = copy.deepcopy(self.product)
        product['productAttributes']['price']['currencyCode'] = 'EUR'
        with self.assertRaisesRegex(RuntimeError, 'CZK'):
            ads.build([product])
        self.product['productAttributes']['link'] = 'https://boschino.sk/products/item'
        with self.assertRaisesRegex(RuntimeError, 'CZ storefront'):
            ads.build([self.product])

    def test_cli_creates_csv_and_does_not_overwrite_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / 'products.json'
            output = directory / 'feed.csv'
            report = directory / 'report.json'
            source.write_text(json.dumps([self.product]))
            command = [sys.executable, str(ROOT / 'scripts/build_boschino_cz_buyable_ads_feed.py'), '--offline-products', str(source), '--output', str(output), '--report', str(report)]
            subprocess.run(command, check=True, capture_output=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'})
            before = output.read_bytes()
            self.assertFalse(before.startswith(b'\xef\xbb\xbf'))
            with output.open(encoding='utf-8', newline='') as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(ads.FIELDS, reader.fieldnames)
                self.assertEqual(1, len(list(reader)))
            self.product['productAttributes'].pop('customLabel0')
            source.write_text(json.dumps([self.product]))
            result = subprocess.run(command, capture_output=True)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(before, output.read_bytes())

    def test_empty_feed_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'empty'):
            ads.build([])


if __name__ == '__main__':
    unittest.main()
