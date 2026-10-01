#!/usr/bin/env python3
"""Generate a visual HTML project dashboard from GitHub repos.

SECURITY / PRIVACY INVARIANT
----------------------------
Blazefit/project-dashboard is a PUBLIC repo served at
https://blazefit.github.io/project-dashboard/. This generator MUST only write
PUBLIC repos into index.html. Private repo names, descriptions, and URLs must
never be published. Filter at generation time (not as a post-hoc cleanup).
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Prefer the checked-out repo root (Actions / local clone). Fall back to the
# historical Hermes path on daneelbrain for the legacy Monday cron.
REPO_ROOT = Path(os.environ.get("DASHBOARD_REPO_ROOT", "")).expanduser()
if not REPO_ROOT or str(REPO_ROOT) in (".", ""):
    here = Path(__file__).resolve().parent
    if (here / ".git").exists() or (here / "index.html").exists():
        REPO_ROOT = here
    else:
        REPO_ROOT = Path.home() / "hermes" / "project-dashboard"
REPO_ROOT.mkdir(parents=True, exist_ok=True)

OWNER = "Blazefit"
SECURITY_COMMENT = """<!--
  SECURITY / PRIVACY INVARIANT — DO NOT REMOVE.
  This repo is PUBLIC and served via GitHub Pages at
  https://blazefit.github.io/project-dashboard/. It MUST list ONLY public
  repositories. Never publish private (🔐) repo names, descriptions, or URLs
  here — doing so leaks confidential business and infrastructure details to
  anyone on the internet. If a dashboard generator regenerates this file, it
  MUST filter out private repos before writing. Verified: only public (🌐)
  repos are present.
-->"""


def _gh_json(args: list[str]) -> list[dict]:
    cmd = ["gh", *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh failed ({' '.join(cmd)}): {result.stderr}")
    return json.loads(result.stdout or "[]")


def _public_api_repos() -> list[dict]:
    """Unauthenticated users API returns public repos only — safe by design."""
    repos: list[dict] = []
    page = 1
    while True:
        url = (
            f"https://api.github.com/users/{OWNER}/repos"
            f"?per_page=100&type=owner&sort=pushed&direction=desc&page={page}"
        )
        headers = {
                "Accept": "application/vnd.github+json",
                "User-Agent": "blazefit-project-dashboard-generator",
            }
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            batch = json.loads(resp.read().decode("utf-8"))
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    # Normalize to the gh --json shape used below.
    out = []
    for r in repos:
        out.append(
            {
                "name": r.get("name"),
                "description": r.get("description"),
                "updatedAt": r.get("updated_at"),
                "pushedAt": r.get("pushed_at"),
                "visibility": r.get("visibility") or ("private" if r.get("private") else "public"),
                "isFork": bool(r.get("fork")),
                "isPrivate": bool(r.get("private")),
                "primaryLanguage": {"name": (r.get("language") or "")} if r.get("language") else None,
                "url": r.get("html_url"),
                "homepageUrl": r.get("homepage"),
            }
        )
    return out


def run_gh() -> list[dict]:
    """Fetch Blazefit repos, returning PUBLIC only.

    Prefer `gh repo list --visibility public` when gh is authenticated.
    Fall back to the public users API (public-only by definition).
    Always apply an isPrivate filter as a hard invariant.
    """
    repos: list[dict] = []
    try:
        repos = _gh_json(
            [
                "repo",
                "list",
                OWNER,
                "--limit",
                "100",
                "--visibility",
                "public",
                "--json",
                "name,description,updatedAt,pushedAt,visibility,isFork,isPrivate,primaryLanguage,url,homepageUrl",
            ]
        )
    except (RuntimeError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"gh public list unavailable ({exc}); falling back to public API")
        try:
            repos = _public_api_repos()
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as api_exc:
            raise RuntimeError(f"Unable to list public repos: {api_exc}") from api_exc

    public = [r for r in repos if not r.get("isPrivate") and (r.get("visibility") or "public") != "private"]
    skipped = len(repos) - len(public)
    if skipped:
        print(f"Filtered out {skipped} private repo(s) before HTML generation")
    if not public:
        raise RuntimeError("Refusing to write dashboard with zero public repos — aborting to avoid blank wipe")
    # Defense in depth: never proceed if any private slipped through.
    leaked = [r["name"] for r in public if r.get("isPrivate")]
    if leaked:
        raise RuntimeError(f"Private repos survived filter: {leaked}")
    return public


def age_since_push(dt_str: str | None) -> timedelta:
    if not dt_str:
        return timedelta.max
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    return datetime.now(timezone.utc) - dt


def bucket(repo: dict) -> str:
    age = age_since_push(repo.get("pushedAt"))
    if age <= timedelta(days=7):
        return "hot"
    if age <= timedelta(days=30):
        return "warm"
    return "dormant"


def card(repo: dict) -> str:
    name = repo["name"]
    url = repo["url"]
    desc = repo.get("description") or ""
    lang = ""
    if repo.get("primaryLanguage"):
        lang = repo["primaryLanguage"].get("name") or ""
    # Public-only generator: always globe. Never emit the private lock emoji.
    vis = "🌐"
    pushed = (repo.get("pushedAt") or "")[:10]
    return f"""
    <a href="{url}" target="_blank" class="card">
      <div class="card-header">
        <span class="repo-name">{vis} {name}</span>
        <span class="lang">{lang}</span>
      </div>
      <p class="desc">{desc}</p>
      <div class="meta">⭐ {pushed}</div>
    </a>
"""


def group_cards(repos: list[dict], label: str, emoji: str, cls: str) -> str:
    if not repos:
        return ""
    cards = "\n".join(card(r) for r in repos)
    return f"""
    <section class="group {cls}">
      <h2>{emoji} {label} <span class="count">({len(repos)})</span></h2>
      <div class="grid">{cards}</div>
    </section>
"""


def build_html(repos: list[dict]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    hot = [r for r in repos if bucket(r) == "hot"]
    warm = [r for r in repos if bucket(r) == "warm"]
    dormant = [r for r in repos if bucket(r) == "dormant"]

    return f"""<!DOCTYPE html>
{SECURITY_COMMENT}
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🔥 BlazeFit Project Dashboard</title>
<style>
  :root {{
    --bg: #f5f5f7;
    --surface: #ffffff;
    --text: #1d1d1f;
    --text2: #6e6e73;
    --accent: #0071e3;
    --hot: #ff3b30;
    --warm: #ff9500;
    --dormant: #8e8e93;
    --shadow: 0 4px 24px rgba(0,0,0,0.08);
    --radius: 18px;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
    padding: 40px 20px;
  }}
  .wrap {{ max-width: 1200px; margin: 0 auto; }}
  header {{ text-align: center; margin-bottom: 40px; }}
  header h1 {{ font-size: 2.4rem; font-weight: 700; letter-spacing: -0.02em; }}
  header p {{ color: var(--text2); margin-top: 8px; font-size: 1rem; }}
  .stats {{
    display: flex;
    justify-content: center;
    gap: 24px;
    margin-bottom: 40px;
    flex-wrap: wrap;
  }}
  .stat {{
    background: var(--surface);
    padding: 16px 28px;
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    text-align: center;
    min-width: 120px;
  }}
  .stat .num {{ font-size: 1.8rem; font-weight: 700; display: block; }}
  .stat .label {{ font-size: 0.85rem; color: var(--text2); text-transform: uppercase; letter-spacing: 0.05em; }}
  .stat.hot .num {{ color: var(--hot); }}
  .stat.warm .num {{ color: var(--warm); }}
  .stat.dormant .num {{ color: var(--dormant); }}
  .group {{ margin-bottom: 48px; }}
  .group h2 {{
    font-size: 1.3rem;
    font-weight: 600;
    margin-bottom: 20px;
    padding-left: 4px;
  }}
  .group.hot h2 {{ color: var(--hot); }}
  .group.warm h2 {{ color: var(--warm); }}
  .group.dormant h2 {{ color: var(--dormant); }}
  .count {{ color: var(--text2); font-weight: 400; }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 16px;
  }}
  .card {{
    background: var(--surface);
    border-radius: var(--radius);
    padding: 20px;
    box-shadow: var(--shadow);
    text-decoration: none;
    color: inherit;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }}
  .card:hover {{
    transform: translateY(-3px);
    box-shadow: 0 8px 32px rgba(0,0,0,0.12);
  }}
  .card-header {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 12px;
  }}
  .repo-name {{
    font-weight: 600;
    font-size: 1.05rem;
    word-break: break-word;
    color: var(--accent);
  }}
  .lang {{
    font-size: 0.75rem;
    color: var(--text2);
    background: var(--bg);
    padding: 3px 10px;
    border-radius: 12px;
    white-space: nowrap;
  }}
  .desc {{
    font-size: 0.9rem;
    color: var(--text2);
    line-height: 1.4;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }}
  .meta {{
    font-size: 0.8rem;
    color: var(--text2);
    margin-top: auto;
    padding-top: 8px;
  }}
  footer {{
    text-align: center;
    color: var(--text2);
    font-size: 0.85rem;
    margin-top: 20px;
  }}
  @media (max-width: 600px) {{
    header h1 {{ font-size: 1.6rem; }}
    .grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>🔥 Project Dashboard</h1>
      <p>BlazeFit GitHub repo tracker · {now} ET · public repos only</p>
    </header>

    <div class="stats">
      <div class="stat hot"><span class="num">{len(hot)}</span><span class="label">Hot</span></div>
      <div class="stat warm"><span class="num">{len(warm)}</span><span class="label">Warm</span></div>
      <div class="stat dormant"><span class="num">{len(dormant)}</span><span class="label">Dormant</span></div>
      <div class="stat"><span class="num">{len(repos)}</span><span class="label">Total</span></div>
    </div>

    {group_cards(hot, "Hot", "🔥", "hot")}
    {group_cards(warm, "Warm", "🟡", "warm")}
    {group_cards(dormant, "Dormant", "🔴", "dormant")}

    <footer>
      Auto-refreshed every Monday at 7 AM ET · public repos only · <a href="https://github.com/Blazefit" target="_blank" style="color:var(--accent);">github.com/Blazefit</a>
    </footer>
  </div>
</body>
</html>"""


def assert_no_private_markers(html: str) -> None:
    # The SECURITY comment intentionally mentions 🔐. Only fail on card markers.
    if 'repo-name">🔐' in html or "repo-name'>🔐" in html:
        raise RuntimeError("Refusing to write index.html: private-repo lock emoji on a card")


def main() -> None:
    repos = run_gh()
    html = build_html(repos)
    assert_no_private_markers(html)
    out = REPO_ROOT / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"Dashboard written to {out} ({len(repos)} public repos)")

    if os.environ.get("DASHBOARD_SKIP_PUSH") == "1":
        print("DASHBOARD_SKIP_PUSH=1 — skipping git commit/push")
        return

    # Auto-push to GitHub Pages (legacy Hermes cron + optional local runs)
    subprocess.run(["git", "-C", str(REPO_ROOT), "add", "index.html"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "commit",
            "-m",
            f"Update dashboard {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        ],
        check=False,
    )
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "push", "origin", "main"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        print("Pushed to https://blazefit.github.io/project-dashboard/")
    else:
        print(f"Git push output: {result.stdout} {result.stderr}")


if __name__ == "__main__":
    main()
