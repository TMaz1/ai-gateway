# AI Gateway 

> → "how should applications control access to AI providers?"

A production-minded AI Gateway API that provides a secure policy-enforcement layer between client applications and multiple AI providers. The gateway abstracts provider-specific implementation while controlling authentication, model access, resource usage, and AI request handling.

## How this work?

```
Client Application
       |
       | HTTPS / API key
       v
+---------------------------+
|        AI Gateway         |
|---------------------------|
| Authentication            |
| Authorization             |
| Validation                |
| Rate / Resource Limits    |
| Model Routing             |
| Provider Adapter          |
| Prompt Isolation          |
| Output Validation         |
+-------------+-------------+
              |
              v
        AI Provider
              |
OpenAI / Ollama / Anthropic / etc.
```

---
### Instructions

**Project uses a virtual environment (.venv)**
```
.\.venv\Scripts\Activate.ps1
```
exit (.venv)
```
deactivate
```

**Formatting, from project root**
```
python -m black .
```

**Run to import dependencies from `pyproject.toml`**
```
python -m pip install -e ".[dev]"
```

**Run tests**
```
python -m pytest
```

**Or, combine all**
```
python -m pip install -e ".[dev]"
python -m compileall -q app tests
python -m pytest -q
```

**Creating an API key from the CLI**
```
python -m app.cli create-key `
  --client-name "checkout-service" `
  --capability "support_intent"
```

**Run project**
```
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Download AI model**
```
ollama pull qwen2.5:1.5b
```
> [Qwen2.5-1.5B](https://pmc.ncbi.nlm.nih.gov/articles/PMC12706044/) is a compact, open-weight large language model 

**Optional: Access endpoints in browser (Swagger UI)**
```
http://127.0.0.1:8000/docs
```

**Open seperate terminal and run**
```
$apiKey = "[API_KEY]"

$headers = @{
    Authorization = "Bearer $apiKey"
}

$body = @{
    capability = "support_intent"
    message = "I cant seem to log into my account. Im confused?"
} | ConvertTo-Json

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/ai/classify" `
    -Method Post `
    -Headers $headers `
    -ContentType "application/json" `
    -Body $body
```

**The possible classification results from different customer messages**
```
payment_failure
duplicate_charge_concern
refund_request
order_status
checkout_technical_issue
account_issue
other
```

## Current Features

* **API-key handling**: generated IDs no longer contain the delimiter used by the key format. Parsing is bounded and continues to accept unambiguous legacy IDs.
* **Authentication and authorization**: reusable Bearer-token authentication and capability checks; invalid, inactive, revoked, expired, and unknown keys receive the same authentication failure.
* **Rate limiting**: bounded, thread-safe fixed-window limits with 429 responses and Retry-After.
* **Concurrency control**: global and per-key limits, with leases released after endpoint execution—including cancellation.
* **Request limits**: request bodies are bounded before routing; JSON-writing methods reject unsupported media types.
* **Safe errors**: consistent JSON error responses without exception details, database paths, or stack traces.
* **Security auditing**: API-key lifecycle events and security denials are recorded without storing plaintext API-key secrets.
* **Startup lifecycle**: database initialization now happens at application startup rather than during module import.
* **Request IDs**: rewritten as pure ASGI middleware so IDs are reliably attached to ordinary and early rejection responses.
* **Configuration validation**: provider URLs reject embedded credentials, untrusted hosts, invalid URL components, and non-HTTPS production URLs where HTTPS is required.

## Files

* **ollama.py** — checks the URL, model request, and HTTP timeout.
* **provider.py** — shows how the gateway selects and invokes its AI provider.
* **settings.py** — shows which provider, model, and endpoint the application expects.
* **classification.py** — reveals where provider_unavailable is raised or caught.

* **`ClassificationService`** is the part of the gateway that safely runs a classification request. Here's the flow:
       1. **Receive request**: Capability ID and customer message
       2. **Find the capability**: Reject unknown capabilities before calling the model
       3. **Validate the input**: Check the message and enforce character/token limits
       4. **Call the AI provider**: Generate a classification response
       5. **Parse and validate the output**: Require JSON with exactly one allowed category
       6. **Return the result**: For example, {"capability": "support_intent", "category": "refund_request"}



---

## Future Plan 

Add MCP:

Your application
      ↓
   AI Gateway
      ↓
 ┌───────────────┐
 │ Authentication│
 │ Authorisation │
 │ Rate limiting │
 │ Resource caps │
 │ Provider      │
 │ selection     │
 │ Validation    │
 │ Logging       │
 └───────────────┘
      ↓
OpenAI / Ollama / Anthropic / etc.


---

Whereas MCP is more like:

AI application / agent
        ↓
       MCP
        ↓
 ┌─────────────┐
 │ MCP Server  │
 ├─────────────┤
 │ Tools       │
 │ Resources   │
 │ Prompts     │
 └─────────────┘
        ↓
Your systems / databases / APIs


---

                    ┌──────────────┐
                    │ AI Agent     │
                    └──────┬───────┘
                           │
                          MCP
                           │
                    ┌──────▼───────┐
                    │ AI Gateway   │
                    │              │
                    │ Auth         │
                    │ Authorisation│
                    │ Rate limits  │
                    │ Quotas       │
                    │ Validation   │
                    │ Audit logs   │
                    │ Provider     │
                    │ routing      │
                    └──────┬───────┘
                           │
             ┌─────────────┼─────────────┐
             ▼             ▼             ▼
          Ollama        Provider B    Provider C

That gives you a much better project story:
AI Gateway — exploring authentication, authorisation, rate limiting, provider routing and resource governance for applications consuming AI services.
Then later: MCP integration — exploring how standardised agent/tool protocols interact with an AI governance layer.

