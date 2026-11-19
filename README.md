# Bulgarian Dialectology as Living Tradition: static site pipeline

This pipeline turns a Pantheon backup of the Drupal 7 site into a static website that has the same
pages, URLs and searches as the Drupal site. The result needs no PHP and no database, and has
nothing on the server to patch.

## Rebuilding after edits

1. Make the edits in Drupal as usual.
2. On Pantheon, go to Backups and create a new backup. Download the **database** and **files** archives
   into `backup/`, replacing the old ones. The **code** archive is not needed.
3. Run the build:

   ```
   ./build.sh
   ```

The finished site is written to `site/`. To preview it, run:

```
python3 pipeline/serve.py site      # then open http://localhost:8765
```

The build takes about a minute and needs Python 3.9 or later. It installs `jinja2` and
`phpserialize` the first time it runs.

## How it works

| Stage | Script | What it does |
|---|---|---|
| 1 | `pipeline/extract.py` | Reads the MySQL dump (`*_database.sql.gz`) directly and copies the Drupal tables it needs into `build/raw.sqlite`. No MySQL server is needed. |
| 2 | `pipeline/model.py` | Loads nodes, fields, taxonomy, files and URL aliases into Python objects (the `Corpus`). |
| 3 | `pipeline/build.py` | Writes one HTML page per text, line, token, lexeme, phrase, location, informant, trait, taxonomy term and info page, all at their old URLs. It also writes the search pages, the 404 page and the CSV data download. |
| 3a | `pipeline/search.py` | Exports the search data (`site/assets/data/*.json`) and builds the search forms. The search logic itself runs in the browser (`pipeline/static/search.js`). |
| check | `pipeline/linkcheck.py site` | Confirms that every internal link and image in the generated site resolves. |
| check | `pipeline/compare.py build/raw.sqlite site` | Compares a random sample of generated pages with the live Drupal site. |

## Notes

- **Audio** is not copied into `site/`, because it is about 1 GB. Pages request it from
  `/sites/default/files/audio/` by default. To host it somewhere else, set
  `AUDIO_BASE=https://your-audio-host/path/` before running `build.sh`. Upload the files from the
  backup's `files_live/audio/` folder to that location.
- **Old links still work.** Every URL alias from Drupal is a real page. The 404 page redirects
  `/node/123` and `/taxonomy/term/45` links to the right pages. Old search URLs, such as
  `/wordform-search?field_case_value[]=voc`, run the same search. Old text-page tab links
  (`?qt-text_display_public=2`) open the correct tab.
- **Searches** match the Drupal Views they replace: the same filters, operators and grouping.
  Results were checked against the live site. Like MySQL, text matching ignores case and accents.
  - The Linguistic Trait search shows all results. The old site showed only the first 100.
  - The Linguistic Trait search includes investigators' lines, which is also what the old site
    did, even though its configuration said otherwise.
- **Data clean-up** happens during the build (`pipeline/cleanup.py`); the Drupal database is not touched.
  The build drops the 69 line records that belong to no text, the test/placeholder records (the
  "New location" location, a phrase titled "test", and two test PDFs), and the Drupal import CSVs.
  It also gives the ~1,040 lines whose URLs contained `[field_location_reference-title-raw]` clean
  URLs, and the old URLs redirect to the new ones. Every change is listed in `build/cleanup-report.csv`.
  Tokens that no line uses are kept by default; build with `DROP_ORPHAN_TOKENS=1 ./build.sh` to leave them out.
- **Staging builds:** `STAGING=1 PAGES_DOMAIN=staging.bulgariandialectology.org ./build.sh` adds a
  `noindex` tag to every page and a robots.txt that blocks crawlers, so the review copy stays out of
  search results. Canonical links always point at the main domain (`SITE_URL`). For the launch build,
  leave out `STAGING` and set `PAGES_DOMAIN=bulgariandialectology.org`.
- **Preview with `pipeline/serve.py`, not `python3 -m http.server`.** Python's built-in server can't
  seek inside audio files (it doesn't support HTTP range requests), so audio would only play from the
  beginning. Real web hosts support range requests.
- **After `./build.sh`, run `./add-audio.sh`** to copy the recordings into `site/` for local previews.

## Publishing

The site is published with GitHub Pages from the `gh-pages` branch of
`ralex981/bulgariandialectology-site`, and the audio is served from Cloudflare R2 at
`https://audio.bulgariandialectology.org/`.

```
# staging (review copy, hidden from search engines)
STAGING=1 PAGES_DOMAIN=staging.bulgariandialectology.org \
  AUDIO_BASE=https://audio.bulgariandialectology.org/ ./build.sh
./deploy.sh

# launch / later updates of the public site
PAGES_DOMAIN=bulgariandialectology.org AUDIO_BASE=https://audio.bulgariandialectology.org/ ./build.sh
./deploy.sh
```

`./upload-audio.sh` uploads the recordings to the R2 bucket. You only need to run it again if recordings
are added or changed.
