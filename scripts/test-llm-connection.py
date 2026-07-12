#!/usr/bin/env python3
"""Quick diagnostic for the Anthropic SDK connection.

Prints env vars, attempts a tiny completion, surfaces the full error.
"""
import os
import sys
import traceback


def main() -> int:
    print("== Relevant env vars ==")
    for k in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    ):
        v = os.environ.get(k, "")
        if v:
            # Mask tokens, show model names and URLs in full
            if "TOKEN" in k or "KEY" in k:
                print(f"  {k} = <set, length={len(v)}>")
            else:
                print(f"  {k} = {v}")
        else:
            print(f"  {k} = (not set)")
    print()

    try:
        import anthropic
    except ImportError:
        print("anthropic SDK not installed")
        return 1

    print(f"anthropic SDK version: {anthropic.__version__}")
    print()

    # Try with default model names from env (these are what Claude Code uses)
    candidate_models = []
    for k in ("ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL"):
        v = os.environ.get(k)
        if v:
            candidate_models.append(v)
    candidate_models.append("claude-sonnet-4-6")  # our script default
    candidate_models.append("claude-haiku-4-5")
    candidate_models.append("claude-3-5-sonnet-latest")

    # Deduplicate
    seen = set()
    candidate_models = [m for m in candidate_models if not (m in seen or seen.add(m))]
    print(f"Candidate models to try: {candidate_models}")
    print()

    # Don't pass any auth — let SDK use env vars
    try:
        client = anthropic.Anthropic()
    except Exception as exc:
        print(f"Failed to construct client: {exc}")
        traceback.print_exc()
        return 1

    # Print the client's configured base URL + auth header type
    print(f"Client base_url: {client.base_url}")
    print(f"Client auth_token set: {bool(getattr(client, 'auth_token', None))}")
    print(f"Client api_key set: {bool(client.api_key)}")
    print()

    for model in candidate_models:
        print(f"== Trying model: {model} ==")
        try:
            message = client.messages.create(
                model=model,
                max_tokens=50,
                messages=[{"role": "user", "content": "Reply with the word OK only."}],
            )
            text = "".join(b.text for b in message.content if hasattr(b, "text"))
            print(f"  SUCCESS — response: {text!r}")
            print(f"  Model used: {message.model}")
            print(f"  -> Use this model name in the relevant agent prompt or LLM-backed authoring script.")
            return 0
        except Exception as exc:
            # Print full error detail
            exc_type = type(exc).__name__
            print(f"  FAILED ({exc_type}): {exc}")
            # Anthropic's APIStatusError has response/body attributes
            response = getattr(exc, "response", None)
            if response is not None:
                print(f"    HTTP status: {response.status_code}")
                print(f"    URL: {response.url}")
                body = getattr(exc, "body", None) or getattr(response, "text", "")
                if body:
                    print(f"    Body: {body[:500] if isinstance(body, str) else body}")
            print()

    print("All candidate models failed. See errors above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
