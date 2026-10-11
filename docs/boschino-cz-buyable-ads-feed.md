# CZ buyable OpenAI Ads feed

The current feed is built from the user-provided Merchant Center TSV ZIP export, not a live Merchant API request. The source archive is kept outside the public repository; only the validated CSV, transformation script, and tests are committed. To refresh it from a new export, run:

```bash
python scripts/build_boschino_cz_feed_from_merchant_export.py \
  --input-zip /path/to/merchant-export.zip \
  --output openai/boschino-cz-buyable-ads.csv \
  --report /tmp/boschino-cz-feed-report.json
```

Only source rows marked `skladem` or `doobjednávka` are included, mapped to `in_stock` and `backorder`; all other availability values are excluded. The feed includes Google-compatible required fields, `price`, `sale_price` when it is a valid lower price, and `custom_label_0` through `custom_label_4`. Labels remain blank where absent and do not filter products. Variant grouping uses the export's group ID or, when a Shopify variant URL is present, its stable CZ product path.

When the export omits a product description, the product title is reused as a conservative description fallback, without adding unverified claims. A row is excluded if its required offer data or both a valid GTIN and MPN are absent. The source export had 51,802 rows; the current build included 35,976 offers (27,031 in stock and 8,945 backorder). It reused the title for 26,064 descriptions and excluded 1,122 rows with neither GTIN nor MPN and 6 rows missing a required offer field.

The GitHub Actions workflow validates the committed CSV and publishes it to Pages. It does not query Merchant Center or regenerate the feed from a live API. Verify the CZ/CZK target and Google-compatible profile in the OpenAI feed registration before connecting the URL.
