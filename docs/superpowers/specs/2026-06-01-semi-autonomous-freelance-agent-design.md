# Semi-Autonomous Freelance Agent Design

## Goal

Extend the existing vacancy monitor into a local semi-autonomous freelance agent. The agent should find suitable one-off freelance projects, prepare outreach, support discovery with the customer, create a per-order workspace, and notify Daniil when a decision or payment action is required.

The first version must keep Daniil in control of reputation-sensitive and financial decisions. The agent never sends the first outreach, commits to price, commits to deadlines, sends deliverables, or requests payment without explicit Telegram approval.

## Scope

The first version supports these project categories:

- Telegram bots.
- Automations and parsers.
- Text and content work.
- Spreadsheets and dashboards.

The first version runs locally on Daniil's computer. It stores state in JSON files inside the repository and creates a separate folder for each order.

AI execution is manual in the first version. The agent prepares a `prompt.md` file and a short Telegram summary for Codex or ChatGPT, but it does not call the OpenAI API itself.

## Non-Goals

The first version does not include:

- Direct OpenAI API calls.
- A web dashboard.
- A cloud database.
- Automatic payment acceptance.
- Automatic login to freelance exchanges through browser automation.
- Anti-bot bypasses or scraping behind authentication walls.
- Autonomous agreement on price, deadline, guarantees, or payment terms.

## Architecture

Add a new local agent mode beside the current monitor. The current monitor remains responsible for finding candidate vacancies from public Telegram pages and RSS feeds. The new agent turns accepted vacancies into order records and coordinates approvals through Telegram.

Core components:

- `monitor`: reads public Telegram and RSS sources, filters suitable jobs, and passes accepted posts to the agent.
- `order store`: stores order state in JSON files and maintains an index for quick lookup.
- `telegram control bot`: sends Daniil order cards and inline approval buttons.
- `conversation adapter`: handles customer contact channels when a safe and explicit channel is available.
- `workspace builder`: creates a per-order working folder with human-readable files.
- `draft executor`: prepares files and Telegram summaries for manual Codex or ChatGPT execution.

## Order Lifecycle

Orders move through these statuses:

1. `new`: a suitable job has been found and persisted.
2. `awaiting_response_approval`: the agent drafted the first outreach and is waiting for Daniil's approval.
3. `outreach_sent`: the first outreach was sent through an automated supported channel.
4. `manual_send_needed`: the agent prepared a message, but Daniil must send it manually.
5. `send_failed`: the agent tried to send an approved message through a supported channel, but delivery failed.
6. `discovery`: the customer has responded and the agent is collecting requirements.
7. `awaiting_terms_approval`: the agent drafted price, deadline, scope, or payment terms and is waiting for Daniil's approval.
8. `draft_ready`: the agent prepared `prompt.md` and the order workspace for manual execution.
9. `awaiting_delivery_approval`: a deliverable or customer message is ready but needs approval before sending.
10. `payment_requested`: the agent has identified that Daniil needs to accept or request payment.
11. `closed`: the order is finished, declined, or no longer actionable.

## Workflow

1. The monitor finds a suitable job from the allowed categories.
2. The agent creates `orders/<order_id>/` and updates `orders/index.json`.
3. The agent writes initial order files:
   - `state.json` for machine-readable state.
   - `brief.md` for the source job, category, risks, and initial assessment.
   - `conversation.md` for the message history.
   - `prompt.md` for manual Codex or ChatGPT execution.
   - `deliverables/` for produced work.
4. The agent sends Daniil a Telegram card with the source job and first outreach draft.
5. Daniil chooses `Approve outreach`, `Edit`, or `Reject`.
6. If a supported automated contact channel exists, the agent sends the approved outreach. Otherwise it switches the order to `manual_send_needed` and gives Daniil the exact text to send.
7. When the customer replies, the agent adds the reply to `conversation.md`, extracts requirements, and drafts follow-up questions or terms.
8. Price, deadline, guarantees, and payment terms always require Daniil's approval.
9. After terms are approved, the agent prepares or updates `prompt.md` and sends Daniil a short Telegram summary.
10. Daniil manually runs Codex or ChatGPT and places outputs into `deliverables/` or marks the draft as ready.
11. The agent drafts the customer-facing delivery message but does not send it without `Allow sending`.
12. When payment should be requested or accepted, the agent sends a dedicated Telegram notification and moves the order to `payment_requested`.

## Data Model

The first version uses repository-local files:

- `data/seen_posts.json`: existing list of processed vacancy post IDs.
- `orders/index.json`: list of orders with IDs, statuses, source URLs, categories, and timestamps.
- `orders/<order_id>/state.json`: full machine-readable order state.
- `orders/<order_id>/brief.md`: human-readable source job and assessment.
- `orders/<order_id>/conversation.md`: customer conversation log.
- `orders/<order_id>/prompt.md`: ready-to-run prompt for Codex or ChatGPT.
- `orders/<order_id>/deliverables/`: files produced during manual execution.

`state.json` should include:

- order ID;
- source type and source URL;
- original post ID;
- detected category;
- current status;
- contact channel and contact value when available;
- latest approved outreach text;
- approved price and deadline when set;
- risk flags;
- created and updated timestamps.

## Telegram Control

The existing Telegram bot becomes the approval surface. Agent messages to Daniil should use inline buttons for actions such as:

- `Approve outreach`;
- `Edit outreach`;
- `Reject`;
- `Sent manually`;
- `Approve terms`;
- `Request changes`;
- `Draft ready`;
- `Allow sending`;
- `Payment requested`;
- `Close order`.

All callbacks must validate the current order status before applying a transition. Invalid or stale callbacks should produce a Telegram notice and leave state unchanged.

## Customer Channels

The agent can act automatically only when there is a safe and explicit communication channel:

- Telegram contact that can be messaged through supported tooling.
- Email through configured IMAP/SMTP access.
- Official exchange API, if available.
- Manual mode for exchanges or links without supported API access.

Manual mode is a first-class path. A Telegram username or exchange profile link does not automatically mean the bot can send messages itself. If the project has no supported API or authenticated messaging integration, the agent still prepares the message and records the conversation, while Daniil performs the actual send and confirms it with `Sent manually`.

## Safety Rules

The agent must be conservative:

- First outreach is never sent without approval.
- Price, deadline, guarantees, and payment terms are never sent without approval.
- Customer-facing deliverables are never sent without approval.
- The agent declines or flags requests involving spam, fake engagement, phishing, malware, credential theft, platform restriction bypasses, or illegal collection of personal data.
- If a contact channel is unclear, the agent switches to manual mode.
- If JSON state cannot be written, the agent does not mark a vacancy as processed.
- If message sending fails, the agent keeps the order in `manual_send_needed` or `send_failed` and preserves the text for manual sending.

## Error Handling

State writes should be atomic enough to avoid corrupt JSON on interruption. If an order folder cannot be created, the agent sends Daniil an error notification and leaves the source post unprocessed so it can be retried.

If `orders/index.json` and `orders/<order_id>/state.json` disagree, the per-order `state.json` is the source of truth and the index can be rebuilt.

If the Telegram callback handler receives an unknown order ID, stale status, or unsupported action, it should respond in Telegram and make no state change.

## Testing

Tests should cover:

- Creating an order from a matched post.
- Creating the expected order folder structure.
- Updating `orders/index.json`.
- Valid lifecycle transitions.
- Rejection of invalid lifecycle transitions.
- Telegram callback parsing and status validation.
- Manual send flow.
- Rules that prevent first outreach, terms, and delivery from being sent without approval.
- Handling corrupt JSON.
- Retrying a post when order persistence fails.

## Implementation Strategy

Build this as an incremental local extension of the existing Python project:

1. Add order models and JSON store.
2. Add workspace creation.
3. Add Telegram approval messages and callback handling.
4. Connect matched posts from the monitor into order creation.
5. Add manual send and manual execution flows.
6. Add tests around state, callbacks, and safety gates.

The existing GitHub Actions monitor can remain available for passive notifications, but the semi-autonomous agent should be run locally because it needs active Telegram interaction and access to local order workspaces.
