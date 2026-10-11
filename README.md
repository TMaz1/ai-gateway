project uses a virtual environment (.venv):
```
.\.venv\Scripts\Activate.ps1
```

formatting, from project root
```
python -m black .
```

run to import dependencies from pyproject.toml
```
python -m pip install -e ".[dev]"
```


run tests
```
python -m pytest
```

run project
```
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

access endpoints
```
http://127.0.0.1:8000/docs
```

Creating a key from the CLI
```
python -m app.cli create-key \
  --client-name "classification-client" \
  --capability classification

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