#!/usr/bin/env python3
"""Read-only login-free test of the saved Open WebUI *service* API key.

Runs one tiny non-streaming chat completion with selected model; does not
touch saved chat_id, require password/MFA, or reveal configured API key.
"""
import argparse
import asyncio
from cute_realtime_gateway import GatewayError, chat_model, load_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    settings = load_settings(args.config)
    async def check():
        answer = await chat_model(
            settings,
            "Réponds en français et en une phrase courte : Bonjour, Kitty.",
            [],
        )
        print("PASS: dedicated API key authenticated to Open WebUI chat model "
              + settings.webui_model)
        print("Model response preview: " + answer[:200])
    try:
        asyncio.run(check())
    except (GatewayError, ValueError, OSError, TimeoutError) as exc:
        print("FAIL: " + str(exc))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
