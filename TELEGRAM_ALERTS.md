# Gifts Telegram alerts

The guest collector remains read-only and does not send messages.
telegram_alerts.py renders previews by default. No BUY buttons or external execution are implemented.

Run all safeguards:
```sh
python3 -m unittest -v test_guest_pipeline test_telegram_alerts
```

A live send requires this project's dedicated GIFTS_BOT_TOKEN and GIFTS_ALERT_CHAT_ID in environment variables.
Never commit credentials or reuse another project's bot. The Telegram user session/API hash is not a bot token.

Delivery is blocked unless an assessment is a VERIFIED_OPPORTUNITY, has no unresolved holds, has a valid opportunity score, verified costs and five comparable sales, and includes a fresh availability check at the same listing price.
The current guest pipeline produces rejected assessments or research candidates only. It cannot yet produce VERIFIED_OPPORTUNITY.
Availability verification and cost estimation still need implementation; this sender does not perform those checks itself.

SQLite records attempts per event and destination. Uncertain network outcomes are held for review and never automatically retried.
The ledger must persist across invocations to preserve deduplication. Keep it outside the repository when configuring live sends.

A preview from actual assessment data can be generated with:
```sh
python3 telegram_alerts.py assessment.json
```
Preview data is labelled as analysis, not a buy signal. No message is sent without --send.
