"""
Configuration & AI App Integration Service — Target Application Adapters.

Supports VS Code and Claude Code as primary target AI coding applications.
Identifies integration type: MCP server, extension, skill, plugin, package, or manual.
Generates structured installation plans with prerequisites, permissions,
commands, configuration diffs, potential risks, and verification steps.
Provides copyable prompts for AI assistants and payloads for the Local Companion Service.
"""

import re
import json
from typing import Dict, Any, List, Optional


class ConfigError(Exception):
    """Raised when configuration generation fails."""
    pass


SUPPORTED_TARGETS = {
    "vscode": "VS Code",
    "claude-code": "Claude Code",
}


def _safe_id(name: str) -> str:
    """Convert a tool name to a safe alphanumeric lowercase slug."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    return slug or "unnamed-tool"


def identify_integration_type(tool: dict, target: str) -> str:
    """
    Identify the most appropriate integration type for a tool and target app.
    Returns one of: 'mcp-server', 'extension', 'skill', 'package', 'manual'.
    """
    category = (tool.get("category") or "").lower()
    name = (tool.get("name") or "").lower()
    purpose = (tool.get("purpose") or "").lower()

    if category == "mcp-server" or "mcp" in name or "model context protocol" in purpose:
        return "mcp-server"

    if target == "vscode":
        if category in ("extension", "ai-tool", "agent", "dev-tool"):
            return "extension"
        elif category in ("library", "package"):
            return "package"
        return "manual"

    elif target == "claude-code":
        if category in ("agent", "automation", "skill"):
            return "skill"
        elif category in ("library", "package"):
            return "package"
        return "mcp-server" if "server" in name else "manual"

    return "manual"


def generate_install_plan(tool: dict, target: str) -> Dict[str, Any]:
    """
    Generate a comprehensive, structured installation plan for an AI coding app.
    
    Returns structured dict containing:
      - tool_name
      - target_app
      - target_label
      - integration_type
      - prerequisites
      - permissions
      - commands
      - config_changes
      - potential_risks
      - verification_step
      - copyable_prompt
      - companion_payload (safe instructions for Local Companion)
    """
    if target not in SUPPORTED_TARGETS:
        supported = ", ".join(SUPPORTED_TARGETS.keys())
        raise ConfigError(f"Unsupported target '{target}'. Supported: {supported}")

    tool_name = tool.get("name", "Unknown Tool")
    category = tool.get("category", "other")
    safe_slug = _safe_id(tool_name)
    integration_type = identify_integration_type(tool, target)
    requirements = tool.get("requirements") or []
    setup_steps = tool.get("setup_steps") or []
    official_website = tool.get("official_website")
    docs_url = tool.get("documentation_url")

    prerequisites = list(requirements) if requirements else []
    permissions = []
    commands = []
    config_changes = {}
    risks = []
    verification_step = ""
    companion_payload = None

    if target == "claude-code":
        target_label = "Claude Code"
        if integration_type == "mcp-server":
            prerequisites.append("Node.js (>= 18.0.0) or Python (>= 3.10)")
            permissions.extend([
                "Read/write local workspace files (if required by server)",
                "Network access to external APIs specified by the MCP server"
            ])
            command = f"claude mcp add {safe_slug} npx -y @{safe_slug}/server"
            commands.append(command)
            config_snippet = {
                "mcpServers": {
                    safe_slug: {
                        "command": "npx",
                        "args": ["-y", f"@{safe_slug}/server"]
                    }
                }
            }
            config_changes = {
                "file": "~/.claude.json or claude_desktop_config.json",
                "format": "json",
                "snippet": json.dumps(config_snippet, indent=2)
            }
            risks.append("Running MCP server executes npx packages. Always verify npm package author.")
            verification_step = f"Run 'claude mcp list' to confirm '{safe_slug}' is active."
            companion_payload = {
                "action": "add_claude_mcp",
                "server_name": safe_slug,
                "command": "npx",
                "args": ["-y", f"@{safe_slug}/server"]
            }

        else:
            prerequisites.append("Claude Code CLI installed and authenticated")
            permissions.append("CLI command execution in workspace")
            if setup_steps:
                commands.extend(setup_steps)
            else:
                commands.append(f"# Add {tool_name} to your Claude Code workspace instructions")
            risks.append("Review third-party scripts before approving in Claude Code.")
            verification_step = f"Ask Claude Code: 'Check if {tool_name} is accessible.'"

    elif target == "vscode":
        target_label = "VS Code"
        if integration_type == "mcp-server":
            prerequisites.append("VS Code with GitHub Copilot / Cline / Roo Code / compatible MCP extension")
            permissions.append("Local process execution via npx or python")
            config_snippet = {
                "mcp": {
                    "servers": {
                        safe_slug: {
                            "command": "npx",
                            "args": ["-y", f"@{safe_slug}/server"]
                        }
                    }
                }
            }
            config_changes = {
                "file": ".vscode/settings.json or Global settings.json",
                "format": "json",
                "snippet": json.dumps(config_snippet, indent=2)
            }
            commands.append(f"# Add server definition to VS Code settings.json")
            risks.append("Executing external MCP server processes.")
            verification_step = "Check VS Code MCP output logs for server connection status."
            companion_payload = {
                "action": "add_vscode_mcp",
                "server_name": safe_slug,
                "command": "npx",
                "args": ["-y", f"@{safe_slug}/server"]
            }

        elif integration_type == "extension":
            ext_id = f"{safe_slug}.{safe_slug}"
            prerequisites.append("VS Code installed and added to PATH (code command)")
            permissions.append("Extension privileges within VS Code sandbox")
            commands.append(f"code --install-extension {ext_id}")
            risks.append("Verify publisher authenticity in VS Code Marketplace.")
            verification_step = f"code --list-extensions | grep {safe_slug}"
            companion_payload = {
                "action": "install_vscode_extension",
                "extension_id": ext_id
            }

        else:
            prerequisites.append("VS Code workspace")
            if setup_steps:
                commands.extend(setup_steps)
            else:
                commands.append(f"# Follow setup guide for {tool_name}")
            verification_step = "Verify tool availability in workspace terminal."

    # Generate a copyable assistant prompt
    copyable_prompt = (
        f"Please install and configure {tool_name} for my {target_label} environment.\n"
        f"Category: {category}\n"
        f"Integration Type: {integration_type}\n"
        f"Prerequisites: {', '.join(prerequisites) if prerequisites else 'None specified'}\n"
        f"Instructions: {'; '.join(commands) if commands else 'See official documentation.'}\n"
        f"Documentation: {docs_url or official_website or 'N/A'}"
    )

    return {
        "tool_name": tool_name,
        "target_app": target,
        "target_label": target_label,
        "integration_type": integration_type,
        "prerequisites": prerequisites,
        "permissions": permissions,
        "commands": commands,
        "config_changes": config_changes,
        "potential_risks": risks,
        "verification_step": verification_step,
        "copyable_prompt": copyable_prompt,
        "companion_payload": companion_payload,
        "documentation_link": docs_url or official_website,
    }


def generate_config(tool: dict, target: str) -> dict:
    """Legacy compatibility function for Phase 2 tests and routes."""
    plan = generate_install_plan(tool, target)
    config_snippet = plan.get("config_changes", {}).get("snippet")
    if not config_snippet and plan["integration_type"] == "extension":
        config_snippet = f"// VS Code Extension: {plan['tool_name']}"

    instructions_parts = []
    if plan["integration_type"] == "extension":
        instructions_parts.append("Open VS Code Extensions panel (Ctrl+Shift+X) and search.")
    if plan["commands"]:
        instructions_parts.extend(plan["commands"])
    else:
        instructions_parts.append("No automated commands available.")

    return {
        "tool_name": plan["tool_name"],
        "target_label": plan["target_label"],
        "config_content": config_snippet,
        "instructions": "\n".join(instructions_parts),
        "dependencies": plan["prerequisites"],
        "documentation_link": plan["documentation_link"],
        "warnings": plan["potential_risks"],
    }

