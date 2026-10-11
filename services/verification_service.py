"""
Verification Service — Verify discovered tools against official repositories and documentation.

Checks official URLs, repositories, and package registries without executing untrusted scripts.
Labels unverified claims and computes verification confidence.
"""

import re
import urllib.parse
from typing import Dict, Any, Optional, Tuple
import requests

TRUSTED_DOMAINS = (
    "github.com",
    "gitlab.com",
    "npmjs.com",
    "pypi.org",
    "code.visualstudio.com",
    "anthropic.com",
    "docs.anthropic.com",
    "modelcontextprotocol.io",
    "huggingface.co",
)


def is_trusted_domain(url: str) -> bool:
    """Check if the URL belongs to a well-known trusted ecosystem domain."""
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = (parsed.hostname or "").lower()
        return any(hostname == d or hostname.endswith("." + d) for d in TRUSTED_DOMAINS)
    except Exception:
        return False


def verify_url_accessibility(url: str, timeout: int = 5) -> Tuple[bool, int, str]:
    """
    Check if a URL is reachable via a lightweight HEAD or GET request.
    Returns (is_reachable, status_code, message).
    """
    try:
        headers = {"User-Agent": "Personal-Tool-Discovery-Verifier/1.0"}
        # Fast HEAD request first
        resp = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
        if resp.status_code in (200, 301, 302, 307, 308):
            return True, resp.status_code, "Reachable"
        # If HEAD not allowed (405), fallback to GET
        if resp.status_code == 405:
            resp = requests.get(url, headers=headers, timeout=timeout, stream=True)
            return resp.status_code < 400, resp.status_code, "Reachable via GET"
        return False, resp.status_code, f"Returned HTTP {resp.status_code}"
    except Exception as e:
        return False, 0, f"Connection failed: {str(e)[:100]}"


def verify_tool(tool: Dict[str, Any]) -> Dict[str, Any]:
    """
    Verify tool claims, URLs, and repository existence.
    Returns verification dictionary with verified flag, confidence, and details.
    """
    official_website = tool.get("official_website")
    docs_url = tool.get("documentation_url")
    repo_url = tool.get("repository_url")

    checks = []
    has_trusted_url = False
    reachable_count = 0

    urls_to_check = [
        ("Repository", repo_url),
        ("Documentation", docs_url),
        ("Official Website", official_website),
    ]

    for label, u in urls_to_check:
        if u and str(u).startswith("http"):
            if is_trusted_domain(u):
                has_trusted_url = True
            reachable, status, msg = verify_url_accessibility(u)
            if reachable:
                reachable_count += 1
                checks.append(f"{label} ({u}) verified active [HTTP {status}]")
            else:
                checks.append(f"{label} ({u}) unverified [{msg}]")

    is_verified = (reachable_count > 0 and has_trusted_url)
    confidence = "high" if (reachable_count >= 2 and has_trusted_url) else ("medium" if reachable_count >= 1 else "unverified")

    return {
        "verified": 1 if is_verified else 0,
        "confidence": confidence,
        "verification_details": "; ".join(checks) if checks else "No official URLs provided for verification.",
    }
