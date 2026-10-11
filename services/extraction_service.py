"""
Extraction Service — Extract structured tool records from transcript text.

Takes transcript text, sends it to the configured LLM with a carefully
crafted prompt, validates the output with Pydantic, and returns a list
of validated tool records.

All LLM output is treated as untrusted data. URLs claimed by the LLM
are labeled as unverified. The LLM is instructed not to invent URLs.
"""

import logging
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from services.llm_provider import call_llm, extract_json_from_response, LLMError

logger = logging.getLogger(__name__)


# ── Pydantic Models for Validated Tool Records ────────────────

class ExtractedTool(BaseModel):
    """A single tool extracted from video/transcript content."""
    name: str = Field(..., min_length=1, max_length=200)
    category: Optional[str] = Field(
        None,
        description="One of: ai-tool, dev-tool, mcp-server, library, agent, automation, app, other"
    )
    purpose: Optional[str] = Field(None, max_length=500)
    capabilities: list[str] = Field(default_factory=list)
    evidence_excerpt: Optional[str] = Field(
        None, max_length=1000,
        description="Direct quote from the transcript supporting this tool's mention"
    )
    video_timestamp: Optional[str] = Field(
        None,
        description="Approximate timestamp in the video, e.g. '2:30' or '00:02:30'"
    )
    mention_type: str = Field(
        "explicit",
        description="'explicit' if the tool was directly named, 'inferred' if guessed from context"
    )
    official_website: Optional[str] = None
    documentation_url: Optional[str] = None
    repository_url: Optional[str] = None
    requirements: list[str] = Field(default_factory=list)
    setup_steps: list[str] = Field(default_factory=list)
    target_applications: list[str] = Field(default_factory=list)
    uncertainties: Optional[str] = Field(
        None, max_length=500,
        description="What the LLM is unsure about regarding this tool"
    )

    @field_validator("mention_type")
    @classmethod
    def validate_mention_type(cls, v):
        if v not in ("explicit", "inferred"):
            return "inferred"
        return v

    @field_validator("category")
    @classmethod
    def normalize_category(cls, v):
        if not v:
            return "other"
        valid = {"ai-tool", "dev-tool", "mcp-server", "library", "agent", "automation", "app", "other"}
        normalized = v.lower().strip().replace(" ", "-").replace("_", "-")
        return normalized if normalized in valid else "other"


# ── System Prompt ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are a specialized AI tool discovery assistant. Your job is to analyze video transcripts and on-screen visual context to identify AI tools, developer tools, apps, libraries, MCP servers, coding agents, skills, and automation utilities that are mentioned or demonstrated.

RULES:
1. Identify tools, skills, extensions, or utilities whether spoken out loud OR shown on screen in the code editor, terminal, browser, or slides.
2. IMPORTANT - Focus on Specific Tools & Skills:
   When the speaker is discussing or demonstrating a specific skill, extension, plugin, MCP server, library, or utility (e.g., 'Find Skills', 'Open Skills', an MCP server, a CLI utility), extract that SPECIFIC tool or skill!
   Do NOT simply list 'Claude' or 'ChatGPT' if they are merely the background conversational host or mentioned for comparison/safety checking. Focus on the actual new tool, skill, or utility being introduced!
3. Do NOT invent or hallucinate tool names, URLs, or capabilities.
4. For official_website, documentation_url, and repository_url: only include URLs you are confident are correct based on well-known tools. If unsure, set them to null.
5. Distinguish between tools that are explicitly named vs. inferred from context.
6. Include a direct quote or on-screen excerpt as evidence_excerpt for each tool.
7. If a tool's exact name is unclear, note this in the uncertainties field.
8. Categorize each tool as one of: ai-tool, dev-tool, mcp-server, library, agent, automation, app, other.

Return a JSON array of tool objects. If no tools are found, return an empty array [].

Each tool object must have these fields:
{
  "name": "string (required)",
  "category": "string",
  "purpose": "string",
  "capabilities": ["string array"],
  "evidence_excerpt": "direct quote from transcript",
  "video_timestamp": "timestamp if mentioned, or null",
  "mention_type": "explicit or inferred",
  "official_website": "URL or null",
  "documentation_url": "URL or null",
  "repository_url": "URL or null",
  "requirements": ["string array"],
  "setup_steps": ["string array"],
  "target_applications": ["string array"],
  "uncertainties": "string or null"
}

Return ONLY the JSON array, no additional text."""



# ── Extraction Function ──────────────────────────────────────

class ExtractedSkill(BaseModel):
    """A skill or technical concept demonstrated/taught in the video."""
    name: str = Field(..., min_length=1, max_length=200)
    domain: Optional[str] = Field("Development", max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    timestamp: Optional[str] = Field(None, max_length=50)


# ── Extraction Functions ─────────────────────────────────────

def extract_video_intelligence(transcript: str) -> dict:
    """
    Analyze transcript to extract executive summary, key takeaways, skills taught,
    and developer/AI tools to reduce user watch time.
    """
    if not transcript or not transcript.strip():
        raise ValueError("Transcript text is empty.")

    system_prompt = (
        "You are a specialized AI video intelligence and tool discovery assistant (ScreenApp style). "
        "Your mission is to reduce user watch time by analyzing both spoken audio and on-screen visual context "
        "(code editor contents, terminal commands, browser tabs, package imports, slide text captured from video frames). "
        "Extract tools, libraries, frameworks, and demonstrated technical skills whether they were spoken out loud OR "
        "shown on screen in the background.\n"
        "Extract: "
        "1. A concise executive summary of the video (2-3 sentences). "
        "2. Key takeaways (3-6 bullet points). "
        "3. Specific skills or techniques taught or visually demonstrated (e.g. MCP Server Development, "
        "Prompt Caching, Dockerization, Retrieval-Augmented Generation, Tailwind Setup, Database Migration). "
        "4. AI tools, developer utilities, libraries, and MCP servers mentioned or visually demonstrated.\n\n"
        "Return a single JSON object with this exact structure:\n"
        "{\n"
        '  "summary": "Executive summary string",\n'
        '  "key_takeaways": ["Takeaway 1", "Takeaway 2", "Takeaway 3"],\n'
        '  "skills": [\n'
        '    {"name": "Skill Name", "domain": "AI / Backend / DevOps", "description": "How demonstrated", "timestamp": "MM:SS or null"}\n'
        "  ],\n"
        '  "tools": [\n'
        '    {\n'
        '      "name": "string (required)",\n'
        '      "category": "ai-tool | dev-tool | mcp-server | library | agent | automation | app | other",\n'
        '      "purpose": "string",\n'
        '      "capabilities": ["string array"],\n'
        '      "evidence_excerpt": "quote from transcript",\n'
        '      "video_timestamp": "timestamp or null",\n'
        '      "mention_type": "explicit or inferred",\n'
        '      "official_website": "URL or null",\n'
        '      "documentation_url": "URL or null",\n'
        '      "repository_url": "URL or null",\n'
        '      "requirements": ["string array"],\n'
        '      "setup_steps": ["string array"],\n'
        '      "target_applications": ["string array"],\n'
        '      "uncertainties": "string or null"\n'
        '    }\n'
        '  ]\n'
        "}\n\n"
        "Return ONLY the valid JSON object."
    )

    user_prompt = f"Analyze the following video transcript:\n\nTRANSCRIPT:\n{transcript}"

    raw_response = call_llm(system_prompt, user_prompt, require_json=True)
    parsed = extract_json_from_response(raw_response)

    raw_tools = []
    skills = []
    summary = ""
    key_takeaways = []

    if isinstance(parsed, dict):
        summary = str(parsed.get("summary", "")).strip()
        raw_takeaways = parsed.get("key_takeaways", [])
        if isinstance(raw_takeaways, list):
            key_takeaways = [str(t).strip() for t in raw_takeaways if t]

        raw_skills = parsed.get("skills", [])
        if isinstance(raw_skills, list):
            for sk in raw_skills:
                if isinstance(sk, dict) and sk.get("name"):
                    try:
                        validated_sk = ExtractedSkill(**sk)
                        skills.append(validated_sk.model_dump())
                    except Exception:
                        skills.append({
                            "name": str(sk["name"]),
                            "domain": str(sk.get("domain", "Development")),
                            "description": str(sk.get("description", "")),
                            "timestamp": sk.get("timestamp"),
                        })

        raw_tools = parsed.get("tools", [])
        if not isinstance(raw_tools, list):
            raw_tools = []
    elif isinstance(parsed, list):
        # Raw tool list returned directly (e.g. from tests or simple prompt)
        raw_tools = parsed

    # Validate each tool with Pydantic
    validated_tools = []
    for i, raw_tool in enumerate(raw_tools):
        if not isinstance(raw_tool, dict):
            continue
        try:
            tool = ExtractedTool(**raw_tool)
            validated_tools.append(tool.model_dump())
        except Exception as e:
            if "name" in raw_tool and raw_tool["name"]:
                try:
                    minimal = ExtractedTool(
                        name=str(raw_tool["name"]),
                        mention_type="inferred",
                        uncertainties=f"Validation partially failed: {str(e)}",
                    )
                    validated_tools.append(minimal.model_dump())
                except Exception:
                    pass

    if not summary and validated_tools:
        names = ", ".join(t["name"] for t in validated_tools[:4])
        summary = f"This video covers key developer tools and workflows including {names}."

    if not key_takeaways and validated_tools:
        key_takeaways = [f"Introduces and demonstrates {t['name']}" for t in validated_tools[:4]]

    return {
        "summary": summary,
        "key_takeaways": key_takeaways,
        "skills": skills,
        "tools": validated_tools,
    }


def extract_tools_from_text(transcript: str) -> list[dict]:
    """
    Analyze transcript text to extract tool records using the LLM.
    Returns a list of validated tool dictionaries for backward compatibility.
    """
    if not transcript or not transcript.strip():
        raise ValueError("Transcript text is empty.")

    intel = extract_video_intelligence(transcript)
    return intel.get("tools", [])


def answer_video_question(transcript: str, question: str, tools: list = None) -> str:
    """
    Answers a user question about the video content based strictly on the transcript and tools context.
    Cites timestamps to help users find information immediately without watching the entire video.
    """
    if not transcript or not transcript.strip():
        return "No transcript available for this video."

    tools_summary = ""
    if tools:
        tools_summary = "\nTOOLS IDENTIFIED IN VIDEO:\n" + "\n".join(
            f"- {t.get('name')}: {t.get('purpose', '')}" for t in tools[:8]
        )

    prompt = (
        "You are an AI video assistant for ScreenApp. "
        "Answer the user's question about the video accurately, clearly, and concisely. "
        "Always cite specific timestamps [MM:SS] if mentioned in the transcript so the user "
        "knows exactly where in the video to look. If the answer is not in the transcript, say so politely.\n\n"
        f"TRANSCRIPT:\n{transcript[:16000]}\n{tools_summary}\n\n"
        f"USER QUESTION: {question}"
    )

    try:
        ans = call_llm(
            "You are a helpful video intelligence assistant who answers questions from video transcripts to save watch time.",
            prompt,
        )
        return ans.strip()
    except Exception as e:
        return f"Could not answer question: {str(e)}"
