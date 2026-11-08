# Sign in with ChatGPT: research notes

Read on **2026-11-08**, from OpenAI's public documentation only. No DevKit code and no code from
the owner's private extension was read or used. The protocol facts below are written in our own
words; the standards used are OAuth 2.0 (RFC 6749), PKCE (RFC 7636), OAuth 2.0 token revocation
(RFC 7009) and OpenID Connect Core 1.0.

Pages read (all under https://developers.openai.com/ unless noted):
`siwc`, `siwc/token-sharing-open-source` (+ `/sign-in`, `/models-and-inference`,
`/token-reference`, `/errors-and-recovery`, `/preview-limitations`, `/profiles-and-sessions`,
`/self-hosted-vms`), `siwc/ui-ux-guidelines`, `siwc/request-client-id`,
`cookbook/articles/sign-in-with-chatgpt`, the DevKit README at
https://github.com/openai/sign-in-with-chatgpt-devkit, and
https://auth.openai.com/.well-known/openid-configuration.

## 1. Can wow-coach use it? (access, gating, license)

- **Yes in principle.** The cookbook says plan usage "is available at launch to open-source
  projects, personal projects that run locally, and selected private apps". Eligible users are
  ChatGPT Plus or Pro subscribers. wow-coach is a free, MIT, local desktop tool.
- **No approval step for open-source apps is described.** Registration is dynamic (section 3):
  the user approves the app in the browser. No client secret and no partner key.
- **Gated:** identity-only sign-in "is offered to a select group of commercial partners"
  (`request-client-id`), and "paid or remotely hosted apps" must join a waitlist. Neither applies
  to us as long as wow-coach stays free and local.
- **Licenses.** The DevKit code AND its docs in the GitHub repo are under the "Sign-in with
  ChatGPT DevKit Noncommercial License v1.0": not usable in an MIT repo. We copy nothing from
  there. The pages on developers.openai.com state no license or reuse terms, and no separate
  program terms for open-source apps were found. The cookbook says to "review OpenAI's terms and
  policies before distributing an integration". **UNVERIFIED: the governing terms.** The owner
  should read OpenAI's Terms of Use and Service Terms once before 0.9.0 ships.
- **Preview status.** The page is called "Preview limitations". The feature may change.
- A "Manage usage" limit can be the plan's or an app-specific limit.

## 2. Endpoints

| What | URL |
|---|---|
| Discovery | `https://auth.openai.com/.well-known/openid-configuration` |
| Issuer | `https://auth.openai.com` |
| Authorize | `https://auth.openai.com/api/accounts/authorize` |
| Token (code exchange and refresh) | `https://auth.openai.com/api/accounts/oauth/token` |
| Revoke | `https://auth.openai.com/api/accounts/oauth/revoke` (the `revocation_endpoint` in discovery) |
| JWKS | `https://auth.openai.com/.well-known/jwks.json` |
| List models | `GET https://api.openai.com/v1/models` |
| Ask a model | `POST https://api.openai.com/v1/responses` |

Discovery says: only `S256` PKCE; grants `authorization_code` and `refresh_token`.
We use fixed endpoint constants rather than fetching discovery on every run (fewer moving
parts); a test pins them to the values above. Never call ChatGPT's `backend-api` (the docs say
so too).

## 3. Registration and sign-in

- First sign-in uses `client_id=dynamic_agent_client` plus `agent_name_hint` (our name:
  `wow-coach`) and `ext_agent_host_id`. The user names and approves the app in the browser.
  The callback then carries the **issued `client_id`** (looks like `oaiapp_...`). Save it
  (keychain) BEFORE exchanging the code; never use `dynamic_agent_client` for the token exchange.
- Later sign-ins use the issued `client_id`, omit `agent_name_hint`, and may send
  `id_token_hint` (skips the account picker) and `login_hint`.
- `ext_agent_host_id` is required: an opaque, stable, per-install value such as
  `urn:uuid:<random>`. Not a secret, not an identity. We generate it once and keep it in the
  keychain.
- **Redirect URI:** `http://127.0.0.1:<port>/auth/callback`. The initial registration example
  uses port 1455. Later sign-ins "may use another port; only the port may change" (scheme, host
  and path must match exactly). Never `localhost`. So the issued client id is **not** tied to the
  port, only to scheme, host and path. We default to 1455 and the port is injectable.
  UNVERIFIED: whether a first registration with a port other than 1455 is accepted.
- Authorize parameters: `response_type=code`, `client_id`, `redirect_uri`,
  `scope=openid profile email offline_access resource.invoke chatgpt.tokens.use.direct`,
  `resource=https://api.openai.com/v1`, `state`, `nonce`, `code_challenge`,
  `code_challenge_method=S256`, `ext_agent_host_id`, `agent_name_hint` (first time only).
- Callback parameters: `code`, `state`, `scope`, and `client_id` on first registration.
  `error=access_denied`: check `state`, stop, do not exchange. A callback with a different
  client id than expected is rejected.
- Token exchange (form POST): `grant_type=authorization_code`, `client_id`, `code`,
  `code_verifier`, `redirect_uri`, `resource`. No secret. On `invalid_grant` start over.
- Token response: `id_token`, `access_token`, `refresh_token`, `token_type=Bearer`,
  `expires_in`, `scope`, `earliest_refresh_at` (meaning UNVERIFIED; we ignore it).
- A valid ID token does NOT prove plan usage is allowed: check that the granted `scope`
  contains `chatgpt.tokens.use.direct`. If not, "plan use not enabled": tell the player and
  stop; to retry, repeat sign-in with the saved client id (`prompt=consent` is supported).
- ID token checks: `iss` = issuer, `aud` = the issued client id, `exp`, `nonce`. The docs also
  say to verify the signature against the JWKS. **Our deliberate deviation:** the ID token
  arrives straight from the token endpoint over TLS, and OIDC Core 3.1.3.7 (step 6) lets TLS
  server validation stand in for the signature check in that case. We check the claims and skip
  the JWKS. (Avoids a JWT/crypto dependency.) Noted in the code.

## 4. Tokens

- Access token: 3600 s (1 h), audience `https://api.openai.com/v1`. Memory only.
- Refresh token: 30 days, **rotates** on every refresh (the new one replaces the old).
  Refresh form POST: `grant_type=refresh_token`, `client_id` (issued), `refresh_token`,
  `resource`; omit `scope`. Serialize refreshes. Store the new refresh token at once.
- Refresh errors meaning "sign in again": `invalid_grant`, `invalid_refresh_token`,
  `token_expired`, `refresh_token_expired`, `refresh_token_invalidated`, `refresh_token_reused`.
  `invalid_client`: configuration problem. Do not erase credentials for network or 5xx errors.
- Sign-out: POST the revoke endpoint with `token`, `token_type_hint=refresh_token`, `client_id`.
  Empty 200 = success (also for an already-invalid token). Retry on network/5xx. If revoking
  could not be confirmed, say so and tell the player they can disconnect in ChatGPT Settings.
  Revoking does not delete the registered client.
- OpenAI does not tell us when the player disconnects in ChatGPT settings.

## 5. Calling the model

- `POST https://api.openai.com/v1/responses`, `Authorization: Bearer <access token>`,
  `Content-Type: application/json`.
- Body: `model` (a slug from the models list), `input` (array of `{role, content}`; all context
  every time), `store: false` (**must**), `stream: true` (**must**).
- System guidance goes in `instructions` (or developer messages). An `input` item with role
  `system` is **rejected**. So our `Message(role="system")` is joined into `instructions`.
- **Unsupported fields (rejected):** `background`, `conversation`, `max_output_tokens`,
  `max_tool_calls`, `metadata`, `moderation`, `multi_agent`, `prompt`, `prompt_cache_retention`,
  `safety_identifier`, `temperature`, `top_logprobs`, `top_p`, `truncation`, `user`, and
  `previous_response_id` over HTTP. Consequence: **`max_output_tokens` cannot be sent.** We
  keep the argument (the Provider contract has it) and cut the text locally once it is longer
  than the limit, then stop reading the stream.
- Streaming events: `response.output_text.delta` (`delta`), `response.completed` (success),
  `response.failed` (`response.error.code`), `response.incomplete`. A stream that ends without
  `response.completed` is a failure. Server-sent events (lines `event:` / `data:` + blank line).
- Models: `GET /v1/models` returns `{"models": [{"slug", "display_name", "visibility"}]}`; show
  entries with `visibility == "list"`, keep the server's order, reload after an account switch.
- **UNVERIFIED (docs silent):** JSON output. The standard Responses API option is
  `text: {format: {type: "json_schema", name, schema, strict}}`; we send that, and the coach
  engine must still validate the JSON. If the route rejects it we get
  `subscription_sharing_unsupported_capability` (400, `error.param`), which we report plainly.
- **UNVERIFIED:** the shape of usage numbers. The standard `response.completed` event has
  `response.usage.input_tokens` / `output_tokens`; we read those and fall back to 0.

## 6. Errors

Before a stream opens (body may be `{"detail": ...}`, diagnostic only): 401 identity or
permission not accepted (we refresh once, then `NotSignedIn`); 403 policy (e.g. region); 503
direct routing unavailable (back off, keep credentials).

Structured `error.code`:

| code | HTTP | Our reaction |
|---|---|---|
| `subscription_sharing_user_not_eligible` | 403 | `AIError`: plan not eligible; do not loop |
| `subscription_sharing_usage_limit_exceeded` | 429 | `PlanLimitReached` (no reset time is given; do not guess) |
| `subscription_sharing_usage_unavailable` | 503 | `AIError`: try later |
| `subscription_sharing_unsupported_capability` | 400 | `AIError`: names `error.param` |
| `subscription_sharing_route_not_supported` | 403 | `AIError` |
| `subscription_sharing_invalid_user` | 401 | treat like 401 |
| `chatpass_v2_scope_not_authorized`, `chatpass_v2_invalid_authorization_context` | 403 | `AIError`: sign in again |
| `subscription_sharing_user_unavailable` | 503 | `AIError`: try later |

Usage-limit errors can also arrive inside the stream as `response.failed`. No `Retry-After`
details are documented; if a `Retry-After` header is present we pass it on (UNVERIFIED).
No numeric rate limits are published; the plan's own usage limit applies.

## 7. Branding and wording (UI/UX guidelines)

- Sign-in button text: **Continue with ChatGPT** (with the approved logo; the official button
  assets are on a separate page, so text only for now. UNVERIFIED whether the logo may be used).
- First sign-in welcome: title "You're using your ChatGPT plan.", body "Eligible usage in this
  app uses your ChatGPT plan. Manage usage in your ChatGPT settings.", action "Got it".
- Show "Using ChatGPT plan" with a "Manage usage" link when a request uses the plan.
- Limit reached: "Usage limit reached" / "Review your plan or this app's limit in ChatGPT
  settings." with "Manage usage" linking to https://chatgpt.com/settings/usage.
- Distinguish plan usage from the app's own charges (we have none).
- These strings are for the 0.9.0 app window; the spike script uses the same wording.

## 8. Not covered by the docs (UNVERIFIED list)

1. Governing terms / license of the program for MIT projects.
2. Whether a port other than 1455 works for the first registration.
3. JSON output (`text.format`) on this route; the shape of usage numbers.
4. `Retry-After` on 429.
5. Meaning of `earliest_refresh_at`.
6. Exact models on a Plus vs Pro plan; `visibility` values besides `list`.
7. Logo/button asset reuse.
8. How the preview may change.

## 9. Hardening decisions after the security review (2026-11-08)

- A refresh reply's new refresh token is saved to the keychain before anything else is checked,
  because the old one is dead the moment OpenAI answers.
- Memory-only secrets happen ONLY when the computer has no keychain at all. A locked or broken
  keychain is an error ("unlock it"), never "no secrets", so wow-coach can't register twice.
- The loopback server serves each visitor in its own thread (an idle connection can't stall
  the sign-in), checks the `Host` header, compares `state` as bytes and is silent on errors.
  On Windows it binds with `SO_EXCLUSIVEADDRUSE`. On Linux and macOS it keeps `SO_REUSEADDR`
  (deviation from "off"): without it the port stays blocked for about a minute after a sign-in
  (TIME_WAIT), and on POSIX it does not let a second program listen on the same port.
  UNVERIFIED on a real Windows machine.
- Refreshes are serialized in the program (a lock) and between programs (an empty lock file
  in the data folder, stale after 30 seconds, always removed).
- A token set that we receive and then refuse (no plan permission, a bad ID-token claim) is
  revoked at once. A new sign-in revokes the old refresh token. A different account than the
  saved one is refused until the player signs out (or uses `forget_registration()`).
- Usage: every ATTEMPT is counted before sending; a cap of 0 means no calls.
