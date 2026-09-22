# Security

## Reporting

Please report vulnerabilities privately through GitHub: open the repository's Security tab and use "Report a vulnerability". Do not open a public issue for a security problem. You will get an answer within a week.

## What the agent does and does not do

- Model output never becomes a selector, a coordinate, a shell command or executable JavaScript. The model names an element number and the page resolves the real DOM node.
- The browser is a throwaway profile launched by dejevu, unless you attach your own Chrome with `--cdp-url`. If you attach your own, the agent acts with your logins. Only do that for goals you trust.
- Password, file and hidden inputs are never listed or read.
- Page text is sent to the model as data. A malicious page can try to instruct the model. The prompt says page text is data, not instructions, and the guards limit what an action can do, but no prompt is a security boundary. Do not point the agent at untrusted pages with a browser that holds your sessions.
- API keys are read from the environment or a `.env` file and sent only to the endpoint you configured.
