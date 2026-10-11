"""
LLM Provider Module — OpenRouter Exclusive Gateway for Free Models.

Uses OpenRouter exclusively as the LLM gateway.
Defaults to openrouter/free for automatic free-model routing.
Retrieves and filters free models from OpenRouter's metadata.
Provides automatic fallback across free models on rate limits or errors.
Strictly prevents switching to paid models.
"""

import os
import json
import logging
import re
from typing import List, Dict, Optional, Any
import requests
from dotenv import load_dotenv

# Ensure environment variables are loaded
load_dotenv()

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
DEFAULT_FREE_MODELS = [
    "openrouter/free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen-2.5-coder-32b-instruct:free",
    "google/gemini-2.0-flash-exp:free",
    "mistralai/mistral-7b-instruct:free",
    "deepseek/deepseek-r1:free",
]

MAX_PROMPT_CHARS = 30_000
MAX_RETRIES = 2


class LLMError(Exception):
    """Raised when the LLM request fails."""
    pass


def get_llm_config() -> dict:
    """Read LLM configuration from environment variables."""
    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("OPENROUTER_MODEL") or os.environ.get("LLM_MODEL") or "openrouter/free"
    base_url = os.environ.get("OPENROUTER_BASE_URL") or os.environ.get("LLM_BASE_URL") or OPENROUTER_BASE_URL
    return {
        "provider": "openrouter",
        "model": model,
        "api_key": api_key,
        "base_url": base_url.rstrip("/"),
        "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", "4096")),
        "timeout": int(os.environ.get("LLM_TIMEOUT", "60")),
    }


def is_configured() -> bool:
    """Check whether the OpenRouter API key is set and non-placeholder."""
    config = get_llm_config()
    key = config["api_key"]
    return bool(key and key not in ("your-api-key-here", "your-openrouter-key-here"))


def fetch_free_models(api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Fetch available models from OpenRouter and filter strictly for free models.
    Always includes openrouter/free as the primary auto-router option.
    Free models have pricing.prompt == '0' and pricing.completion == '0' or id ending with ':free'.
    """
    free_models = [{
        "id": "openrouter/free",
        "name": "OpenRouter Free Auto-Router (openrouter/free)",
        "context_length": 131072,
        "description": "Automatically routes to currently available free models with zero cost",
    }]

    url = f"{OPENROUTER_BASE_URL}/models"
    headers = {"User-Agent": "Personal-Tool-Discovery/1.0"}
    key = api_key or get_llm_config()["api_key"]
    if key and key not in ("your-api-key-here", "your-openrouter-key-here"):
        headers["Authorization"] = f"Bearer {key}"

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("data", [])
            for m in models:
                mid = m.get("id", "")
                if mid == "openrouter/free":
                    continue
                pricing = m.get("pricing", {})
                prompt_price = str(pricing.get("prompt", "1")).strip()
                comp_price = str(pricing.get("completion", "1")).strip()
                
                is_free = (
                    mid.endswith(":free") or 
                    (prompt_price in ("0", "0.0", "0.00") and comp_price in ("0", "0.0", "0.00"))
                )
                if is_free:
                    free_models.append({
                        "id": mid,
                        "name": m.get("name", mid),
                        "context_length": m.get("context_length", 4096),
                        "description": m.get("description", ""),
                    })
            if len(free_models) > 1:
                return free_models
    except Exception as e:
        logger.warning(f"Could not fetch dynamic models from OpenRouter: {e}")

    # Fallback default free model list
    for m in DEFAULT_FREE_MODELS:
        if m != "openrouter/free":
            free_models.append({
                "id": m,
                "name": m.split("/")[-1].replace(":free", " (Free)"),
                "context_length": 32768,
                "description": "Free OpenRouter model"
            })
    return free_models


def call_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    preferred_model: Optional[str] = None,
    require_json: bool = False,
) -> str:
    """
    Send a chat completion request to OpenRouter using free models only.
    Defaults to openrouter/free and automatically cycles through fallback free models on rate limits,
    outages, or invalid non-JSON output (when require_json=True).
    Never silently switches to paid models.
    """
    config = get_llm_config()

    if not config["api_key"] or config["api_key"] in ("your-api-key-here", "your-openrouter-key-here"):
        raise LLMError(
            "OpenRouter API key is not configured. "
            "Please set OPENROUTER_API_KEY in your .env file."
        )

    if len(user_prompt) > MAX_PROMPT_CHARS:
        user_prompt = user_prompt[:MAX_PROMPT_CHARS] + "\n\n[Transcript truncated]"

    # Prepare model priority: preferred or configured first, followed by default free models
    selected_model = preferred_model or config["model"]
    candidate_models = [selected_model] + [m for m in DEFAULT_FREE_MODELS if m != selected_model]

    url = f"{config['base_url']}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://127.0.0.1:5000",
        "X-Title": "Personal AI Tool Discovery",
    }

    last_error = ""

    for model_name in candidate_models:
        # Strict validation: ensure model is intended to be free
        if not (model_name == "openrouter/free" or model_name.endswith(":free") or model_name in DEFAULT_FREE_MODELS):
            logger.warning(f"Skipping non-free model candidate: {model_name}")
            continue

        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": config["max_tokens"],
        }

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=config["timeout"])

                if resp.status_code == 429:
                    last_error = f"Model {model_name} rate limit reached (HTTP 429). Trying fallback free model..."
                    logger.info(last_error)
                    break  # Break inner loop to try next free model

                if resp.status_code >= 500:
                    last_error = f"OpenRouter server error (HTTP {resp.status_code})"
                    continue

                if resp.status_code != 200:
                    err_msg = ""
                    try:
                        err_msg = resp.json().get("error", {}).get("message", "")
                    except Exception:
                        err_msg = resp.text[:200]
                    last_error = f"OpenRouter request error (HTTP {resp.status_code}): {err_msg}"
                    break  # Try next free model

                data = resp.json()
                choices = data.get("choices", [])
                if not choices:
                    last_error = f"Model {model_name} returned no choices."
                    break

                content = choices[0].get("message", {}).get("content", "")
                if not content:
                    last_error = f"Model {model_name} returned empty content."
                    break

                # If caller specifically requires valid JSON, validate before accepting
                if require_json:
                    try:
                        extract_json_from_response(content)
                    except LLMError as je:
                        last_error = f"Model {model_name} returned non-JSON response ({content.strip()[:100]}): {je}"
                        logger.warning(f"{last_error}. Trying fallback free model...")
                        break

                return content

            except requests.exceptions.Timeout:
                last_error = f"Model {model_name} timed out"
                if attempt < MAX_RETRIES:
                    continue
                break
            except requests.exceptions.ConnectionError:
                raise LLMError(
                    f"Cannot reach OpenRouter at {config['base_url']}. "
                    "Check your network connection."
                )
            except Exception as e:
                last_error = f"Unexpected error with {model_name}: {str(e)}"
                break

    raise LLMError(
        f"All available free OpenRouter models failed or were rate-limited. "
        f"Last error: {last_error}. No paid models will be used automatically."
    )


def extract_json_from_response(text: str) -> list | dict:
    """
    Parse JSON from an LLM response, handling markdown code fences,
    safety evaluation headers (e.g. 'User Safety: safe'), <think> tags,
    trailing commas, and format imperfections.
    Returns the parsed JSON (list or dict).
    Raises LLMError if parsing fails.
    """
    if not text or not isinstance(text, str):
        raise LLMError("Failed to parse JSON from LLM response: empty or invalid content")

    cleaned = text.strip()

    # 1. Strip reasoning tags (<think>...</think>) from reasoning models
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", cleaned, flags=re.IGNORECASE).strip()

    # 2. Strip safety evaluation preambles (e.g. "User Safety: safe", "Safety: safe")
    cleaned = re.sub(
        r"^(?:(?:User|Input|Prompt)?\s*Safety(?:\s+Evaluation)?:\s*\w+[\r\n\s]*)+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    # 3. If there is a markdown code block ```json ... ``` or ``` ... ```, extract its inner content
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if fence_match:
        fenced_content = fence_match.group(1).strip()
        try:
            parsed = json.loads(fenced_content)
            if isinstance(parsed, (list, dict)):
                return parsed
        except json.JSONDecodeError:
            cleaned = fenced_content

    # 4. Try direct json.loads
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, (list, dict)):
            return parsed
    except json.JSONDecodeError:
        pass

    # 5. Try substring between outer [ ] or { }
    for start_char, end_char in [("[", "]"), ("{", "}")]:
        start = cleaned.find(start_char)
        end = cleaned.rfind(end_char)
        if start != -1 and end > start:
            candidate = cleaned[start:end + 1]
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, (list, dict)):
                    return parsed
            except json.JSONDecodeError:
                pass

    # 6. Try json-repair for imperfect LLM formatting (trailing commas, quotes, missing brackets)
    try:
        import json_repair

        # Check bracket candidate first
        for start_char, end_char in [("[", "]"), ("{", "}")]:
            start = cleaned.find(start_char)
            end = cleaned.rfind(end_char)
            if start != -1 and end > start:
                candidate = cleaned[start:end + 1]
                try:
                    repaired = json_repair.loads(candidate)
                    if isinstance(repaired, (list, dict)):
                        return repaired
                except Exception:
                    pass

        # Try whole string
        repaired = json_repair.loads(cleaned)
        if isinstance(repaired, (list, dict)):
            return repaired
    except Exception as e:
        logger.debug(f"json_repair attempt failed: {e}")

    # 7. If all attempts fail, raise descriptive LLMError
    raise LLMError(f"Failed to parse JSON from LLM response: {cleaned[:200] if cleaned else text[:200]}")
