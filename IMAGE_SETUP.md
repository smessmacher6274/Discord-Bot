# AI image command

**Disabled for deployment.** The command, client initialization, and configuration
are commented out in main.py, config.py, and .env.example. The service source and
tests below are retained for future use. These instructions describe that disabled
feature; it is not available in Discord until explicitly re-enabled.

Use `/computer show me prompt:A dragon guarding a moonlit castle` to generate one
1024×1024 JPEG and return it as a Discord attachment. No voice channel is required.
Generation runs asynchronously and does not stop or pause music.

## Setup

Create an OpenAI API key at https://platform.openai.com/api-keys and save it locally
in this bot's `.env`:

```env
OPENAI_API_KEY=your_api_key
IMAGE_MODEL=gpt-image-2.5-flare
IMAGE_ALLOWED_USER_IDS=
```

Do not paste the key in chat or commit it. API usage is billed separately from
ChatGPT subscriptions; enable API billing and check the selected model's pricing.
Some image models/accounts may require organization verification.
The key and model are read from `.env` each request, so you can add or update them
without restarting the bot. No credentials or prompts are logged by this integration.

By default, only the Discord bot application owner can generate images. To allow
others, put their Discord user IDs in IMAGE_ALLOWED_USER_IDS, separated by commas,
and restart the bot. Everyone allowed uses the configured API account's billing.
The bot needs Attach Files, View Channels, and Send Messages in the request channel.
It posts the image in that channel; do not use sensitive prompts in public channels.

## Behavior and limits

- One image per request, medium quality, JPEG compression 85.
- One generation at a time across the bot, with a 60-second per-user cooldown.
- Prompts: 1–4000 characters. Requests time out after five minutes.
- Files are held in memory and sent directly to Discord; no image archive is saved.
- API failures produce actionable messages without exposing response details or keys.
- No automatic generation retries, avoiding duplicate charges after connection failures.
- Music commands and Spotify exports remain available without an image API key.

Live generation requires the configured key and account access; offline tests use
mock API responses and do not incur image generation costs.

Official reference: https://developers.openai.com/api/reference/resources/images/methods/generate
