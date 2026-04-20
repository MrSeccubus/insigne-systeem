# Insigne Systeem — API Specification

## Overview

The API allows a scout to maintain their progress through the badge system of Scouting Nederland.
It consists of three areas:

- **Users** — account registration and management.
- **Badges** — a catalogue of badges, each with 5 *eisen* (requirements) and 3 *niveaus* (difficulty levels) per eis.
- **Progress** — a scout's log of completed steps, which can be signed off by registered mentors.

## Architecture: hybrid JSON + HTML

The server exposes two parallel layers:

| Layer | Prefix | Returns | Consumer |
|-------|--------|---------|----------|
| JSON API | `/api/` | `application/json` | Future integrations, mobile apps |
| HTML | `/` | `text/html` | HTMX frontend |

All JSON endpoints described in the **Resources** section are mounted under `/api/` (e.g. `GET /api/badges`).

The HTML layer serves full pages on initial load and HTML fragments for HTMX partial updates.

## Base URL

```
http://localhost:8000
```

## Authentication

- Registered users authenticate with their email address and password and receive a JWT.
- The JWT is valid for 30 days (configurable via `jwt.expire_days` in `config.yml`).
- Protected endpoints require the header: `Authorization: Bearer <token>`
- Sign-off requires a registered account. If the mentor is not yet registered, they receive an invitation email and can sign off after completing registration.

---

## Resources

---

### Users

Registration is a three-step process. The forgot-password flow reuses steps 2 and 3.

```
Step 1: POST /api/users              — provide email, receive confirmation email
Step 2: POST /api/users/confirm      — submit code from email, receive setup token
Step 3: POST /api/users/activate     — submit setup token + password
```

---

#### `POST /api/users` — Step 1: Request account (registration)

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

#### `POST /api/users/confirm` — Step 2: Confirm email

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

#### `POST /api/users/activate` — Step 3: Set password

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

#### `POST /api/auth/token` — Login

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

#### `POST /api/auth/forgot-password` — Request password reset

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
> `POST /api/users/confirm` to exchange the code for a setup token, then
> `POST /api/users/activate` to set the new password.

---

#### `GET /api/users/me` — Get own profile 🔒

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

#### `PUT /api/users/me` — Update own profile 🔒

All fields are optional. Progress and sign-offs are stored against `user_id`, so changing email is safe.

**Request body** (all fields optional):

```json
{
  "name": "Jan de Vries",
  "email": "new@example.com",
  "password": "newpassword"
}
```

**Response `200`:** Updated user object (same shape as `GET /api/users/me`).

**Response `400`:** Password too short (minimum 8 characters).

**Response `409`:** Email address already in use.

---

#### `DELETE /api/users/me` — Delete own account 🔒

**Response `204`:** No content.

---

### Badges

Badge data is read from YAML files on disk — there is no database table for badges.

- `api/data/badges.yml` — index of all badges, grouped by category
- `api/data/badges/<slug>.yml` — full detail for one badge
- `api/data/images/<slug>.{1,2,3}.png` — badge images, served under `/images/`

Badge endpoints are **public** (no authentication required).

---

#### `GET /api/badges` — List all badges

Returns an object with two keys: `gewoon` and `buitengewoon`, each containing an ordered list of badges.

**Response `200`:**

```json
{
  "gewoon": [
    {
      "slug": "sport_spel",
      "title": "Insigne Sport & Spel",
      "category": "gewoon",
      "images": [
        "/images/sport_spel.1.png",
        "/images/sport_spel.2.png",
        "/images/sport_spel.3.png"
      ]
    }
  ],
  "buitengewoon": [
    {
      "slug": "vredeslicht",
      "title": "Insigne Vredeslicht",
      "category": "buitengewoon",
      "images": [
        "/images/vredeslicht.1.png",
        "/images/vredeslicht.2.png",
        "/images/vredeslicht.3.png"
      ]
    }
  ]
}
```

---

#### `GET /api/badges/{slug}` — Get badge detail

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `slug` | string | Badge slug (e.g. `vredeslicht`) |

**Response `200`:**

```json
{
  "slug": "vredeslicht",
  "title": "Insigne Vredeslicht",
  "category": "buitengewoon",
  "images": [
    "/images/vredeslicht.1.png",
    "/images/vredeslicht.2.png",
    "/images/vredeslicht.3.png"
  ],
  "introduction": "Het insigne Vredeslicht is...",
  "levels": [
    {
      "name": "Ontdek de digitale wereld",
      "steps": [
        { "index": 0, "text": "Een digitale wereld vol kansen! ..." },
        { "index": 1, "text": "Laat je niet Phishen. ..." },
        { "index": 2, "text": "Ontdek het digitale domein ..." }
      ]
    }
  ],
  "afterword": "Toelichting Insigne Vredeslicht ..."
}
```

**Response `404`:** Badge not found.

---

### Progress

All progress endpoints require authentication (🔒).

A *progress entry* records that a scout is working on or has completed a specific eis at a specific niveau.

**Status lifecycle:**

```
in_progress → work_done → pending_signoff → signed_off
```

| Status | Meaning |
|--------|---------|
| `in_progress` | Scout has started the step |
| `work_done` | Scout has marked the step as done, not yet sent for sign-off |
| `pending_signoff` | One or more mentors have been invited to sign off |
| `signed_off` | A mentor has confirmed the step |

---

#### `GET /api/progress` — List own progress 🔒

Returns all progress entries for the authenticated scout.

**Query parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `badge_slug` | string | No | Filter by badge |
| `status` | string | No | Filter by status |

**Response `200`:**

```json
[
  {
    "id": "p1p2p3p4-...",
    "badge_slug": "vredeslicht",
    "level_index": 0,
    "step_index": 0,
    "notes": "Gemaakt tijdens zomerkamp.",
    "status": "signed_off",
    "pending_mentors": [],
    "signed_off_by": { "user_id": "m1m2m3m4-...", "name": "Leider Piet" },
    "signed_off_at": "2026-04-10T14:00:00Z",
    "created_at": "2026-04-08T09:00:00Z"
  }
]
```

---

#### `POST /api/progress` — Create a progress entry 🔒

Records that the authenticated scout has started or completed a step.

**Request body:**

```json
{
  "badge_slug": "vredeslicht",
  "level_index": 0,
  "step_index": 0,
  "notes": "Gemaakt tijdens zomerkamp."
}
```

**Response `201`:**

```json
{
  "id": "p1p2p3p4-...",
  "badge_slug": "vredeslicht",
  "level_index": 0,
  "step_index": 0,
  "notes": "Gemaakt tijdens zomerkamp.",
  "status": "in_progress",
  "pending_mentors": [],
  "signed_off_by": null,
  "signed_off_at": null,
  "created_at": "2026-04-18T10:00:00Z"
}
```

**Response `409`:** Progress for this step is already `signed_off`.

---

#### `GET /api/progress/{id}` — Get a progress entry 🔒

**Response `200`:** Single progress entry (same shape as above).

**Response `404`:** Not found or not owned by the authenticated user.

---

#### `PUT /api/progress/{id}` — Edit a progress entry 🔒

Only `notes` can be edited. Not allowed when status is `signed_off`.

**Request body:**

```json
{
  "notes": "Gemaakt tijdens zomerkamp, beoordeeld door de groep."
}
```

**Response `200`:** Updated progress entry.

**Response `403`:** Entry has been signed off and can no longer be edited.

**Response `404`:** Not found or not owned by the authenticated user.

---

#### `DELETE /api/progress/{id}` — Delete a progress entry 🔒

Not allowed when status is `signed_off`.

**Response `204`:** No content.

**Response `403`:** Cannot delete a signed-off entry.

---

#### `POST /api/progress/{id}/signoff` — Request sign-off from a mentor 🔒

The scout submits one mentor's email address. Can be called multiple times to invite additional mentors. The entry is completed as soon as any one mentor confirms.

1. If the mentor **has an account** — sends them a sign-off notification by email.
2. If the mentor **has no account** — creates a `pending` user record, sends an invitation email. After completing registration they can sign off.

**Request body:**

```json
{
  "mentor_email": "leider.piet@example.com"
}
```

**Response `202`:** Sign-off request accepted. Email sent to mentor.

**Response `404`:** Progress entry not found.

**Response `409`:** This mentor has already been invited, or the entry is already `signed_off`, or the entry is not in `work_done`/`pending_signoff` status.

---

#### `POST /api/progress/{id}/signoff/confirm` — Confirm sign-off 🔒

Called by the mentor. Marks the entry as `signed_off` and removes all outstanding sign-off requests.
The mentor must be authenticated and must have been invited.

**Response `200`:** Updated progress entry with `status: "signed_off"`.

**Response `403`:** Authenticated user is not an invited mentor.

**Response `404`:** Progress entry not found.

**Response `409`:** Already signed off.

---

#### `GET /api/signoff-requests` — Open sign-off requests for the authenticated mentor 🔒

Returns all progress entries where the authenticated user has been invited to sign off.

**Response `200`:**

```json
[
  {
    "id": "sr1sr2-...",
    "scout": { "user_id": "a1b2c3d4-...", "name": "Jan" },
    "badge_slug": "vredeslicht",
    "level_index": 0,
    "step_index": 0,
    "notes": "Gemaakt tijdens zomerkamp.",
    "status": "pending_signoff",
    "created_at": "2026-04-08T09:00:00Z"
  }
]
```

---

#### `GET /api/progress/mentors` — Previously used mentors 🔒

Returns a deduplicated list of mentors who have signed off at least one step for the authenticated scout, ordered by most recent sign-off first. Used to pre-populate the sign-off request form.

**Response `200`:**

```json
[
  { "user_id": "m1m2m3m4-...", "name": "Leider Piet" }
]
```

---

## Badge Response Shapes

### `Badge` (list item)

| Field | Type | Description |
|-------|------|-------------|
| `slug` | string | URL identifier, matches YAML filename |
| `title` | string | Badge title |
| `category` | string | `gewoon` or `buitengewoon` |
| `images` | string[3] | URLs to the three badge images |

### `BadgeDetail`

| Field | Type | Description |
|-------|------|-------------|
| `slug` | string | URL identifier |
| `title` | string | Badge title |
| `category` | string | `gewoon` or `buitengewoon` |
| `images` | string[3] | URLs to the three badge images |
| `introduction` | string | Introductory text (optional) |
| `levels` | StepGroup[] | 5 named requirement groups (*eisen*) |
| `afterword` | string | Closing text (optional) |

### `StepGroup` (one eis)

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Eis name |
| `steps` | Step[] | 3 steps — one per niveau |

### `Step`

| Field | Type | Description |
|-------|------|-------------|
| `index` | integer | Niveau index (0 = niveau 1, 1 = niveau 2, 2 = niveau 3) |
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
| `level_index` | integer | Zero-based eis index (0–4, one of the 5 requirement groups) |
| `step_index` | integer | Zero-based niveau index (0–2, one of the 3 difficulty levels) |
| `notes` | string \| null | Scout's notes |
| `status` | string | `in_progress` \| `work_done` \| `pending_signoff` \| `signed_off` |
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

These endpoints serve the HTMX frontend. Full pages are returned on direct navigation; HTML fragments (partials) are returned for HTMX requests. Authentication is via an `access_token` httponly cookie set on login/activation.

### Pages

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Home — badge catalogue with progress overview |
| `GET` | `/login` | Login page |
| `GET` | `/register` | Registration page |
| `GET` | `/register/confirm` | Confirm-code entry page (step 2) |
| `GET` | `/register/confirm/{code}` | Confirm link from email — redirects to set-password step |
| `GET` | `/profile` | Profile page (auth required) |
| `GET` | `/forgot-password` | Forgot password page |
| `GET` | `/forgot-password/confirm` | Reset-code entry page |
| `GET` | `/forgot-password/confirm/{code}` | Reset link from email — redirects to set-password step |
| `GET` | `/badges/{slug}` | Badge detail — all eisen and niveaus |
| `GET` | `/signoff-requests` | Mentor dashboard — open sign-off requests (auth required) |

### Form submissions (return HTML partials)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/register` | Submit email — renders confirmation prompt |
| `POST` | `/register/confirm` | Submit code — renders set-password form or error |
| `POST` | `/register/activate` | Submit password — sets cookie, sends `HX-Redirect: /` |
| `POST` | `/login` | Submit credentials — sets cookie + `HX-Redirect: /`, or re-renders form with error |
| `POST` | `/logout` | Clears cookie, redirects to `/login` |
| `POST` | `/profile` | Update name / email / password (auth required) |
| `POST` | `/forgot-password` | Submit email — renders confirmation prompt |
| `POST` | `/forgot-password/confirm` | Submit code — renders set-password form or error |
| `POST` | `/forgot-password/reset` | Submit new password — sets cookie, sends `HX-Redirect: /` |

### Badge / progress partials

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/badges/{slug}/niveau-checks/{niveau_index}` | Niveau progress check icons partial |
| `POST` | `/badges/{slug}/log` | Log a step (auth required) — returns updated step card partial |
| `POST` | `/progress/{id}/request-signoff` | Request sign-off from mentor (auth required) |
| `POST` | `/progress/{id}/cancel-signoff` | Cancel all pending sign-off requests (auth required) |
| `POST` | `/progress/{id}/delete` | Delete a progress entry (auth required) |
| `GET` | `/signoff-requests/count` | Pending sign-off count badge for nav (auth required) |
| `POST` | `/progress/{id}/confirm-signoff` | Mentor confirms sign-off (auth required) |
| `POST` | `/progress/{id}/reject-signoff` | Mentor rejects sign-off (auth required) |
