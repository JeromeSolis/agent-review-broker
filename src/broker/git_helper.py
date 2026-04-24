"""Writes a reasoning markdown file, commits, pushes, and returns a github blob URL.

Every platform comment must carry a `github_file_url` — this is a hard server-side
rule. The LLM calls `write_reasoning_and_commit` as a tool and gets back the URL
to pass into `post_comment`/`post_verdict`.
"""

import asyncio
import re
from datetime import UTC, datetime

from broker.config import REPO_ROOT, settings
from broker.logging import log


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower())
    return slug.strip("-")[:60] or "note"


async def _run(cmd: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=REPO_ROOT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout.decode(), stderr.decode()


async def write_reasoning_and_commit(
    title: str,
    body: str,
    *,
    agent_name: str | None = None,
    paper_id: str | None = None,
) -> str:
    """Write a reasoning MD under agent_configs/<name>/reasoning/, push, return URL.

    Retries `git push` once on transient failures. If git fails twice, raises
    so the tool dispatcher surfaces the error back to the LLM — it can then
    retry or abandon the comment attempt.
    """
    agent_name = agent_name or settings.agent_name
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    slug = _slugify(title)
    if paper_id:
        filename = f"{ts}-{_slugify(paper_id)}-{slug}.md"
    else:
        filename = f"{ts}-{slug}.md"

    rel_path = f"agent_configs/{agent_name}/reasoning/{filename}"
    abs_path = REPO_ROOT / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    header_bits = [f"# {title}", f"_agent: `{agent_name}` · ts: {ts}_"]
    if paper_id:
        header_bits.append(f"_paper: `{paper_id}`_")
    content = "\n\n".join(header_bits) + "\n\n" + body.strip() + "\n"
    abs_path.write_text(content)

    rc, out, err = await _run(["git", "add", rel_path])
    if rc != 0:
        raise RuntimeError(f"git add failed: {err.strip()}")

    commit_msg = f"reasoning({agent_name}): {title[:72]}"
    rc, out, err = await _run(["git", "commit", "-m", commit_msg])
    if rc != 0 and "nothing to commit" not in (out + err).lower():
        raise RuntimeError(f"git commit failed: {err.strip() or out.strip()}")

    for attempt in (1, 2):
        rc, out, err = await _run(["git", "push"])
        if rc == 0:
            break
        log.warning("git_push_retry", attempt=attempt, err=err.strip()[:200])
        await asyncio.sleep(2)
    else:
        raise RuntimeError(f"git push failed after 2 attempts: {err.strip()}")

    url = f"{settings.github_repo_url.rstrip('/')}/blob/main/{rel_path}"
    log.info("reasoning_committed", path=rel_path, url=url)
    return url
