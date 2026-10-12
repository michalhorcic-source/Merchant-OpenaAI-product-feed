# CZ buyable OpenAI Ads feed

The recurring feed must be built from a fresh, fully paginated Merchant API `products.list` response for CZ Merchant account `5757276720`. GitHub Actions uses the configured service-account secret and publishes only the resulting validated CSV; API responses and credentials are never committed. The user-provided TSV ZIP is the baseline for transformation rules and offline checks.

To run a fresh build locally, install the pinned OAuth dependency and provide `GOOGLE_SERVICE_ACCOUNT_JSON_B64` securely through the process environment:

```bash
python -m pip install 'google-auth==2.38.0'
python scripts/build_boschino_cz_feed_from_merchant_api.py \
  --output /tmp/boschino-cz-buyable-ads.csv \
  --report /tmp/boschino-cz-buyable-ads-report.json
```

Only CZ storefront offers priced in CZK with availability `IN_STOCK` or `BACKORDER` are included, mapped to `in_stock` and `backorder`. No custom-label, Shopping Ads approval, or single-data-source filter is allowed. Google labels 0–4 are included but never used to select products. `price` is always included; `sale_price` is emitted only when valid and lower than `price`. The output contains required variant data and all five custom-label columns.

When Merchant omits a product description, the product title is reused as a conservative description fallback, without adding unverified claims. A row is excluded if its required offer data or both a valid GTIN and MPN are absent. The baseline export contained 51,802 source rows and produced 35,976 offers (27,031 in stock and 8,945 backorder); it reused the title for 26,064 descriptions and excluded 1,122 rows with neither GTIN nor MPN and 6 rows missing a required offer field. Daily API builds must contain at least 30,000 valid offers; otherwise the workflow fails and leaves the currently published feed intact.

The GitHub Actions workflow fetches a fresh Merchant API snapshot, builds and validates the CSV, and publishes it to Pages daily at 23:00 Europe/Prague. It uses two UTC cron entries (21:00 and 22:00) for daylight saving time and a Prague-local gate so only one run proceeds. Pagination errors, empty responses, missing required fields, and a result below 30,000 offers stop publication. Verify the CZ/CZK target and Google-compatible profile in the OpenAI feed registration before connecting the URL.

Feed A and Feed B are independent, post-validation campaign filters over that same fresh full CZ CSV. Both require `availability=in_stock`, `custom_label_0=CZ1`, label 1 in `Náhradní díl` / `Spotřební materiál` / `Příslušenství`, label 3 in `margin_30_40` / `margin_40_50` / `margin_50_60`, and case-insensitive label 4 from `elephant2` through `elephant10`; the published variants strip all five label columns. A requires `custom_label_2=Bobr0`; B requires `custom_label_2=Bobr1`. A remains fail-closed. B also fails closed by default, while the scheduled workflow deliberately skips a zero-match B without blocking the full feed or A: it retains a previously published, strictly validated nonempty B if one exists, or publishes no B file when the public B URL returns HTTP 404. It never publishes a header-only B. The reserved B public URL is `https://michalhorcic-source.github.io/Merchant-OpenaAI-product-feed/boschino-ads-cz-feed-b.csv`; it is not live until matching products exist and a successful scheduled deployment creates it.
