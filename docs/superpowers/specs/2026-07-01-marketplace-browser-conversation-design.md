# Browser Conversation Layer Design

## Goal

Add autonomous reading and replying for messages on FL.ru, Freelance.ru, and Weblancer. The layer operates only on orders already linked to a marketplace project and never starts conversations with unknown customers.

## Architecture

Extend the isolated marketplace browser worker with two operations:

- `list_messages`: open the order's project or conversation page and return normalized incoming messages.
- `send_reply`: fill and submit one reply, then require visible confirmation before reporting success.

Provider-specific selectors remain in the worker. The main agent receives normalized records and reuses the existing customer-intent, reply-drafting, execution, revision, and audit pipeline.

## Data Flow

1. Select orders with `platform_browser` contacts and active conversation statuses.
2. Ask the browser worker for messages for that order and marketplace.
3. Reject messages that cannot be linked to the order's project URL or conversation identifier.
4. Store new messages under `orders/<order_id>/inbox/` and append them to `conversation.md` idempotently.
5. Classify intent and generate a reply with the existing AI client.
6. Block unsafe replies using the existing risk policy.
7. In dry-run mode, save the reply draft and browser screenshot without submitting.
8. In live mode, submit once, verify success, and write a sent record.

## Safety And Failure Handling

- No CAPTCHA bypass.
- Authentication loss, CAPTCHA, ambiguous selectors, duplicate forms, and missing submission confirmation are terminal for that attempt.
- Unknown conversations and unlinked messages are ignored and recorded in a health report.
- Message IDs and content hashes prevent duplicate ingestion and duplicate replies.
- Browser failures do not change an order to `outreach_sent`, `payment_requested`, or `closed`.
- Live replies remain disabled until provider dry-runs produce valid screenshots and normalized messages.

## Components

- `marketplace_browser.py`: typed conversation requests and subprocess client methods.
- `marketplace_browser_worker.py`: provider selectors, message extraction, reply form handling, screenshots, and normalized results.
- `marketplace_conversation.py`: idempotent inbox storage and conversation journal updates.
- `local_agent_cli.py`: polling, order linking, AI reply generation, risk checks, sending, and status reporting.
- `Config`: browser conversation enablement, polling limits, and dry-run/live controls.

## Testing

- Unit tests for selector routing, normalization, deduplication, auth/CAPTCHA states, and verified submission.
- Integration tests for linked-order ingestion, safe reply drafts, blocked risky replies, and no duplicate sends.
- Full repository tests before live rollout.
- Live rollout starts in dry-run and records screenshots per supported marketplace.

## Completion Criteria

- New linked customer messages are stored exactly once.
- Safe replies are drafted automatically for all three supported marketplaces.
- Live mode sends only after a verified dry-run for that provider.
- Every attempt has a JSON result and screenshots where a browser page was reached.
- The marketplace report distinguishes `browser_conversation_dry_run`, `platform_auto`, authentication blockers, and layout errors.
