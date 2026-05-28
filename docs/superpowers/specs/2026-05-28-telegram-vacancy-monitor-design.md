# Telegram Vacancy Monitor Design

## Goal

Build a near-free Telegram vacancy monitor that runs in GitHub Actions every five minutes, filters public vacancy posts for tasks Daniil can complete with Codex/AI help, and sends matching items to his Telegram chat.

## Architecture

The project is a small Python CLI. GitHub Actions runs it on a schedule. The CLI downloads public `t.me/s/<channel>` pages, extracts post IDs, text, links, and dates, scores each post with rule-based filters, sends accepted posts through Telegram Bot API, and persists seen post IDs in `data/seen_posts.json`.

## Components

- `src/vacancy_monitor/config.py` reads environment variables and default channel settings.
- `src/vacancy_monitor/sources.py` fetches and parses public Telegram web pages.
- `src/vacancy_monitor/filtering.py` decides whether a post is suitable.
- `src/vacancy_monitor/telegram.py` sends messages through Telegram Bot API.
- `src/vacancy_monitor/state.py` stores already processed posts.
- `src/vacancy_monitor/cli.py` wires the monitor flow together.
- `.github/workflows/monitor.yml` runs the monitor every five minutes and commits state updates.

## Data Flow

1. GitHub Actions checks out the repository.
2. Python installs dependencies from `requirements.txt`.
3. The CLI reads `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and optional channel/filter settings.
4. The CLI fetches each public Telegram source.
5. Unknown posts are filtered and formatted.
6. Matching posts are sent to Telegram.
7. Seen IDs are saved to `data/seen_posts.json`.
8. GitHub Actions commits the updated state file only when it changed.

## First Run Behavior

The first run seeds current posts as seen and sends nothing. This avoids spamming old vacancies. Setting `SEND_FIRST_RUN=true` sends matching current posts during initial setup.

## Constraints

GitHub Actions scheduled workflows can run no more frequently than every five minutes and may be delayed under load. Private Telegram channels cannot be read from public web pages; their posts must be forwarded to an accessible source or added through a future Telegram client integration.

## Testing

Unit tests cover Telegram page parsing, filtering decisions, formatting, and state persistence. Network calls are isolated from tests.
