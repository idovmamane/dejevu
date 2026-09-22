# Changelog

## 0.1.0, 2026-09-22

First release.

- Hold out tasks (Selenium test form, Python docs, Wikipedia inventor question) added after tuning: 18 of 18 runs verified across llama-3.3-70b, gpt-oss-120b and gemini-2.5-flash. Traces in `bench/holdout`.

- One model call per step returns the operation, the element and the text together. Any OpenAI compatible endpoint. Optional TypeSafe Jev backend for head to head runs.
- Settle detection after every action: DOM quiet, requests started by the action finished, closing modal transitions ended. No fixed waits.
- Page reader across open shadow roots and same origin frames. Just off screen elements listed and scrolled into view when chosen.
- Guards on every decision: identity, role, name, state and nearby text must be unchanged before input. Hit testing for overlays. DONE only on a settled page.
- Rejected, unreadable and stale answers are explained back to the model. Loop breakers and budgets.
- Reference tasks with independent checks: Google Flights and Wikipedia. Measurement harness, results table, screencast recording and GIF rendering.
- Measured: Google Flights verified in 5.63 s median with llama-3.3-70b on Groq, 10 model calls, 15k tokens. jev-ultrafast publishes 7.09 s, 17 calls, 85k tokens.
