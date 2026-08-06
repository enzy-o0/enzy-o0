#!/usr/bin/env python3
"""
Update a pinned gist with this week's AI coding stats from WakaTime.

WakaTime exposes AI coding data inside the regular weekly stats response:
the time split lives in `categories[]` under the name "AI Coding", and the
line/prompt/token counters are flat keys on `data` (ai_additions,
ai_prompt_events_total, ...). So one request is enough — there is no
separate AI endpoint.

Field names follow anmol098/waka-readme-stats' `make_ai_coding_stats`.

Env:
  WAKATIME_API_KEY  WakaTime API key
  GH_TOKEN          GitHub token with the `gist` scope
  AI_GIST_ID        Target gist id
  OUT_FILE          Optional. Also write the rendered block here.
"""

import json
import os
import sys
import urllib.error
import urllib.request

WAKA_URL = "https://wakatime.com/api/v1/users/current/stats/last_7_days"
GIST_API = "https://api.github.com/gists/"

BAR_WIDTH = 18
FILLED, EMPTY = "█", "░"

# 라벨 이모지는 모두 단일 코드포인트만 씁니다. 변이선택자가 붙은 이모지(예: U+270D U+FE0F)는
# len() 이 2로 세어져 고정폭 패딩이 한 칸씩 밀립니다.
LABEL_AI_TIME, LABEL_AI_LINES, LABEL_HUMAN = "🤖 AI time", "📝 AI written", "🙋 By hand"


def get_json(url: str, headers: dict | None = None) -> dict:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def bar(percent: float) -> str:
    filled = round(percent / 100 * BAR_WIDTH)
    return FILLED * filled + EMPTY * (BAR_WIDTH - filled)


def row(label: str, value: str, percent: float) -> str:
    return f"{label:<14}{value:<14}{bar(percent)} {percent:5.1f}%"


def build(data: dict) -> tuple[str, str]:
    """Returns (gist filename, gist content)."""
    stats = data.get("data", {})
    categories = stats.get("categories", [])
    ai_category = next((c for c in categories if c.get("name") == "AI Coding"), None)
    sessions = stats.get("ai_sessions", 0)

    if not ai_category or not sessions:
        return "🤖 No AI coding tracked this week", (
            "이번 주에는 기록된 AI 코딩 활동이 없어요.\n"
            "\n"
            "WakaTime 플러그인이 설치되어 있고 활동이\n"
            "수집되기 시작하면 이 자리에 채워집니다."
        )

    ai_added = stats.get("ai_additions", 0)
    ai_deleted = stats.get("ai_deletions", 0)
    human_added = stats.get("human_additions", 0)
    human_deleted = stats.get("human_deletions", 0)
    prompts = stats.get("ai_prompt_events_total", 0)
    cost = stats.get("ai_model_total_cost", 0)

    total_added = ai_added + human_added
    ai_written = (ai_added / total_added * 100) if total_added else 0

    total_changed = ai_added + ai_deleted + human_added + human_deleted
    by_hand = ((human_added + human_deleted) / total_changed * 100) if total_changed else 0

    lines = [
        row(LABEL_AI_TIME, ai_category.get("text", "-"), float(ai_category.get("percent", 0))),
        row(LABEL_AI_LINES, f"{ai_added:,} lines", ai_written),
        row(LABEL_HUMAN, f"{human_added + human_deleted:,} lines", by_hand),
    ]

    top_model = max(stats.get("ai_model_breakdown", []), key=lambda m: m.get("lines", 0), default=None)
    if top_model:
        lines.append(f"\n🧠 {top_model['name']} · {prompts:,} prompts · {sessions} sessions")
    else:
        lines.append(f"\n🧠 {prompts:,} prompts · {sessions} sessions")

    if cost:
        lines.append(f"💵 Est. cost ${cost:,.2f}")

    # Mirrors productive-box's "I'm a night 🦉" title convention.
    if ai_written >= 66:
        title = f"🤖 I'm AI-driven ({ai_written:.0f}% AI-written)"
    elif ai_written >= 33:
        title = f"⚖️ I'm balanced ({ai_written:.0f}% AI-written)"
    else:
        title = f"✋ I'm hands-on ({ai_written:.0f}% AI-written)"

    return title, "\n".join(lines)


def update_gist(gist_id: str, token: str, filename: str, content: str) -> None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "ai-box",
    }
    existing = get_json(GIST_API + gist_id, headers)
    old_name = next(iter(existing.get("files", {})), filename)

    # Passing `filename` under the old key renames the file in place, so the
    # gist keeps a single file instead of accumulating one per title change.
    payload = json.dumps({"files": {old_name: {"filename": filename, "content": content}}}).encode()
    request = urllib.request.Request(GIST_API + gist_id, data=payload, headers=headers, method="PATCH")
    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()


def main() -> int:
    api_key = os.environ.get("WAKATIME_API_KEY")
    token = os.environ.get("GH_TOKEN")
    gist_id = os.environ.get("AI_GIST_ID")

    missing = [n for n, v in (("WAKATIME_API_KEY", api_key), ("GH_TOKEN", token), ("AI_GIST_ID", gist_id)) if not v]
    if missing:
        print(f"missing env: {', '.join(missing)}", file=sys.stderr)
        return 1

    try:
        data = get_json(f"{WAKA_URL}?api_key={api_key}")
    except urllib.error.HTTPError as error:
        print(f"WakaTime request failed: {error.code} {error.reason}", file=sys.stderr)
        return 1

    filename, content = build(data)
    update_gist(gist_id, token, filename, content)
    print(f"updated gist {gist_id}\n{filename}\n{content}")

    out_file = os.environ.get("OUT_FILE")
    if out_file:
        with open(out_file, "w", encoding="utf-8") as handle:
            handle.write(f"{filename}\n\n{content}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
