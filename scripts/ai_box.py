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

WAKA_URL = "https://wakatime.com/api/v1/users/current/stats/"
GIST_API = "https://api.github.com/gists/"

BAR_WIDTH = 18
FILLED, EMPTY = "█", "░"

# 본문에는 이모지를 쓰지 않습니다. 라벨만으로 의미가 충분하고, 좁은 pin 카드에서
# 폭을 아낄 수 있으며, 이모지마다 표시 폭이 달라 고정폭 정렬이 깨지는 문제도 없앨 수 있습니다.
# 귀여움은 제목 한 줄이 담당합니다.


def get_json(url: str, headers: dict | None = None) -> dict:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def bar(percent: float) -> str:
    filled = round(percent / 100 * BAR_WIDTH)
    return FILLED * filled + EMPTY * (BAR_WIDTH - filled)


def row(label: str, value: str, percent: float) -> str:
    return f"{label:<12}{value:<14}{bar(percent)} {percent:5.1f}%"


def korean_duration(text: str) -> str:
    """WakaTime 의 'hrs/mins/secs' 표기를 한글 문장에 섞이도록 바꿉니다."""
    for source, target in (("hrs", "시간"), ("hr", "시간"), ("mins", "분"), ("min", "분"), ("secs", "초"), ("sec", "초")):
        text = text.replace(f" {source}", target)
    return text


def compact(number: int) -> str:
    """1234567 -> '1.2M'. Keeps token/line counts from blowing up the line width."""
    for limit, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if number >= limit:
            return f"{number / limit:.1f}{suffix}"
    return f"{number:,}"


def section(title: str, items: list, value_key: str = "text") -> list[str]:
    """Render a WakaTime list section (editors / languages / ...) as bar rows."""
    if not items:
        return []
    rows = [f"\n{title}"]
    for item in items[:4]:
        rows.append(row(item.get("name", "?"), item.get(value_key, "-"), float(item.get("percent", 0))))
    return rows


def build(data: dict, all_time: dict | None = None) -> tuple[str, str]:
    """Returns (gist filename, gist content)."""
    stats = data.get("data", {})
    categories = stats.get("categories", [])
    ai_category = next((c for c in categories if c.get("name") == "AI Coding"), None)
    sessions = stats.get("ai_sessions", 0)

    if not ai_category or not sessions:
        return "아직 시동 거는 중 ❄️", (
            "이번 주엔 아직 기록이 없어요.\n"
            "\n"
            "WakaTime 이 활동을 모으기 시작하면\n"
            "여기가 채워집니다."
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

    # pin 카드는 앞쪽 몇 줄만 보여주고 나머지는 클릭해야 보입니다.
    # 그래서 "어떤 모델을 얼마나" 를 맨 위에, 부가 정보를 아래에 둡니다.
    models = sorted(stats.get("ai_model_breakdown", []), key=lambda m: m.get("lines", 0), reverse=True)
    model_total = sum(m.get("lines", 0) for m in models)
    model_costs = stats.get("ai_model_costs", {}) or {}

    lines = []
    for model in models[:4]:
        name = model.get("name", "?")
        count = model.get("lines", 0)
        share = (count / model_total * 100) if model_total else 0
        spent = model_costs.get(name)
        value = f"{count:,} lines" if not spent else f"{count:,}ㆍ${spent:,.0f}"
        lines.append(row(name, value, share))

    if not lines:
        lines.append(row("AI", f"{ai_added:,} lines", ai_written))
        lines.append(row("Me", f"{human_added + human_deleted:,} lines", by_hand))

    # 이번 주 총량.
    lines.append(f"\n{korean_duration(ai_category.get('text', '-'))} 동안 AI가 {ai_written:.1f}%" + (f" · ${cost:,.2f}" if cost else ""))
    lines.append(f"AI가 {ai_added:,}줄, 제가 {human_added + human_deleted:,}줄 썼어요")

    prompt_avg = stats.get("ai_prompt_length_avg", 0)
    per_session = stats.get("ai_prompt_events_avg_per_session", 0)
    detail = f"{sessions}번 앉아서 {prompts:,}번 물어봤어요"
    if per_session:
        detail += f" (한 번에 {per_session:.1f}개)"
    lines.append(detail)
    if prompt_avg:
        lines.append(f"프롬프트는 평균 {prompt_avg:,.0f}자")

    tokens_in = stats.get("ai_input_tokens", 0)
    tokens_out = stats.get("ai_output_tokens", 0)
    if tokens_in or tokens_out:
        lines.append(f"토큰 {compact(tokens_in)} 넣고 {compact(tokens_out)} 받았어요")

    # 부가 분류. pin 카드 밖이라 잘려도 손해가 없습니다.
    lines += section("── 어디서 짰나", stats.get("editors", []))
    lines += section("── 무슨 언어로", stats.get("languages", []))
    lines += section("── 뭘 하며 보냈나", categories)

    # 누적.
    if all_time:
        total = all_time.get("data", {})
        total_ai = total.get("ai_additions", 0)
        total_cost = total.get("ai_model_total_cost", 0)
        parts = [korean_duration(total.get("human_readable_total", "-"))]
        if total_ai:
            parts.append(f"AI {compact(total_ai)}줄")
        if total_cost:
            parts.append(f"${total_cost:,.0f}")
        lines.append(f"\n── 지금까지 전부\n{' · '.join(parts)}")

    # 제목도 한글. 옆 pin 의 productive-box 가 "I'm a night 🦉" 라
    # 같은 영어 문법을 따르면 따라한 것처럼 읽힙니다.
    if ai_written >= 66:
        title = "오늘도 AI가 운전했어요 🤖"
    elif ai_written >= 33:
        title = "AI랑 같이 짰어요 🤝"
    else:
        title = "제 손으로 짰어요 🎛️"

    return title, "\n".join(lines)


def update_gist(gist_id: str, token: str, filename: str, content: str) -> None:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "ai-box",
    }
    existing = get_json(GIST_API + gist_id, headers)
    old_name = next(iter(existing.get("files", {})), filename)

    # 파일명과 설명을 함께 갱신합니다. pin 카드는 설명이 있으면 그것을 제목으로
    # 쓰기 때문에, 파일명만 바꾸면 생성 당시의 설명이 계속 노출됩니다.
    #
    # Passing `filename` under the old key renames the file in place, so the
    # gist keeps a single file instead of accumulating one per title change.
    payload = json.dumps(
        {"description": filename, "files": {old_name: {"filename": filename, "content": content}}}
    ).encode()
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
        data = get_json(f"{WAKA_URL}last_7_days?api_key={api_key}")
    except urllib.error.HTTPError as error:
        print(f"WakaTime request failed: {error.code} {error.reason}", file=sys.stderr)
        return 1

    # 누적은 없어도 주간만으로 렌더링할 수 있으므로 실패를 치명적으로 다루지 않습니다.
    try:
        all_time = get_json(f"{WAKA_URL}all_time?api_key={api_key}")
    except urllib.error.HTTPError as error:
        print(f"all_time unavailable ({error.code}), rendering weekly only", file=sys.stderr)
        all_time = None

    filename, content = build(data, all_time)
    update_gist(gist_id, token, filename, content)
    print(f"updated gist {gist_id}\n{filename}\n{content}")

    out_file = os.environ.get("OUT_FILE")
    if out_file:
        with open(out_file, "w", encoding="utf-8") as handle:
            handle.write(f"{filename}\n\n{content}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
