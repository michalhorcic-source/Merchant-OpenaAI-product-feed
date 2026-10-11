# Authoritative CZ buyable OpenAI Ads feed process

The only approved process for `openai/boschino-cz-buyable-ads.csv` is the daily GitHub Actions job using the Merchant API account `5757276720` and `scripts/build_boschino_cz_feed_from_merchant_api.py`. The user-provided Merchant TSV ZIP is the baseline for transformation rules and validation, not the recurring data source.

- Paginate through the complete Merchant API `products.list` response. Do not filter by Google custom labels, Shopping Ads approval status, or a single data source.
- Keep only CZ storefront offers with a CZK price and availability `IN_STOCK` or `BACKORDER`; publish them as `in_stock` and `backorder`. No other availability is allowed.
- Include all five custom labels, including blank values; blank labels never exclude an offer.
- Preserve `price`; include `sale_price` only when it is valid and lower than `price`.
- Keep required offer fields complete. If the source description is blank, use the source title as a conservative fallback; do not invent product claims.
- Never commit Merchant API responses or credentials. The Actions job reads the service account from `GOOGLE_SERVICE_ACCOUNT_JSON_B64` and uploads only the validated CSV to Pages.
- Fail closed if pagination fails, the API returns no products, or fewer than 30,000 valid offers remain. This protects the existing public feed from incomplete API results.
- Schedule the fresh fetch/build/validate/publish for 23:00 Europe/Prague using paired UTC schedules and a Prague-local timezone gate.

The ZIP converter is retained for offline rule testing. Detailed behavior and checks are documented in [`docs/boschino-cz-buyable-ads-feed.md`](docs/boschino-cz-buyable-ads-feed.md).
