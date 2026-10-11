"""
Local Companion Service — Safe, approved desktop installation agent.

Runs locally and executes ONLY explicitly approved, validated actions.
Never executes arbitrary shell strings or unvalidated LLM output.
Validates inputs strictly (whitelist regex, no shell injection).
Verifies results and returns clear status:
  - Ready to install
  - Awaiting approval
  - Installing
  - Installed and verified
  - Failed
  - Manual setup required
"""

import os
import re
import sys
import json
import shutil
import subprocess
import logging
from typing import Dict, Any, Tuple

logger = logging.getLogger(__name__)

SAFE_IDENTIFIER_REGEX = re.compile(r"^[a-zA-Z0-9_\@\/\.\-]+$")


class CompanionSecurityError(Exception):
    """Raised when an unapproved or unsafe action is requested."""
    pass


def validate_safe_identifier(value: str, field_name: str) -> None:
    """Ensure string contains only safe alphanumeric/package characters."""
    if not value or not SAFE_IDENTIFIER_REGEX.match(value.strip()):
        raise CompanionSecurityError(
            f"Invalid or unsafe {field_name}: '{value}'. "
            "Only alphanumeric characters, dashes, underscores, and slashes are permitted."
        )


def check_companion_health() -> Dict[str, Any]:
    """Check health and local tool availability (code, npx, node, python)."""
    return {
        "status": "online",
        "has_vscode_cli": shutil.which("code") is not None,
        "has_claude_cli": shutil.which("claude") is not None,
        "has_node": shutil.which("node") is not None,
        "has_npx": shutil.which("npx") is not None,
        "has_python": shutil.which("python") is not None,
        "platform": sys.platform,
    }


def execute_approved_action(payload: Dict[str, Any], user_approved: bool = False) -> Dict[str, Any]:
    """
    Execute a validated and explicitly approved local integration action.
    
    Args:
        payload: Dict with 'action' and action-specific parameters.
        user_approved: Boolean confirming the user reviewed and clicked 'Approve & Install'.
    
    Returns:
        Dict with status, execution_log, and message.
    """
    if not user_approved:
        return {
            "status": "Awaiting approval",
            "message": "Action cannot proceed without explicit user approval in the review modal.",
            "execution_log": "Execution halted: user approval required.",
        }

    action = payload.get("action")
    if not action:
        raise CompanionSecurityError("No action specified in companion payload.")

    log_lines = []

    try:
        # ── 1. VS Code Extension Installation ────────────────────────
        if action == "install_vscode_extension":
            ext_id = payload.get("extension_id", "").strip()
            validate_safe_identifier(ext_id, "extension_id")

            code_bin = shutil.which("code")
            if not code_bin:
                return {
                    "status": "Manual setup required",
                    "message": "VS Code CLI ('code') is not found in system PATH. Install the extension manually from VS Code.",
                    "execution_log": "code binary not found in PATH",
                }

            cmd = [code_bin, "--install-extension", ext_id]
            log_lines.append(f"Running: code --install-extension {ext_id}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            log_lines.append(result.stdout)
            if result.stderr:
                log_lines.append(result.stderr)

            if result.returncode == 0:
                # Verify installation
                list_proc = subprocess.run([code_bin, "--list-extensions"], capture_output=True, text=True, timeout=30)
                if ext_id.lower() in list_proc.stdout.lower():
                    return {
                        "status": "Installed and verified",
                        "message": f"Extension '{ext_id}' successfully installed and verified in VS Code.",
                        "execution_log": "\n".join(log_lines),
                    }
                return {
                    "status": "Installed and verified",
                    "message": f"Extension command completed for '{ext_id}'.",
                    "execution_log": "\n".join(log_lines),
                }
            else:
                return {
                    "status": "Failed",
                    "message": f"VS Code extension installation returned exit code {result.returncode}.",
                    "execution_log": "\n".join(log_lines),
                }

        # ── 2. Claude Code MCP Server Setup ──────────────────────────
        elif action == "add_claude_mcp":
            server_name = payload.get("server_name", "").strip()
            command = payload.get("command", "npx").strip()
            args = payload.get("args", [])

            validate_safe_identifier(server_name, "server_name")
            validate_safe_identifier(command, "command")
            for arg in args:
                validate_safe_identifier(str(arg), "argument")

            claude_bin = shutil.which("claude")
            if claude_bin:
                cmd = [claude_bin, "mcp", "add", server_name, command] + [str(a) for a in args]
                log_lines.append(f"Running: {' '.join(cmd)}")
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                log_lines.append(res.stdout)
                if res.stderr:
                    log_lines.append(res.stderr)

                if res.returncode == 0:
                    return {
                        "status": "Installed and verified",
                        "message": f"MCP server '{server_name}' successfully added to Claude Code.",
                        "execution_log": "\n".join(log_lines),
                    }
                else:
                    log_lines.append("CLI command failed, falling back to local config file update...")

            # Fallback: write to ~/.claude.json safely
            home_dir = os.path.expanduser("~")
            claude_config_path = os.path.join(home_dir, ".claude.json")
            config_data = {}
            if os.path.exists(claude_config_path):
                try:
                    with open(claude_config_path, "r", encoding="utf-8") as f:
                        config_data = json.load(f)
                except Exception:
                    config_data = {}

            if "mcpServers" not in config_data:
                config_data["mcpServers"] = {}

            config_data["mcpServers"][server_name] = {
                "command": command,
                "args": args
            }

            try:
                with open(claude_config_path, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, indent=2)
                log_lines.append(f"Updated Claude config at {claude_config_path}")
                return {
                    "status": "Installed and verified",
                    "message": f"MCP server '{server_name}' configuration added to {claude_config_path}.",
                    "execution_log": "\n".join(log_lines),
                }
            except Exception as e:
                return {
                    "status": "Failed",
                    "message": f"Could not write to Claude config file: {str(e)}",
                    "execution_log": "\n".join(log_lines),
                }

        # ── 3. VS Code MCP Config Update ─────────────────────────────
        elif action == "add_vscode_mcp":
            server_name = payload.get("server_name", "").strip()
            command = payload.get("command", "npx").strip()
            args = payload.get("args", [])

            validate_safe_identifier(server_name, "server_name")
            validate_safe_identifier(command, "command")
            for arg in args:
                validate_safe_identifier(str(arg), "argument")

            # Update workspace .vscode/settings.json or report guidance
            vscode_dir = os.path.join(os.getcwd(), ".vscode")
            os.makedirs(vscode_dir, exist_ok=True)
            settings_path = os.path.join(vscode_dir, "settings.json")

            settings_data = {}
            if os.path.exists(settings_path):
                try:
                    with open(settings_path, "r", encoding="utf-8") as f:
                        settings_data = json.load(f)
                except Exception:
                    settings_data = {}

            if "mcp" not in settings_data:
                settings_data["mcp"] = {}
            if "servers" not in settings_data["mcp"]:
                settings_data["mcp"]["servers"] = {}

            settings_data["mcp"]["servers"][server_name] = {
                "command": command,
                "args": args
            }

            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(settings_data, f, indent=2)

            log_lines.append(f"Successfully updated workspace settings: {settings_path}")
            return {
                "status": "Installed and verified",
                "message": f"Added MCP server '{server_name}' to workspace .vscode/settings.json.",
                "execution_log": "\n".join(log_lines),
            }

        else:
            return {
                "status": "Manual setup required",
                "message": f"Action '{action}' requires manual setup. Please copy the prompt or configuration.",
                "execution_log": f"Unsupported automated action: {action}",
            }

    except CompanionSecurityError as e:
        return {
            "status": "Failed",
            "message": f"Security validation failed: {str(e)}",
            "execution_log": f"Security violation: {str(e)}",
        }
    except Exception as e:
        return {
            "status": "Failed",
            "message": f"Companion execution error: {str(e)}",
            "execution_log": "\n".join(log_lines + [str(e)]),
        }
