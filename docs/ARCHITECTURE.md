# AI Gateway Architecture

## Purpose

The AI Gateway is a policy enforcement boundary between consuming
applications and AI model providers.

It is deliberately **not** a generic AI proxy.

A future provider request will only occur after:

1. authentication
2. authorization
3. request validation
4. abuse/resource checks
5. model/provider policy evaluation
6. trusted prompt construction

A provider response will only reach the caller after:

1. provider response handling
2. normalization
3. output validation
4. enforcement of the public API contract

---

## Intended request flow

```text
Untrusted Client
       |
       | HTTPS
       | API key
       v
+-----------------------------+
|        AI Gateway           |
|-----------------------------|
| API-key authentication      |
| Capability authorization    |
| Request validation          |
| Abuse policy                |
| Resource limits             |
| Rate limiting               |
| Model/capability policy     |
| Prompt isolation            |
| Provider adapter            |
| Output validation           |
| Logging / audit             |
| Safe error handling         |
+--------------+--------------+
               |
               | Internal HTTP
               v
       Trusted Provider
               |
          +----+----+
          |         |
       Ollama    Cloud APIs
                  later
````

---

## Dependency direction

The application is structured around dependency inversion.

```text
HTTP/API layer
      |
      v
Application services
      |
      +----> Domain models/contracts
      |
      +----> Security abstractions
      |
      +----> Provider abstractions
      |
      v
Infrastructure implementations
      |
      +----> SQLite
      +----> Ollama
      +----> OpenAI
      +----> Anthropic
             future
```

The application layer must not become dependent on Ollama-specific behavior.

Provider-specific request/response formats belong inside provider adapters.

---

## Authentication boundary

The gateway does not implement human authentication.

It does not implement:

* registration
* login
* passwords
* password reset
* MFA
* email verification
* refresh tokens
* JWT issuance
* user sessions
* a user database

Instead, the gateway authenticates service/application callers using API keys.

An API key represents an authorized application or service.

The existing Authentication API remains responsible for human/user authentication.

A future JWT integration can be implemented through a separate authentication adapter if required.

That future integration should produce the gateway's common authenticated-principal representation rather than coupling every endpoint to JWT implementation details.

---

## API-key lifecycle

An API key contains:

```text
agw_<key-id>_<secret>
```

The key ID is an identifier and is not treated as secret.

The secret is generated with Python's cryptographically secure `secrets` module.

Only a cryptographic digest of the secret is stored.

The plaintext secret is returned only during creation.

Normal list/get operations do not return it.

Lifecycle states:

```text
ACTIVE
  |
  +----> INACTIVE
  |
  +----> REVOKED

INACTIVE
  |
  +----> ACTIVE
  |
  +----> REVOKED

REVOKED
  |
  +----> terminal
```

A revoked key cannot be reactivated.

---

## Capability authorization

Authentication and authorization are intentionally separate.

A caller possessing a valid API key is not automatically entitled to every future gateway operation.

Capabilities are associated with API keys.

Batch 1 defines:

```text
classification
```

Future endpoints can require additional explicit capabilities.

For example:

```text
classification
summarization
embedding
chat
```

A capability should only become usable when the corresponding endpoint and policy have been explicitly designed and implemented.

---

## Model/provider routing

Clients should not select arbitrary providers or models.

The desired public contract is:

```http
POST /ai/classify
```

rather than:

```http
POST /ollama/deepseek/classify
```

or:

```http
POST /ai/classify?provider=ollama&model=...
```

Internally the gateway will eventually maintain a trusted registry:

```text
logical capability
       |
       v
logical route
       |
       +----> provider
       |
       +----> model
       |
       +----> provider policy
```

For the initial deployment this will eventually resolve:

```text
classification
    |
    +----> Ollama
    |
    +----> deepseek-r1:1.5b
```

Changing the model should therefore normally require a gateway configuration/routing
change rather than a consuming-application change.

---

## Prompt isolation

Caller text is untrusted data.

The caller must never control:

* system instructions
* developer instructions
* classification rules
* provider URL
* model routing
* capability policy
* arbitrary provider options

The gateway constructs trusted instructions independently from caller input.

The eventual classification implementation must distinguish:

```text
TRUSTED GATEWAY INSTRUCTIONS
```

from:

```text
UNTRUSTED CUSTOMER MESSAGE
```

The model is not trusted to enforce this boundary.

---

## Provider isolation

Provider destinations are trusted configuration.

They must never be constructed from:

* query parameters
* request JSON
* request headers
* API-key metadata
* customer messages

The gateway must never become:

```text
POST /proxy?url=https://...
```

or any equivalent generic forwarding endpoint.

Provider HTTP clients should eventually use:

* bounded connection timeouts
* bounded response timeouts
* restricted redirects
* bounded response sizes
* cancellation propagation

---

## Output isolation

Provider output is untrusted.

The gateway will normalize provider responses into internal domain representations.

For classification:

```text
provider response
      |
      v
extract category
      |
      v
validate against allowlist
      |
      +---- billing
      +---- technical
      +---- cancellation
      +---- general
```

Only the validated public representation is returned.

Provider-specific fields such as model reasoning/thinking are not part of the public API.

---

## Persistence

SQLite is the v1 persistence implementation.

The database stores:

* API-key metadata
* API-key secret digests
* API-key lifecycle state
* capabilities
* expiration
* timestamps
* security-event metadata

The database does not store plaintext API-key secrets.

The database is never exposed through an HTTP endpoint.

The database path is configuration-driven.

SQLite is suitable for the initial local/small deployment.

A multi-instance production gateway will eventually need a shared database and
distributed rate-limit mechanism.

---

## Security events

Security events are distinct from ordinary request logs.

Examples include:

* API-key creation
* authentication failures
* authorization failures
* API-key revocation
* API-key deactivation
* rate-limit violations
* resource-policy violations
* suspicious prompt attempts

Security events must not contain:

* API-key secrets
* passwords
* JWTs
* provider credentials
* complete customer messages unless specifically justified

---

## Request IDs

Each HTTP request receives an `X-Request-ID`.

A valid caller-provided ID can be retained for distributed tracing.

Invalid or oversized IDs are replaced with a gateway-generated identifier.

The request ID will eventually be propagated through:

```text
client
  |
  v
gateway
  |
  v
provider
```

This allows operational tracing without exposing secrets.

---

## Failure philosophy

Security controls should fail closed wherever practical.

The gateway should never respond to uncertainty by silently granting access.

Examples:

```text
authorization state unavailable
        |
        v
      reject
```

```text
model policy invalid
        |
        v
   startup failure
```

```text
rate-limit state unavailable
        |
        v
      reject
```

The exact behavior will be refined as those controls are introduced.

````

---

## `docs/THREAT_MODEL.md`

```markdown
# Lightweight Threat Model

This document describes the initial security assumptions and controls.

The gateway does not make AI usage completely safe.

It establishes a policy enforcement boundary and reduces several classes of
accidental and deliberate misuse.

---

## Assets

Important assets include:

- gateway API-key secrets
- provider credentials
- provider URLs/configuration
- SQLite gateway state
- customer messages
- provider responses
- security/audit metadata
- gateway availability
- provider capacity

---

## Threats

| Threat | Impact | Mitigation | Residual risk |
|---|---|---|---|
| Stolen API key | Unauthorized AI consumption | High-entropy key generation, hashed storage, expiry, deactivation and revocation | An active stolen key remains usable until revoked/expired |
| Malicious API-key holder | Resource consumption or policy bypass attempts | Capability authorization, request validation, resource limits, rate limiting and policy checks | No gateway can eliminate all malicious behavior |
| Compromised client application | Uncontrolled or malformed AI workload | Per-key resource policies, concurrency limits and rate limiting | Compromised credentials remain a significant risk |
| Prompt injection | Manipulation of model behavior | Trusted prompt construction and strict output validation | Model behavior remains probabilistic |
| System-prompt extraction | Disclosure of gateway instructions | Prompt isolation and narrow output contract | Models may still react unpredictably to adversarial input |
| SSRF | Gateway connects to attacker-controlled destination | Provider destinations only from trusted configuration; no arbitrary proxy functionality | Operator misconfiguration can still create risk |
| Provider credential leakage | Compromise of external AI credentials | Provider credentials are never client-controlled and must not enter logs/errors | Host/runtime compromise is outside the gateway boundary |
| Sensitive-message leakage | Privacy/security incident | Customer messages are not persisted or logged by default | Application and infrastructure logging remain operational responsibilities |
| Provider-output manipulation | Unexpected or unsafe output | Provider adapters and output schemas | Provider output may still be incorrect |
| Resource exhaustion | Gateway/provider denial of service | Request size, workload, concurrency and rate controls | Workload estimation is necessarily imperfect |
| API-key brute force | Authentication resource consumption | High-entropy secrets and later rate limiting | Network-level traffic remains possible |
| Configuration error | Unsafe routing or security policy | Startup validation and explicit configuration | Operators can still configure unsafe values |
| Database compromise | Exposure of gateway metadata | Plaintext secrets are not stored | Compromised infrastructure may still permit offline analysis |
| Provider outage | Failed AI requests | Bounded provider timeouts and safe errors | v1 does not guarantee provider availability |
| Audit-data leakage | Disclosure of operational/security information | Minimized event metadata and no secret storage | Log/database retention remains an operational responsibility |

---

## Trust boundaries

The principal trust boundary is:

```text
UNTRUSTED CALLER
       |
       v
+------------------------+
|      AI Gateway        |
|------------------------|
| Authentication         |
| Authorization          |
| Validation             |
| Abuse controls         |
| Resource controls      |
| Prompt isolation       |
| Provider policy        |
| Output validation      |
+------------+-----------+
             |
             v
      TRUSTED PROVIDER
````

The provider is **not** considered a security boundary.

Provider responses remain untrusted data.

---

## Caller responsibilities

Consuming applications are responsible for:

* protecting gateway API keys
* storing keys in environment variables or a secrets manager
* human/user authentication
* user-level authorization
* validating AI results in business-specific contexts
* deciding whether AI output is suitable for business decisions
* protecting sensitive customer data before transmission where necessary

---

## Gateway responsibilities

The gateway is responsible for:

* authenticating service callers
* enforcing gateway capabilities
* controlling provider/model routing
* validating requests
* enforcing workload limits
* limiting concurrency
* rate limiting
* constructing trusted prompts
* preventing arbitrary provider access
* validating provider output
* preventing provider-specific data leakage
* safe error handling
* security-event auditing
* privacy-conscious logging

---

## Residual risk

The gateway cannot guarantee:

* factual model output
* complete prompt-injection resistance
* provider availability
* protection against a compromised gateway host
* protection against a stolen active API key before revocation
* correctness of consuming application's business decisions
* complete detection of semantic abuse

The gateway should therefore be treated as one security control within a larger
application architecture, not as a guarantee of AI safety.

````

---

# `README.md`

```markdown
# AI Gateway

A reusable, text-focused AI Gateway that acts as a **policy enforcement point**
between consuming applications and AI model providers.

The gateway is intentionally not a generic AI proxy.

Its purpose is to provide a controlled abstraction and security boundary around
AI capabilities.

---

## Core idea

The intended architecture is:

```text
Consuming Application
        |
        | HTTPS
        | Service API key
        v
+-----------------------------+
|        AI Gateway           |
|-----------------------------|
| Authentication              |
| Authorization               |
| Abuse/resource controls     |
| Validation                  |
| Rate limiting               |
| Model routing               |
| Prompt isolation            |
| Provider adapters           |
| Output validation            |
| Logging / auditing          |
| Error handling              |
+--------------+--------------+
               |
               | Internal HTTP
               v
        AI Provider
               |
          Ollama / APIs
````

The consuming application must not need to know:

* that Ollama exists
* where Ollama is running
* which model is used internally
* how Ollama's HTTP API works
* how OpenAI's API works
* how Claude's API works
* provider credentials
* internal provider URLs
* provider-specific response formats

Those concerns belong to the gateway.

---

# Authentication boundary

**This gateway does not implement human/user authentication.**

It does not implement:

* user registration
* passwords
* login
* email verification
* MFA
* password reset
* JWT issuance
* refresh tokens
* user sessions
* administrative user management
* a user database

It provides **service-to-service API-key authentication**.

An API key represents an authorized calling application/service.

Human authentication remains the responsibility of the consuming application or
the existing Authentication API.

A future integration with the existing Authentication API could add JWT
authentication through a separate authentication adapter, but JWT/user
authentication is not required for v1.

This separation is intentional.

---

# Batch 1

Batch 1 provides the project foundation:

* FastAPI application
* configuration management
* startup configuration validation
* SQLite persistence
* API-key generation
* cryptographically secure API-key secrets
* hashed API-key storage
* API-key identification
* API-key activation/deactivation
* API-key revocation
* optional expiration
* capability metadata
* security-event persistence
* request/correlation IDs
* safe health endpoints
* API-key administration CLI
* automated foundation tests
* architecture documentation
* threat model

The AI provider and `/ai/classify` path are introduced in later batches.

---

# Technology

Current stack:

* Python 3.11+
* FastAPI
* Pydantic
* Pydantic Settings
* SQLite
* pytest
* Uvicorn

Provider communication will use `httpx` when the provider layer is introduced.

No Redis, PostgreSQL, Docker, Kubernetes, message queue, or cloud dependency is
required for the initial local implementation.

---

# Project structure

```text
ai-gateway/
├── app/
│   ├── api/
│   ├── application/
│   ├── configuration/
│   ├── domain/
│   ├── infrastructure/
│   │   └── persistence/
│   ├── middleware/
│   ├── security/
│   ├── cli.py
│   ├── errors.py
│   ├── logging_config.py
│   └── main.py
├── data/
├── docs/
├── tests/
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

The structure intentionally separates:

* HTTP concerns
* application services
* domain objects
* security infrastructure
* persistence
* configuration
* middleware

---

# Local setup

Python 3.11 or newer is required.

On Windows PowerShell:

```powershell
py -3.11 -m venv .venv
```

Activate it:

```powershell
.venv\Scripts\Activate.ps1
```

Upgrade pip:

```powershell
python -m pip install --upgrade pip
```

Install the application and development dependencies:

```powershell
python -m pip install -e ".[dev]"
```

---

# Configuration

Copy:

```text
.env.example
```

to:

```text
.env
```

Do not commit `.env`.

Generate a development API-key pepper with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put the generated value in:

```dotenv
GATEWAY_API_KEY_PEPPER=...
```

Production environments must not use:

```text
development-only-change-me
```

---

# Running the gateway

Start the development server:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Health:

```text
GET /health
```

Readiness:

```text
GET /health/ready
```

Interactive API documentation is available in non-production environments at:

```text
/docs
```

and:

```text
/redoc
```

---

# API keys

API keys are for service-to-service authentication.

They are not user credentials.

A generated key has this structure:

```text
agw_<key-id>_<secret>
```

The key ID is non-secret.

The secret has high entropy and is generated using Python's cryptographically
secure `secrets` module.

Only a cryptographic digest of the secret is persisted.

The complete plaintext key is displayed only when it is created.

Normal listing and retrieval operations do not return the secret.

---

## Create an API key

For example:

```powershell
python -m app.cli create-key --client-name "classification-client" --capability classification
```

The command displays something similar to:

```text
Key ID: ...
Client: classification-client
Capabilities: classification
Expires: never

API key (displayed once):
agw_...
```

Store that key securely.

Recommended locations for consuming applications include:

* environment variables
* OS secret stores
* cloud secret managers
* deployment secret managers

Do not commit API keys to source control.

---

## Expiring key

Create a key that expires after 30 days:

```powershell
python -m app.cli create-key --client-name "temporary-client" --capability classification --expires-in-days 30
```

---

## List key metadata

```powershell
python -m app.cli list-keys
```

The plaintext secret is never included.

---

## Deactivate

```powershell
python -m app.cli deactivate-key --key-id <key-id>
```

A deactivated key cannot authenticate.

It can later be activated.

---

## Activate

```powershell
python -m app.cli activate-key --key-id <key-id>
```

A revoked key cannot be reactivated.

---

## Revoke

```powershell
python -m app.cli revoke-key --key-id <key-id>
```

Revocation is terminal.

A revoked key cannot be activated again.

---

# API-key security model

The gateway never needs to retrieve the original secret from SQLite.

The incoming key is parsed into:

```text
key ID
secret
```

The key ID identifies the database record.

The secret is transformed into a digest using the configured application pepper.

That digest is compared against the stored digest using a constant-time comparison.

Conceptually:

```text
Incoming API key
      |
      v
Parse key ID + secret
      |
      v
Lookup key ID
      |
      v
Check status
      |
      v
Check expiration
      |
      v
Digest secret
      |
      v
Constant-time comparison
      |
      v
Authenticated service
```

Invalid, inactive, revoked and expired keys are not differentiated through the
authentication primitive.

---

# SQLite

SQLite is the v1 persistence layer.

The database currently stores:

* API-key metadata
* API-key secret digests
* API-key status
* client/application name
* capabilities
* creation timestamp
* last-used timestamp
* optional expiration
* security-event metadata

It does not store plaintext API-key secrets.

The SQLite database is stored according to:

```dotenv
GATEWAY_DATABASE_PATH=./data/gateway.db
```

The database is not exposed through an HTTP endpoint.

Queries use parameterized SQL.

Clients cannot supply:

* SQL
* table names
* database paths
* arbitrary filters
* arbitrary database operations

---

# SQLite limitations

SQLite is appropriate for:

* local development
* a single gateway instance
* small deployments
* the initial v1 implementation

A multi-instance production gateway will eventually need shared persistence and
distributed rate limiting.

The architecture keeps persistence behind repositories so that a future database
migration does not require rewriting the application/API layer.

---

# Request IDs

Every request receives:

```text
X-Request-ID
```

If a caller provides a valid bounded ID, it can be retained.

Malformed or excessively long IDs are replaced.

This establishes the foundation for future tracing:

```text
client request
      |
      v
gateway request
      |
      v
provider request
```

The request ID is not a security credential.

---

# Privacy

Customer messages may contain sensitive information.

The gateway therefore follows data minimization.

By default:

* customer messages are not persisted
* provider responses are not persisted
* customer messages are not logged
* API-key secrets are not logged
* provider credentials are not logged
* JWTs are not logged
* passwords are not logged

Security/audit events are designed to contain investigation metadata without
requiring complete customer content.

---

# AI provider abstraction

The gateway will use a provider abstraction rather than embedding provider
logic into API controllers.

The intended architecture is:

```text
AI capability
      |
      v
Application service
      |
      v
IAIProvider
      |
      +---- OllamaProvider
      |
      +---- OpenAIProvider
      |
      +---- AnthropicProvider
      |
      +---- future providers
```

The consuming application should not care which provider implementation is used.

---

# Ollama

The current target environment contains:

```text
Ollama 0.34.0
```

and:

```text
deepseek-r1:1.5b
```

The gateway will communicate with Ollama through its HTTP API.

It will not invoke the Ollama CLI through subprocesses during normal request
processing.

The provider URL is configuration-owned:

```dotenv
GATEWAY_OLLAMA_BASE_URL=http://127.0.0.1:11434
```

The client will never be permitted to replace this value.

Provider integration is introduced in a later batch.

---

# `/ai/classify`

The first AI endpoint will be:

```text
POST /ai/classify
```

The intended request is:

```json
{
  "message": "My boiler has stopped working."
}
```

The intended normalized response is:

```json
{
  "category": "technical"
}
```

Allowed categories:

```text
billing
technical
cancellation
general
```

The gateway will own the classification instructions.

The caller will only provide data to classify.

The caller will not be able to supply:

* system prompts
* developer prompts
* model instructions
* provider URLs
* provider credentials
* arbitrary provider options
* arbitrary model parameters
* alternate output schemas

Provider responses will be treated as untrusted and normalized before reaching
the caller.

DeepSeek reasoning/thinking output will never be exposed through the public
classification response.

---

# Security philosophy

The gateway is an abuse-resistance boundary.

Every caller is treated as untrusted.

The gateway is designed to prevent clients from:

* accessing arbitrary provider URLs
* selecting arbitrary providers
* selecting arbitrary models
* modifying gateway prompts
* changing gateway policy
* bypassing capability authorization
* generating unlimited concurrent workloads
* causing unbounded provider processing
* obtaining provider credentials
* obtaining internal reasoning
* using the gateway as a generic HTTP proxy

The gateway does not rely solely on a model's natural-language instructions to
enforce these controls.

---

# Model switching

A consuming application should call:

```text
POST /ai/classify
```

rather than naming the internal model.

The desired internal routing is:

```text
classification
      |
      v
logical route
      |
      +---- Ollama
      |
      +---- deepseek-r1:1.5b
```

If the gateway later changes that route to another approved provider/model, the
consuming application should not need to change.

The exact configuration mechanism is introduced with the model/provider registry
in a later batch.

---

# Adding providers

The provider abstraction is designed for implementations such as:

```text
OllamaProvider
OpenAIProvider
AnthropicProvider
AzureOpenAIProvider
OtherLocalProvider
```

A provider implementation will own:

* provider-specific HTTP communication
* request translation
* response translation
* provider-specific error handling
* provider-specific response semantics

Application services must not contain provider-specific HTTP logic.

---

# Rate limiting

Rate limiting is intentionally introduced after the foundation.

The configuration contract already provides:

```dotenv
GATEWAY_RATE_LIMIT_REQUESTS=30
GATEWAY_RATE_LIMIT_WINDOW_SECONDS=60
```

The eventual rate-limiting service will be abstracted so that the in-process
implementation can later be replaced with distributed storage such as Redis
without rewriting gateway controllers.

Rate limiting is not considered sufficient by itself.

The gateway will also implement:

* request-size limits
* input limits
* estimated workload limits
* output limits
* global concurrency limits
* per-key concurrency limits
* bounded provider processing

---

# Threat model

See:

```text
docs/THREAT_MODEL.md
```

The architecture documentation is in:

```text
docs/ARCHITECTURE.md
```

---

# Testing

Install development dependencies:

```powershell
python -m pip install -e ".[dev]"
```

Run:

```powershell
pytest
```

Batch 1 tests cover:

* API-key generation
* API-key parsing
* cryptographic verification
* wrong secrets
* pepper separation
* expiration
* inactive keys
* revoked keys
* SQLite persistence
* API-key lifecycle
* plaintext-secret non-disclosure
* configuration validation
* health endpoints
* readiness
* request IDs

The tests do not require Ollama.

Provider mocking is introduced when the provider layer is implemented.

---

# Security non-goals

This project is not:

* a general-purpose AI chatbot
* a generic HTTP proxy
* an arbitrary Ollama proxy
* an unrestricted OpenAI proxy
* an unrestricted Claude proxy
* a prompt playground
* a tool-execution framework
* a code-execution environment
* a web-browsing proxy
* a credential storage system
* a replacement for user authentication
* a guarantee of factual AI output
* a guarantee that malicious users cannot attempt abuse

Future capabilities that materially expand the attack surface must receive their
own authentication, authorization, validation, resource, provider-isolation,
output-validation, testing and documentation design.

---

# Planned implementation batches

## Batch 1

Foundation:

* configuration
* SQLite
* API-key infrastructure
* capabilities
* request IDs
* health endpoints
* tests
* architecture documentation
* threat model

## Batch 2

Gateway security boundary:

* API-key HTTP authentication
* authenticated principal
* capability authorization
* centralized error handling
* security headers
* consistent authentication/authorization errors

## Batch 3

Policy/resource controls:

* policy abstraction
* request body limits
* message limits
* estimated token limits
* global concurrency
* per-key concurrency
* abuse-policy extension point

## Batch 4

Rate limiting:

* in-process rate limiter
* per-key limits
* global limits where appropriate
* burst controls
* `429` responses
* rate-limit headers
* distributed-rate-limit abstraction

## Batch 5

Provider layer:

* provider interface
* normalized provider request/response contracts
* model registry
* trusted provider configuration
* Ollama adapter
* SSRF/redirect hardening
* provider error abstraction

## Batch 6

Classification:

* prompt/template service
* `/ai/classify`
* strict input schema
* trusted instruction isolation
* DeepSeek/Ollama integration
* classification allowlist
* normalized output
* reasoning/thinking suppression

## Batch 7

Provider resilience:

* timeout handling
* cancellation propagation
* response-size limits
* bounded processing
* explicit retry policy, initially likely no automatic retry
* provider failure normalization

## Batch 8

Security regression suite:

* prompt injection
* prompt extraction
* arbitrary provider URL attempts
* model/provider override attempts
* oversized requests
* oversized provider responses
* concurrency floods
* invalid-key flooding
* revoked/expired keys
* unauthorized capabilities
* malformed provider output
* provider hangs
* provider redirects
* reasoning extraction attempts

Tests will verify that requests rejected at the gateway boundary do not invoke
the provider.

## Batch 9

Operations:

* structured request logging
* security-event auditing
* privacy controls
* readiness/dependency checks
* operational observability

## Batch 10

Production hardening:

* complete documentation
* final threat model
* deployment guidance
* production configuration review
* limitations
* provider extension guidance
* security review checklist

````

---

## Batch 1 completion state

At the end of this batch, the project has a real executable FastAPI application and a persistent API-key subsystem, but **no endpoint yet invokes an AI provider**. That is deliberate: the provider must not be introduced before the gateway's foundational security and policy boundaries exist.

The next batch should therefore build directly on these modules rather than restructuring them:

```text
Batch 1
   |
   +-- Settings
   +-- Database
   +-- ApiKeyManager
   +-- ApiKeyService
   +-- Capability
   +-- Request ID
   |
   v
Batch 2
   |
   +-- HTTP authentication
   +-- AuthenticatedPrincipal
   +-- Capability authorization
   +-- centralized gateway errors
   |
   v
Batch 3+
   |
   +-- policy
   +-- resource controls
   +-- rate limiting
   +-- provider abstraction
   +-- Ollama
   +-- /ai/classify
````

When you say **“Proceed with Batch 2”**, I’ll continue from this exact architecture and codebase.