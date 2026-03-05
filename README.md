# MakerWorld Likes -> Notion (n8n)

This starter polls your MakerWorld Likes page every 15 minutes and upserts rows in your existing `Printables` database.

## 1) Target Notion database (already wired)
This workflow is pre-wired to your existing `Printables` database:

- Database ID: `30f4fc50af3f80a1a702e7862de7187a`
- Required properties used:
- `Name` (Title)
- `Model ID` (Rich text)
- `URL` (URL)
- `Nozzle` (Select)
- `Material` (Relation)
- `Creator` (Rich text)
- `Cover Image URL` (URL)
- `Cover Image` (Files)
- `Scraped At` (Date)
- `Tags` (Rich text)
- `Print Profile Details` (Rich text)

## 2) Notion integration setup
1. Create an internal integration in Notion.
2. Copy the integration token.
3. Share your target database with that integration.
4. Copy database ID from URL.

## 3) Import n8n workflow
Import:

- `makerworld-likes-to-notion.n8n.json`

Then edit node `Sync Into Notion` and set:

- `NOTION_TOKEN = 'secret_...'`

Also edit `Fetch MakerWorld Likes` URL:

- `https://makerworld.com/en/@YOUR_USERNAME/likes`

## 4) Notion API payloads used

### Query existing by Model ID
```json
{
  "filter": {
    "property": "Model ID",
    "rich_text": {
      "equals": "123456"
    }
  },
  "page_size": 1
}
```

### Create page
```json
{
  "parent": {
    "database_id": "30f4fc50af3f80a1a702e7862de7187a"
  },
  "properties": {
    "Name": {
      "title": [
        {
          "text": {
            "content": "My Liked Model"
          }
        }
      ]
    },
    "Model ID": {
      "rich_text": [
        {
          "text": {
            "content": "123456"
          }
        }
      ]
    },
    "URL": {
      "url": "https://makerworld.com/en/models/123456"
    },
    "Creator": {
      "rich_text": [
        {
          "text": {
            "content": "Maker Name"
          }
        }
      ]
    },
    "Cover Image URL": {
      "url": "https://example.com/image.jpg"
    },
    "Tags": {
      "rich_text": [
        {
          "text": {
            "content": "tag1, tag2"
          }
        }
      ]
    },
    "Print Profile Details": {
      "rich_text": [
        {
          "text": {
            "content": "Nozzle 0.4mm | Layer 0.2mm | Material PLA"
          }
        }
      ]
    },
    "Scraped At": {
      "date": {
        "start": "2026-03-05T12:00:00.000Z"
      }
    }
  }
}
```

## Data quality notes
- `Creator`, `Tags`, and `Print Profile Details` are best-effort from public model detail pages.
- If MakerWorld changes page structure, some enrichment fields may be blank.
- `Scraped At` always records when the automation captured the model.

## Notes
- If your likes page is private, add authenticated headers/cookies in `Fetch MakerWorld Likes`.
- First run may import many historical likes.
- Existing records are upserted by `Model ID` (fallback: `URL` for older rows).

## No n8n option (local Mac script)
If you do not use n8n, use the script in:

- `/Users/amandachappell/Documents/Development/makerworld-notion-automation/script/makerworld_to_notion.py`

### One-time setup
1. Copy env template:
```bash
cp /Users/amandachappell/Documents/Development/makerworld-notion-automation/script/.env.example /Users/amandachappell/Documents/Development/makerworld-notion-automation/script/.env
```
2. Edit `.env` and set:
- `NOTION_TOKEN`
- `MAKERWORLD_LIKES_URL`
- `MAKERWORLD_COOKIE` (optional, but needed if MakerWorld returns 403)
- `MAKERWORLD_CATEGORY` (defaults to `Printer Tools`)
- `MATERIAL_PAGE_ID_*` values (optional) to map parsed material names to your Material relation pages

### Manual run
```bash
/Users/amandachappell/Documents/Development/makerworld-notion-automation/script/run_sync.sh
```

### Verbose dry run (no Notion writes)
```bash
/Users/amandachappell/Documents/Development/makerworld-notion-automation/script/run_sync.sh --dry-run --verbose
```
This prints each item payload and whether it would `create` or `update`.

### Category for MakerWorld imports
- Every imported/upserted item sets `Category` from `MAKERWORLD_CATEGORY`.
- Default is `Printer Tools`.
- Allowed values: `Template`, `Ebook`, `Preset`, `Course`, `Bundle`, `TKD Belts`, `Toy`, `Printer Tools`.

### Material + nozzle extraction
- `Nozzle` is auto-filled when parsed value is `0.2mm` or `0.4mm`.
- `Material` is a relation field, so the script needs page IDs to set it.
- Put those IDs in `.env` (example):
```bash
MATERIAL_PAGE_ID_PLA=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
MATERIAL_PAGE_ID_PETG=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

### Fixing `403 Forbidden` from MakerWorld
1. Open your MakerWorld likes page in Chrome/Safari while logged in.
2. Open DevTools -> Network -> refresh page -> click the page request.
3. Copy the full `cookie` request header value.
4. Paste it into `.env` as `MAKERWORLD_COOKIE=...`.
5. Re-run `run_sync.sh`.

### Auto-run every 15 minutes (macOS launchd)
1. Copy plist:
```bash
cp /Users/amandachappell/Documents/Development/makerworld-notion-automation/script/com.amanda.makerworld-notion-sync.plist ~/Library/LaunchAgents/
```
2. Load job:
```bash
launchctl load -w ~/Library/LaunchAgents/com.amanda.makerworld-notion-sync.plist
```
3. Logs:
- `/tmp/makerworld-notion-sync.log`
- `/tmp/makerworld-notion-sync.err.log`

## Tampermonkey option
This option scrapes likes directly in your logged-in browser and sends them to a local receiver.

### Files
- Userscript: `/Users/amandachappell/Documents/Development/makerworld-notion-automation/tampermonkey/makerworld_likes_to_local_notion.user.js`
- Receiver: `/Users/amandachappell/Documents/Development/makerworld-notion-automation/script/makerworld_receiver.py`

### Start local receiver
```bash
/Users/amandachappell/Documents/Development/makerworld-notion-automation/script/run_receiver.sh
```
Health check:
```bash
curl http://127.0.0.1:8765/health
```

### Install userscript
1. Install Tampermonkey in your browser.
2. Create a new script and paste:
- `/Users/amandachappell/Documents/Development/makerworld-notion-automation/tampermonkey/makerworld_likes_to_local_notion.user.js`
3. Save and enable the script.

### Use it
1. Open your MakerWorld likes page while logged in.
2. Click `Sync Likes to Notion` button (bottom-right).
3. Choose dry-run or live mode in the prompt.
4. Check receiver terminal output and Notion updates.

## GitHub Actions option (off your computer)
Use this workflow to run regularly in GitHub:

- `/Users/amandachappell/Documents/Development/makerworld-notion-automation/.github/workflows/makerworld-sync.yml`

### Schedule
- Default: every 30 minutes (`*/30 * * * *`)
- Also supports manual run via `workflow_dispatch` with `dry_run` and `verbose` inputs.

### Debug workflow (manual only)
- `/Users/amandachappell/Documents/Development/makerworld-notion-automation/.github/workflows/makerworld-sync-debug.yml`
- Manual-only, defaults to `dry_run=true` and `verbose=true`.
- Supports optional `likes_url_override` input per run.
- Supports optional `model_id` to test one MakerWorld model without scanning the full likes page.

### Required repo setup
1. Put this project in a GitHub repo.
2. Push the workflow file.
3. In GitHub repo settings, add these Actions secrets:
- `NOTION_TOKEN` (required)
- `MAKERWORLD_LIKES_URL` (required)
- `MAKERWORLD_COOKIE` (optional but likely needed if MakerWorld blocks anonymous requests)
- `MAKERWORLD_CATEGORY` (optional, defaults to `Printer Tools` in script)
- `MATERIAL_PAGE_ID_PLA` (optional)
- `MATERIAL_PAGE_ID_PETG` (optional)
- `MATERIAL_PAGE_ID_ABS` (optional)
- `MATERIAL_PAGE_ID_ASA` (optional)
- `MATERIAL_PAGE_ID_TPU` (optional)
- `MATERIAL_PAGE_ID_PA` (optional)
- `MATERIAL_PAGE_ID_PC` (optional)

### Notes
- If your MakerWorld session cookie expires, update `MAKERWORLD_COOKIE` secret.
- First scheduled run may process many historical likes.
