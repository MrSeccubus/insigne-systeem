# Insigne Systeem — API Specification

## Overview

The API allows a scout to maintain their progress through the badge system of Scouting Nederland.
It consists of three areas:

- **Users** — account registration and management.
- **Badges** — a catalogue of badges, each with 3 levels and 5 *steps* (requirements) per level.
- **Progress** — a scout's log of completed steps, which can be signed off by registered mentors.

## Architecture: hybrid JSON + HTML

The server exposes two parallel layers:

| Layer | Prefix | Returns | Consumer |
|-------|--------|---------|----------|
| JSON API | `/api/` | `application/json` | Future integrations, mobile apps |
| HTML | `/` | `text/html` | HTMX frontend |

All JSON endpoints described in the **Resources** section are mounted under `/api/` (e.g. `GET /api/badges`).

The HTML layer serves full pages on initial load and HTML fragments for HTMX partial updates. HTMX requests are identified by the `HX-Request: true` header — the server returns only the relevant fragment rather than the full page.

## Base URL

```
http://localhost:8000
```

## Authentication

- Registered users authenticate with their email address and password and receive a JWT.
- The JWT is renewed on every API call. Session timeout is 30 days of inactivity.
- Protected endpoints require the header: `Authorization: Bearer <token>`
- Sign-off requires a registered account. If the mentor is not yet registered, they receive an invitation email and can sign off after completing registration.

---

## Resources

---

### Users

Registration is a three-step process. The forgot-password flow reuses steps 2 and 3.

```
Step 1: POST /users              — provide email, receive confirmation email
Step 2: POST /users/confirm      — submit code from email, receive setup token
Step 3: POST /users/activate     — submit setup token + password
```

---

#### `POST /users` — Step 1: Request account (registration)

Accepts an email address and sends a confirmation email containing a secret code.
Public endpoint (no token required).

**Request body:**

```json
{
  "email": "jan@example.com"
}
```

**Response `202`:** Request accepted. Confirmation email sent.

> Always returns `202` even if the email is already registered, to avoid user enumeration.

---

#### `POST /users/confirm` — Step 2: Confirm email

Validates the secret code from the confirmation email.
Returns a short-lived setup token (valid 1 hour) used in step 3.

**Request body:**

```json
{
  "code": "a3f8b1..."
}
```

**Response `200`:**

```json
{
  "setup_token": "eyJ..."
}
```

**Response `400`:** Code is invalid or expired.

---

#### `POST /users/activate` — Step 3: Set password

Completes registration. The setup token from step 2 authorises this call.
Returns a JWT so the user is immediately logged in.

`name` is optional — defaults to the part of the email address before the `@` sign.

**Request body:**

```json
{
  "setup_token": "eyJ...",
  "password": "s3cr3t",
  "name": "Jan"
}
```

**Response `200`:**

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_at": "2026-05-18T10:00:00Z"
}
```

**Response `400`:** Setup token is invalid or expired.

---

#### `POST /auth/token` — Login

Authenticates a user and returns a JWT.

**Request body:**

```json
{
  "email": "jan@example.com",
  "password": "s3cr3t"
}
```

**Response `200`:**

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_at": "2026-05-18T10:00:00Z"
}
```

**Response `401`:** Invalid credentials.

---

#### `POST /auth/forgot-password` — Request password reset

Sends a reset email to the address if it belongs to an active account.
Reuses steps 2 and 3 of the registration flow.

**Request body:**

```json
{
  "email": "jan@example.com"
}
```

**Response `202`:** Always returned, even if the email is not found.

> After this call the user follows the same steps 2 and 3:
> `POST /users/confirm` to exchange the code for a setup token, then
> `POST /users/activate` to set the new password.

---

#### `GET /users/me` — Get own profile 🔒

**Response `200`:**

```json
{
  "id": "a1b2c3d4-...",
  "email": "jan@example.com",
  "name": "Jan",
  "created_at": "2026-04-18T10:00:00Z"
}
```

---

#### `PUT /users/me` — Update own profile 🔒

All relationships (progress, sign-offs) are stored against `user_id`, so changing email is safe and has no side effects.

**Request body** (all fields optional):

```json
{
  "name": "Jan de Vries",
  "email": "new@example.com",
  "password": "newpassword"
}
```

**Response `200`:**

```json
{
  "id": "a1b2c3d4-...",
  "email": "jan@example.com",
  "name": "Jan de Vries",
  "created_at": "2026-04-18T10:00:00Z"
}
```

---

#### `DELETE /users/me` — Delete own account 🔒

**Response `204`:** No content.

---

### Badges

Badge data is read from YAML files on disk — there is no database table for badges.
- `api/data/badges.yml` — index of all badges, grouped by category
- `api/data/badges/<slug>.yml` — full detail for one badge
- `api/data/images/<slug>.{1,2,3}.png` — badge images, served as static files under `/images/`

All badge endpoints require authentication (🔒).

---

#### `GET /badges` — List all badges

Returns an object with two keys: `gewoon` and `buitengewoon`, each containing an ordered list of badges in the order defined in `badges.yml`. No query parameters.

**Response `200`:**

```json
{
  "gewoon": [
    {
      "slug": "klantklossen",
      "title": "Insigne Klantklossen",
      "category": "gewoon",
      "images": [
        "/images/klantklossen.1.png",
        "/images/klantklossen.2.png",
        "/images/klantklossen.3.png"
      ]
    }
  ],
  "buitengewoon": [
    {
      "slug": "cybersecurity",
      "title": "Insigne Cybersecurity",
      "category": "buitengewoon",
      "images": [
        "/images/cybersecurity.1.png",
        "/images/cybersecurity.2.png",
        "/images/cybersecurity.3.png"
      ]
    }
  ]
}
```

---

#### `GET /badges/{slug}` — Get badge detail

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `slug` | string | Badge slug (e.g. `cybersecurity`) |

**Response `200`:**

```json
{
  "slug": "cybersecurity",
  "title": "Insigne Cybersecurity",
  "category": "buitengewoon",
  "images": [
    "/images/cybersecurity.1.png",
    "/images/cybersecurity.2.png",
    "/images/cybersecurity.3.png"
  ],
  "introduction": "Het insigne Cyber Security is...",
  "step_groups": [
    {
      "name": "Ontdek de digitale wereld",
      "steps": [
        { "index": 0, "text": "Een digitale wereld vol kansen! ..." },
        { "index": 1, "text": "Laat je niet Phishen. ..." },
        { "index": 2, "text": "Ontdek het digitale domein ..." }
      ]
    }
  ],
  "afterword": "Toelichting Insigne Cyber Security ..."
}
```

**Response `404`:** Badge not found.

---

### Progress

All progress endpoints require authentication (🔒).

A *progress entry* records that a scout has completed a specific step and is awaiting or has received sign-off.

---

#### `GET /progress` — List own progress 🔒

Returns all progress entries for the authenticated scout.

**Query parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `badge_slug` | string | No | Filter by badge |
| `status` | string | No | Filter by status: `open`, `pending_signoff`, `completed` |

**Response `200`:**

```json
[
  {
    "id": "p1p2p3p4-...",
    "badge_slug": "cybersecurity",
    "level_index": 0,
    "step_index": 0,
    "notes": "Gemaakt tijdens zomerkamp.",
    "status": "completed",
    "pending_mentors": [],
    "signed_off_by": { "user_id": "m1m2m3m4-...", "name": "Leider Piet" },
    "signed_off_at": "2026-04-10T14:00:00Z",
    "created_at": "2026-04-08T09:00:00Z"
  }
]
```

---

#### `POST /progress` — Log progress 🔒

Records that the authenticated scout has completed a step.

**Request body:**

```json
{
  "badge_slug": "cybersecurity",
  "level_index": 0,
  "step_index": 0,
  "notes": "Gemaakt tijdens zomerkamp."
}
```

**Response `201`:**

```json
{
  "id": "p1p2p3p4-...",
  "badge_slug": "cybersecurity",
  "level_index": 0,
  "step_index": 0,
  "notes": "Gemaakt tijdens zomerkamp.",
  "status": "open",
  "signed_off_by": null,
  "signed_off_at": null,
  "created_at": "2026-04-18T10:00:00Z"
}
```

**Response `409`:** Progress for this step already exists and is completed.

---

#### `GET /progress/{id}` — Get a progress entry 🔒

**Response `200`:** Single progress entry (same shape as above).

**Response `404`:** Not found or not owned by the authenticated user.

---

#### `PUT /progress/{id}` — Edit a progress entry 🔒

Only `notes` can be edited. Only allowed when `status` is `open` or `pending_signoff`.

**Request body:**

```json
{
  "notes": "Gemaakt tijdens zomerkamp, beoordeeld door de groep."
}
```

**Response `200`:** Updated progress entry (same shape as `POST /progress` response).

**Response `403`:** Entry has been signed off and can no longer be edited.

**Response `404`:** Not found or not owned by the authenticated user.

---

#### `DELETE /progress/{id}` — Delete a progress entry 🔒

Only allowed when `status` is `open` or `pending_signoff`.

**Response `204`:** No content.

**Response `403`:** Cannot delete a completed (signed-off) entry.

---

#### `POST /progress/{id}/signoff` — Request sign-off from a mentor 🔒

The scout submits one mentor's email address. This endpoint can be called multiple times to invite additional mentors. The entry is completed as soon as any one mentor confirms.

The server then:

1. If the mentor **has an account** — sends them a sign-off link by email.
2. If the mentor **has no account** — automatically creates a `pending` user record for them (no password yet), then sends an invitation email. After completing registration (step 2 + 3 of the registration flow) they are redirected to the sign-off link.

**Request body:**

```json
{
  "mentor_email": "leider.piet@example.com"
}
```

**Response `202`:** Sign-off request accepted. Email sent to mentor.

**Response `404`:** Progress entry not found.

**Response `409`:** This mentor has already been invited, or the entry is already completed.

---

#### `POST /progress/{id}/signoff/confirm` — Confirm sign-off 🔒

Called by the mentor after following the link in their email. Marks the entry as completed and cancels any outstanding sign-off requests to other mentors.
The mentor must be authenticated (either via existing session or immediately after registration).

**Response `200`:** Updated progress entry with `status: "completed"`.

**Response `403`:** Authenticated user is not the invited mentor.

**Response `404`:** Progress entry not found.

**Response `409`:** Already signed off.

---

#### `GET /signoff-requests` — Open sign-off requests for the authenticated mentor 🔒

Returns all progress entries where the authenticated user has been invited to sign off and has not yet done so.

**Response `200`:**

```json
[
  {
    "id": "p1p2p3p4-...",
    "scout": { "user_id": "a1b2c3d4-...", "name": "Jan" },
    "badge_slug": "cybersecurity",
    "level_index": 0,
    "step_index": 0,
    "notes": "Gemaakt tijdens zomerkamp.",
    "status": "pending_signoff",
    "created_at": "2026-04-08T09:00:00Z"
  }
]
```

---

#### `GET /progress/mentors` — Mentors who have previously signed off this scout 🔒

Returns a deduplicated list of mentors who have signed off at least one progress entry for the authenticated scout, ordered by most recent sign-off first. Intended for easy re-selection when requesting a new sign-off.

**Response `200`:**

```json
[
  { "user_id": "m1m2m3m4-...", "name": "Leider Piet" }
]
```

---

## Badge Response Shapes

These shapes are derived from YAML files at runtime — they are not stored in the database.

### `Badge` (list item)

| Field | Type | Description |
|-------|------|-------------|
| `slug` | string | URL identifier, matches YAML filename |
| `title` | string | Badge title |
| `category` | string | `gewoon` or `buitengewoon` |
| `images` | string[3] | URLs to the three badge images (`/images/{slug}.1.png` etc.) |

### `BadgeDetail`

| Field | Type | Description |
|-------|------|-------------|
| `slug` | string | URL identifier |
| `title` | string | Badge title |
| `category` | string | `gewoon` or `buitengewoon` |
| `images` | string[3] | URLs to the three badge images |
| `introduction` | string | Introductory text |
| `step_groups` | StepGroup[] | Named groups of steps |
| `afterword` | string | Closing text |

### `StepGroup`

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Group name |
| `steps` | Step[] | Ordered list of steps |

### `Step`

| Field | Type | Description |
|-------|------|-------------|
| `index` | integer | Zero-based position within the group |
| `text` | string | Full step description |

---

## Data Models

### `User`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique identifier |
| `email` | string | Email address — also used as login |
| `name` | string | Display name — defaults to the local part of the email address |
| `status` | string | `pending` (email unconfirmed) \| `active` |
| `created_at` | datetime | ISO 8601 |

### `ProgressEntry`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique identifier |
| `badge_slug` | string | The badge being worked on |
| `level_index` | integer | Zero-based level index (0–4) |
| `step_index` | integer | Zero-based step index within the level (0–2) |
| `notes` | string | Scout's notes |
| `status` | string | `open` \| `pending_signoff` \| `completed` |
| `pending_mentors` | `{user_id, name}`[] | Users with an outstanding sign-off request |
| `signed_off_by` | `{user_id, name}` \| null | User who signed off |
| `signed_off_at` | datetime \| null | When it was signed off |
| `created_at` | datetime | ISO 8601 |

---

## Error Responses

All errors follow the same shape:

```json
{
  "detail": "<human-readable message>"
}
```

| Status | Meaning |
|--------|---------|
| `400` | Bad request — invalid input |
| `401` | Unauthorized — missing or expired token |
| `403` | Forbidden — authenticated but not allowed |
| `404` | Not found |
| `409` | Conflict — duplicate or invalid state transition |
| `422` | Validation error — request body failed schema validation |
| `500` | Internal server error |

---

## HTML Endpoints

These endpoints serve the HTMX frontend. Full pages are returned on direct navigation; HTML fragments are returned when the request includes `HX-Request: true`.

### Authentication

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/login` | Login page |
| `POST` | `/login` | Submit credentials — redirects to `/` on success or re-renders form with error |
| `POST` | `/logout` | Clears session, redirects to `/login` |
| `GET` | `/register` | Registration page (step 1) |
| `POST` | `/register` | Submit email — renders confirmation prompt |
| `GET` | `/register/confirm` | Confirm email page (step 2 — user arrives via link in email) |
| `POST` | `/register/confirm` | Submit code — renders set-password form |
| `POST` | `/register/activate` | Submit password — logs user in, redirects to `/` |
| `GET` | `/forgot-password` | Forgot password page |
| `POST` | `/forgot-password` | Submit email — renders confirmation prompt |

### Badges

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/badges` | Badge catalogue — renders full badge list grouped by category |
| `GET` | `/badges/{slug}` | Badge detail page — shows all levels and steps |

### Progress

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/progress` | Progress overview — all logged steps for the current user |
| `POST` | `/progress` | Log a completed step — returns updated step fragment |
| `PUT` | `/progress/{id}` | Edit notes on a progress entry — returns updated entry fragment |
| `DELETE` | `/progress/{id}` | Delete a progress entry — returns updated step fragment |
| `POST` | `/progress/{id}/signoff` | Submit mentor email — sends sign-off or invitation email |
| `GET` | `/progress/{id}/signoff/confirm` | Mentor lands here from email link — shows confirmation page |
| `POST` | `/progress/{id}/signoff/confirm` | Mentor confirms sign-off — returns updated entry fragment |
| `GET` | `/signoff-requests` | Mentor's dashboard — lists all open sign-off requests |
| `GET` | `/progress/mentors` | Returns mentor list fragment for sign-off form pre-population |
