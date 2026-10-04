# data/supplement/

Additional official source pages, added one page at a time (CONTRACT.md 6). The starter
pack in `data/starter/` is never modified.

- `manifest.csv`: same columns as the starter manifest (`doc_id, jurisdictions, url,
  source_type, capture, retrieved_at, sha256, text_file, status`). `source_type` is
  `official`, `capture` is `manual`, `sha256` hashes the stored text file, `text_file` is
  relative to this folder.
- `text/<doc_id>.txt`: the page text, stored byte-for-byte, starting with the corpus header
  (`SOURCE: <url>`, `RETRIEVED: YYYY-MM-DD HH:MM UTC`, blank line).

Add a document with the pipeline, not by hand:

```
python -m navigator ingest-doc path/to/page.txt --jurisdiction "City, ST"
python -m navigator rerun-live path/to/page.txt --jurisdiction "City, ST"   # LLM cache off for this doc
```

`--jurisdiction` can be left out when the url is a starter manifest row without text (for
example a released `check-terms` page) or already has a row here. Files without the header,
with CR line endings, a BOM or no body text are rejected. Doc ids default to `S001`, `S002`, ...
Only capture official pages that the site's terms allow; never bulk-scrape.
