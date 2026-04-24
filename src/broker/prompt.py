"""System prompt assembly — mirrors the reference repo's reva.prompt exactly."""

from pathlib import Path

from broker.config import REPO_ROOT, settings

SECTION_SEPARATOR = "\n\n---\n\n"


def assemble_prompt(agent_name: str | None = None, koala_base_url: str | None = None) -> str:
    """Concatenate the three prompt files and substitute {KOALA_BASE_URL}.

    Identical structure to koala-science/peer-review-agents/cli/reva/prompt.py:
        GLOBAL_RULES.md + platform_skills.md + agent_configs/<name>/system_prompt.md
    joined by '\\n\\n---\\n\\n' with a single {KOALA_BASE_URL} substitution.
    """
    agent_name = agent_name or settings.agent_name
    koala_base_url = (koala_base_url or settings.koala_base_url).rstrip("/")

    parts = [
        (REPO_ROOT / "agent_definition" / "GLOBAL_RULES.md").read_text().strip(),
        (REPO_ROOT / "agent_definition" / "platform_skills.md").read_text().strip(),
        (REPO_ROOT / "agent_configs" / agent_name / "system_prompt.md").read_text().strip(),
    ]
    joined = SECTION_SEPARATOR.join(parts)
    return joined.replace("{KOALA_BASE_URL}", koala_base_url)


def initial_user_message(agent_name: str | None = None) -> str:
    """Kickoff message handed to the agent on first turn.

    Distilled from the reference repo's DEFAULT_INITIAL_PROMPT — tells the agent
    the transparency workflow (reasoning MD → git push → use URL) and that its
    first moves are read .api_key + check notifications.
    """
    agent_name = agent_name or settings.agent_name
    return f"""You are now live on the Koala Science platform as agent `{agent_name}`.

Startup checklist:

1. Your Koala API key is already loaded into the environment (via `.api_key`). You do not need to read the file yourself — every Koala MCP tool call is authenticated for you.
2. Fetch the live skill guide at {settings.koala_base_url.rstrip('/')}/skill.md and treat it as authoritative over anything else you've been told.
3. Call `get_unread_count` then `get_notifications` — respond to what you find, mark them read.
4. Call `get_papers` with phase filtering to decide what to engage with next.

Transparency workflow for every comment: use the `write_reasoning_and_commit` tool to write a markdown file documenting your reasoning, commit+push it to the agent repo, and pass the returned URL as `github_file_url` on your `post_comment` call. Comments without a valid `github_file_url` are rejected.

Work one action at a time. Check your karma and strike count periodically via `get_actor_profile`. Begin now.
"""
