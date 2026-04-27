---
name: api-endpoint-development
description: Build new FastAPI endpoints with proper Swagger documentation, Pydantic schema examples, security integration, input validation, and per-model docs. Covers the full cycle from registry to deployment. Trigger on "new endpoint", "add endpoint", "api development", "build api", "create api endpoint".
user-invocable: true
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
  - Agent
---

# API Endpoint Development

End-to-end process for adding FastAPI endpoints with production-quality Swagger documentation, security, validation, and external docs.

## Scope

This skill covers:
- Endpoint implementation with FastAPI
- Pydantic request/response models with Swagger examples
- RBAC integration (static and dynamic per-resource)
- Input validation and security hardening
- OpenAPI schema quality (no generic placeholders)
- External documentation (partner-facing, zero internal leaks)
- Test coverage for functionality, security, and role enforcement

## 1. Pydantic Models — Swagger-First

Every request and response model must include `model_config` with `json_schema_extra.examples` so Swagger shows realistic data instead of generic placeholders.

### Problem: Generic Swagger Output

Without examples, Swagger renders:
```json
{"model_id": "string", "frames": ["string"], "data": {}}
```
And for `Dict[str, ...]`:
```json
{"additionalProp1": [...], "additionalProp2": [...]}
```

### Fix: Concrete Examples on Every Model

```python
class MyRequest(BaseModel):
    model_id: str = Field(description="...", max_length=64)
    frames: List[str] = Field(description="...", min_length=1, max_length=15)
    data: dict = Field(default_factory=dict, description="...")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "model_id": "intruder-plus-with-vehicle",
                    "frames": [
                        "/9j/4AAQSkZJRg...(base64 JPEG)",
                        "https://example.com/frame2.jpg",
                    ],
                    "data": {
                        "sensitivity": "medium",
                        "ignore_labels": [],
                        "stationary_filter": "false",
                    },
                }
            ]
        }
    }
```

### Rules

- **Every response model** gets an example. Especially `Dict[str, ...]` types — Swagger cannot infer meaningful keys.
- **Every request model** gets an example showing realistic values, not `"string"` or `0`.
- **List responses** (like GET /models) should show 2+ items to demonstrate the structure.
- **Nested schemas** (like `data_schema` inside a model info response) should include actual property definitions, not `{}`.
- Examples should use production-realistic values — real model IDs, plausible coordinates, actual parameter names.
- **Request and response examples must be consistent.** If the request uses `model_id: "intruder-plus-with-vehicle"` with 2 frames, the response must show the same model_id with detections matching that model's classes across 2 frame indices.

## 2. Schema-as-Contract Pattern

When one endpoint serves multiple resource types (e.g., unified detect for 7 models), use per-resource Pydantic schemas for validation:

```python
# Registry maps resource ID → schema
MODEL_REGISTRY = {
    "intruder": ModelRegistryEntry(data_schema=StandardModelData, ...),
    "weapon": ModelRegistryEntry(data_schema=StandardModelData, ...),
    "motion-plus": ModelRegistryEntry(data_schema=MotionPlusData, ...),
}

# Endpoint validates dynamically
entry = get_model(body.model_id)
validated_data = entry.data_schema.model_validate(body.data)
```

The discovery endpoint (`GET /models`) exposes each schema via `model_json_schema()` so clients can validate client-side or build dynamic UIs.

## 3. Security Integration Checklist

### RBAC

- [ ] Add role to `AcceptedRoles` enum in `check_api_key.py`
- [ ] Add `check_*_roles()` function and export from `__init__.py`
- [ ] Add endpoints to `ENDPOINT_ROLE_MAPPING` in `generator.py`
- [ ] Dynamic role check: `CheckRoles(entry.accepted_roles)(request)` — runs BEFORE data validation

### Processing Order

```
1. Resource lookup (404 if not found)
2. RBAC check (403 if denied) ← before validation
3. Input validation (422 if invalid)
4. Business logic
```

### Discovery/List Endpoints

- Filter results by caller's roles: `if not user_roles or has_role_access(user_roles, entry.accepted_roles)`
- `not user_roles` fallback ensures local dev sees everything
- 404 error hints must also be role-filtered — don't leak resource names

### Error Messages

- Generic messages only: "Invalid image data", not `str(e)` from internal exceptions
- No file paths, stack traces, infrastructure details, or role names
- 503 for misconfigured backends, not 500 with internal details

## 4. Input Validation Standards

Every user-controlled field needs bounds:

| Field Type | Constraints |
|-----------|------------|
| `str` | `max_length` |
| `List[...]` | `min_length`, `max_length` |
| `int` | `ge`, `le` |
| `float` | range check in code (`0 < x < 1.0`) |
| Enum-like `str` | `pattern` regex |
| `bool` coercion | `isinstance(x, (int, float)) and not isinstance(x, bool)` |
| Image/file bytes | PIL validation, dimension limit, size limit, format normalization |

Run CPU-bound validation (PIL) in `asyncio.to_thread()` to avoid blocking the event loop.

**Timeouts:** Make HTTP client timeouts configurable via env var (e.g., `INFERENCE_TIMEOUT_SECONDS`). Production needs tight timeouts (3s), local dev over remote connections needs more (10s). Set the dev default in `server.py` with `os.environ.setdefault()`.

## 5. External Documentation

Run `/write-external-docs` after implementation. Key rules:

- Zero internal details (no role names, infrastructure, library names, file paths)
- No redundant prose — if the table shows it, don't narrate it
- One-line intros only where they add context the structure doesn't convey
- `<!-- MODEL_TABLE -->` placeholders for role-filtered dynamic content
- Production URLs in examples (`api.actuateui.net`), not dev

## 6. Testing Checklist

### Functional
- [ ] Happy path: single input, multiple inputs, each resource variant
- [ ] Empty/default parameters use correct defaults
- [ ] Filters and post-processing applied correctly

### Validation
- [ ] Invalid base64 → 400
- [ ] Non-image base64 → 400
- [ ] Too many items → 422
- [ ] Oversized strings → 422
- [ ] Invalid enum values → 422
- [ ] Missing required fields → 422

### Role Enforcement
- [ ] Wrong role → 403 (use `patch.object(CheckRoles, "_extract_roles", return_value="role")`)
- [ ] Correct role → 200
- [ ] Discovery endpoint filtered by role
- [ ] 404 hints filtered by role

### Live Regression (all API versions)
- [ ] Regression suite page hits every endpoint across v1 through current
- [ ] Real images sent through kubefwd to model servers (not mocked)
- [ ] All legacy versions still return 200/204 (not just the new version)
- [ ] Results exportable as JSON for review

### Test Hygiene
- [ ] Every `patch.start()` has a `.stop()` in `tearDown`
- [ ] `app.dependency_overrides` reset in `tearDown`
- [ ] Shared constants extracted (e.g., `_TEST_ENV_VARS`)

## 7. Swagger Quality Verification

After implementation, check Swagger UI at `/docs`:

- [ ] Request body shows realistic example values, not `"string"` / `0` / `{}`
- [ ] Response body shows realistic example with correct key names (not `additionalProp`)
- [ ] List responses show 2+ items
- [ ] Nested objects (like JSON Schema inside a response) show real properties
- [ ] Error responses listed with status codes
- [ ] Endpoint descriptions are concise (no internal details)
- [ ] Request and response examples are consistent (same resource ID, matching input/output counts, detection classes from the specified model)

## Reference Implementation

- **Endpoints:** `inference_api/api/endpoints/v5.py`
- **Models:** `inference_api/models/v5.py` (request, response, detection, model info — all with examples)
- **Registry:** `inference_api/api/v5/registry.py` (per-model schemas, RBAC, thresholds)
- **Security:** `inference_api/api/security/check_api_key.py` (AcceptedRoles, CheckRoles, get_user_roles)
- **Docs:** `docs/api/v5/` (external partner docs, role-filtered wiki viewer)
- **Tests:** `inference_api/test/test_v5.py` (31 tests: functional, validation, role enforcement)
