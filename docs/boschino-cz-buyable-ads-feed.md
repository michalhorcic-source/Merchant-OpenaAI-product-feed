# CZ buyable OpenAI Ads export

This separate export leaves the existing CZ/SK full feeds unchanged. It follows OpenAI's current Google-compatible product-feed profile, confirmed in the official [product specification](https://developers.openai.com/commerce/specs/file-upload/products) and [Ads product-feed guide](https://developers.openai.com/ads/product-feeds#use-the-correct-feed-schema). Upload this format only if OpenAI has confirmed the registered feed uses the Google-compatible profile.

The CSV uses the Google-compatible names: id, title, description, link, image_link, availability, price, and brand. It includes assigned gtin/mpn identifiers, item_group_id and available selected variant attributes, sale_price, and custom_label_0 through custom_label_4. The feed registration supplies seller identity and Ads eligibility; row-level seller_name and is_ads_eligible do not override Google-compatible feed settings. Price is always populated. Sale price is blank when the source has no valid discounted price. Custom labels are optional segmentation fields: populated values are passed through, blank values do not exclude an otherwise valid offer.

The generator reads all products in the configured Merchant API account across its data sources and retains IN_STOCK and BACKORDER CZ offers regardless of Google Shopping Ads approval. Other availability values are excluded. It excludes individual rows missing required export fields, invalid prices or identifiers, or valid variant grouping, and reports reason counts. Empty results prevent publication. Reported stock is Merchant data, not a live checkout verification. If a variant URL includes a Shopify variant ID but Merchant omits item_group_id, the stable product path becomes the parent group ID.

Run tests with the environment's Python virtual environment:

```bash
PYTHONDONTWRITEBYTECODE=1 /workspace/.venvs/merchant-openai-feed/bin/python -m unittest discover -s tests -v
```

A live read requires the existing GOOGLE_SERVICE_ACCOUNT_JSON_B64 credential through a supported local secure binding, or the GitHub Actions repository secret with that name. Never put the credential in source control. The new manually dispatched workflow uses the repository secret, builds and validates the fresh CSV, commits only openai/boschino-cz-buyable-ads.csv, and explicitly deploys GitHub Pages. It does not rely on a GITHUB_TOKEN push triggering a second workflow.

The registered feed must support the CZ country and CZK currency. OpenAI documentation says a Google-compatible feed uses the registered feed target countries and currencies; otherwise its standard upload target is US. Do not connect this CZ file until the existing feed registration confirms Google-compatible processing for CZ.

The public feed path is boschino-cz-buyable-ads.csv relative to the Pages deployment URL returned by GitHub. Verify its HTTP response and actual CSV after deployment before providing it to Ads Manager. Repository branch protection or missing Pages/secret setup can prevent publication; none should be bypassed.

The workflow has not been run and the public feed does not yet exist. OpenAI schema documentation is reachable and has been reviewed. Live Merchant API access, repository workflow-secret presence, feed registration profile/market, and publication still require verification. Roll back source changes by reverting the introducing commit; after deployment, restore any preceding public feed from Git history and rerun the Pages deployment.
