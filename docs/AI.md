# AI caption suggestions

Select a saved album photo, then choose **Suggest captions with AI** in Print Studio. The adjacent notice explains that this sends a resized photo to OpenAI. Nothing is sent on upload or selection alone. Choose one of the three returned captions to populate the editable caption field. Sending to a printer remains a separate action.

The backend uses the OpenAI Responses API with `gpt-5.4-mini`, reasoning disabled, low image detail, and at most 700 output tokens. Requests use a fresh JPEG of at most 768 pixels per side with EXIF excluded. The original filename, other album photos, and account details are not included. The API request sets `store: false`; this is not a guarantee of zero retention by the provider.

On the Pi, add `OPENAI_API_KEY=...` to `/etc/memory-cloud.env`, keeping its existing entries and root-only permissions, then restart `memory-web`. Never put the key in static assets or source control. Optional `OPENAI_CAPTION_MODEL` overrides the model; it must support image input, structured outputs, and `reasoning.effort: none`. No new Python dependencies are needed.

Results (three captions, description, tags, token usage) are cached in SQLite by album, photo ID, model, and prompt version. Descriptions and tags are stored for future search; semantic search is not implemented yet. Cached requests do not contact OpenAI. Unsaved color/crop adjustments are not sent; save a color copy and select it first if needed. No automatic regeneration or provider retries occur.

The app enforces 20 uncached attempts per user in a rolling hour and 100 total in a rolling day, including failed provider attempts. Duplicate concurrent requests for a photo are blocked with a two-minute recovery lease. These are request limits, not a guaranteed dollar cap. Review usage in the API dashboard. Cached results are available even without a configured key, but still require album access.

Deployment from the repository root:

```sh
bash pi/deploy/push-to-pi.sh YOUR_USER@YOUR_PI_HOST
```

The update script installs the current app code and restarts its services while
preserving the Pi's database, photos, and environment configuration.

Refresh the browser. SQLite tables are added automatically; existing accounts/photos/jobs are preserved. The installer and package builder include ai_captions.py for future clean installs.

Tests mock the provider: consent, authentication, album isolation, caching, failure cleanup, request limits, in-flight deduplication, image resizing, metadata stripping, and invalid responses. A live provider request with the Pi's key still needs checking after deployment.
