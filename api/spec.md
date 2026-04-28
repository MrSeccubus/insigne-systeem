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

### Version

#### `GET /api/version`

Returns the running application version and whether a newer release is available on GitHub.

No authentication required.

**Response `200`:**
```json
{
  "version": "v0.8.0",
  "newer_release": null
}
```

- `version` — current version string. Format `vX.Y.Z` when running on a tagged release, `vX.Y.Z+N` when N commits ahead of the latest tag (development/unreleased build).
- `newer_release` — tag name of the latest GitHub release if it is newer than the running version, otherwise `null`. Determined via a background cache refreshed at most once per hour.

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

#### `GET /api/users/me/memberships` — Get own active memberships 🔒

Returns all active (approved, not withdrawn) group and speltak memberships for the authenticated user.

**Response `200`:**

```json
{
  "group_memberships": [
    { "group_id": "...", "role": "groepsleider", "approved": true, "withdrawn": false }
  ],
  "speltak_memberships": [
    { "speltak_id": "...", "group_id": "...", "role": "scout", "approved": true, "withdrawn": false }
  ]
}
```

---

#### `GET /api/users/me/requests` — List own membership requests 🔒

Returns all membership requests submitted by the authenticated user (pending, approved, and rejected).

**Response `200`:** `MembershipRequest[]`

---

#### `DELETE /api/users/me/requests/{req_id}` — Cancel a membership request 🔒

Deletes the request if it belongs to the authenticated user. Silently ignored if the request belongs to another user.

**Response `204`:** No content.

---

#### `DELETE /api/users/me/requests` — Cancel all membership requests 🔒

Deletes all membership requests submitted by the authenticated user.

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

#### `POST /api/progress/{id}/signoff` — Request sign-off (direct email path) 🔒

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

**Response `403`:** Scout tried to invite themselves (`self_signoff`).

**Response `404`:** Progress entry not found.

**Response `409`:** This mentor has already been invited, or the entry is already `signed_off`, or the entry is not in `work_done`/`pending_signoff` status.

---

#### `POST /api/progress/{id}/signoff-speltak` — Request sign-off from all speltakleiders 🔒

Sends a sign-off request to every speltakleider of the given speltak. Suitable for non-peer-signoff speltakken where the leiding signs off.

**Request body:**

```json
{
  "speltak_id": "speltak-uuid"
}
```

**Response `202`:** Sign-off requests sent.

**Response `404`:** Progress entry not found, or no eligible leiders found (`no_eligible_mentors`).

**Response `409`:** Entry is already `signed_off`, or not in `work_done`/`pending_signoff` status.

---

#### `POST /api/progress/{id}/signoff-members` — Request sign-off from selected members 🔒

Sends sign-off requests to the selected member(s). Suitable for peer-signoff speltakken.

**Request body:**

```json
{
  "mentor_ids": ["user-uuid-1", "user-uuid-2"]
}
```

**Response `202`:** Sign-off requests sent.

**Response `404`:** Progress entry not found, or all selected users were ineligible (`no_eligible_mentors`).

**Response `409`:** Entry is already `signed_off`, or not in `work_done`/`pending_signoff` status.

---

#### `POST /api/progress/{id}/signoff/confirm` — Confirm sign-off 🔒

Called by the mentor. Marks the entry as `signed_off` and removes all outstanding sign-off requests.
The mentor must be authenticated and must have been invited.

**Response `200`:** Updated progress entry with `status: "signed_off"`.

**Response `403`:** Authenticated user is not an invited mentor, or tried to sign off their own entry (`self_signoff`).

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

### Groups

Groups organise scouts into a local scouting group. Each group contains one or more *speltakken* (age-based sub-groups). Membership of a group is managed via invites; managers can revoke invites and invitees can accept, deny, or dismiss them.

**Roles:**

| Role | Scope | Meaning |
|------|-------|---------|
| `groepsleider` | Group | Can manage the group, its speltakken, and all members |
| `speltakleider` | Speltak | Can manage the speltak and its members |
| `scout` | Speltak | Regular member |
| `member` | Group | Generic group membership (auto-created when added to a speltak) |

A user who is added to a speltak automatically receives a group-level `member` membership. If all speltak memberships are removed and the user holds no leadership role, the group membership is also removed.

**Invite lifecycle:**

```
pending (approved=false) → accepted (approved=true)
                         → denied (record deleted)
                         → withdrawn by manager (withdrawn=true)
                              → dismissed by invitee (record deleted)
```

---

#### `GET /api/groups` — List groups

Public. Returns groups sorted alphabetically (case-insensitive).

**Response `200`:** `Group[]`

---

#### `POST /api/groups` — Create group 🔒

Requires authentication. By default any authenticated user may create a group; this can be restricted to admins via `allow_any_user_to_create_groups: false` in `config.yml`.

**Request body:**

```json
{ "name": "Groep Noord", "slug": "groep-noord" }
```

**Response `201`:** `Group`

**Response `409`:** Slug already in use.

---

#### `GET /api/groups/{group_id}` — Get group

**Response `200`:** `Group`

**Response `404`:** Group not found.

---

#### `PUT /api/groups/{group_id}` — Update group 🔒

Requires groepsleider.

**Request body:** `{ "name": "...", "slug": "..." }`

**Response `200`:** Updated `Group`.

---

#### `DELETE /api/groups/{group_id}` — Delete group 🔒

Requires groepsleider.

**Response `204`:** No content.

---

#### `GET /api/groups/{group_id}/members` — List members 🔒

Requires groepsleider. Returns approved memberships only.

**Response `200`:** `GroupMembership[]`

---

#### `GET /api/groups/{group_id}/members/pending` — List pending invites 🔒

Requires groepsleider. Returns non-withdrawn pending memberships.

**Response `200`:** `GroupMembership[]`

---

#### `GET /api/groups/{group_id}/members/without-speltak` — List members not in any speltak 🔒

Requires groepsleider. Returns approved group members with role `member` who have no active speltak membership in this group.

**Response `200`:** `GroupMembership[]`

---

#### `POST /api/groups/{group_id}/members` — Set member role 🔒

Requires groepsleider. Creates or updates the membership for `user_id`.

**Request body:**

```json
{ "user_id": "a1b2-...", "role": "groepsleider" }
```

Role must be `groepsleider` or `member`.

**Response `204`:** No content.

---

#### `DELETE /api/groups/{group_id}/members/{user_id}` — Remove member 🔒

Requires groepsleider.

**Response `204`:** No content.

---

#### `POST /api/groups/{group_id}/members/{user_id}/withdraw` — Revoke invite 🔒

Requires groepsleider. Sets `withdrawn=true` on a pending membership.

**Response `204`:** No content.

---

#### `POST /api/groups/{group_id}/members/{user_id}/accept` — Accept invite 🔒

Must be called by the invitee themselves (`user_id` must match the authenticated user).

**Response `204`:** No content.

---

#### `POST /api/groups/{group_id}/members/{user_id}/deny` — Deny invite 🔒

Must be called by the invitee. Deletes the pending membership record.

**Response `204`:** No content.

---

#### `POST /api/groups/{group_id}/members/{user_id}/dismiss` — Dismiss withdrawn invite 🔒

Must be called by the invitee. Deletes a withdrawn (`withdrawn=true`) membership record.

**Response `204`:** No content.

---

#### `POST /api/groups/{group_id}/requests` — Submit membership request 🔒

Creates a pending membership request for the authenticated user. `speltak_id` is optional; omit it to request group-level membership.

**Request body:**

```json
{ "speltak_id": "..." }
```

**Response `201`:** `MembershipRequest`

**Response `409`:** Already a member, or a pending request already exists.

---

#### `GET /api/groups/{group_id}/requests` — List pending requests 🔒

Requires groepsleider. Returns all pending membership requests for the group.

**Response `200`:** `MembershipRequest[]`

---

#### `POST /api/groups/{group_id}/requests/{req_id}/approve` — Approve request 🔒

Requires groepsleider. Creates the membership and marks the request as `approved`.

**Response `204`:** No content.

**Response `404`:** Request not found.

---

#### `POST /api/groups/{group_id}/requests/{req_id}/reject` — Reject request 🔒

Requires groepsleider. Marks the request as `rejected`. No membership is created.

**Response `204`:** No content.

**Response `404`:** Request not found.

---

#### `POST /api/groups/{group_id}/speltakken` — Create speltak 🔒

Requires groepsleider.

**Request body:**

```json
{ "name": "Welpen", "slug": "welpen", "peer_signoff": false }
```

`peer_signoff: true` marks the speltak as a volwassenen speltak where members may sign off each other's progress.

**Response `201`:** `Speltak`

**Response `409`:** Slug already in use within this group.

---

#### `PUT /api/groups/{group_id}/speltakken/{speltak_id}` — Update speltak 🔒

Requires groepsleider.

**Request body:** `{ "name": "...", "slug": "...", "peer_signoff": false }`

**Response `200`:** Updated `Speltak`.

---

#### `DELETE /api/groups/{group_id}/speltakken/{speltak_id}` — Delete speltak 🔒

Requires groepsleider.

**Response `204`:** No content.

---

#### `GET /api/groups/{group_id}/speltakken/{speltak_id}/members` — List speltak members 🔒

Requires speltakleider or groepsleider. Returns approved memberships only.

**Response `200`:** `SpeltakMembership[]`

---

#### `GET /api/groups/{group_id}/speltakken/{speltak_id}/members/pending` — List pending speltak invites 🔒

Requires speltakleider or groepsleider. Returns non-withdrawn pending memberships.

**Response `200`:** `SpeltakMembership[]`

---

#### `POST /api/groups/{group_id}/speltakken/{speltak_id}/members` — Set speltak member role 🔒

Requires speltakleider or groepsleider.

**Request body:**

```json
{ "user_id": "a1b2-...", "role": "scout" }
```

Role must be `speltakleider` or `scout`.

**Response `204`:** No content.

---

#### `DELETE /api/groups/{group_id}/speltakken/{speltak_id}/members/{user_id}` — Remove speltak member 🔒

Requires speltakleider or groepsleider. Auto-removes the group membership if the user has no remaining speltak ties and no leadership role.

**Response `204`:** No content.

---

#### `POST /api/groups/{group_id}/speltakken/{speltak_id}/members/{user_id}/transfer` — Transfer scout 🔒

Moves the scout to a different speltak within the same group.

**Request body:**

```json
{ "to_speltak_id": "b2c3-..." }
```

**Response `204`:** No content.

---

#### `POST /api/groups/{group_id}/speltakken/{speltak_id}/members/{user_id}/withdraw` — Revoke speltak invite 🔒

Requires speltakleider or groepsleider. For scouts who were emailless and had an email attached: reverts the scout to emailless (clears email, restores active status, invalidates tokens) instead of marking withdrawn.

**Response `204`:** No content.

---

#### `POST /api/groups/{group_id}/speltakken/{speltak_id}/members/{user_id}/accept` — Accept speltak invite 🔒

Must be called by the invitee. If the invite has a linked emailless scout (`source_scout_id`), the scout record is cleaned up without merging progress (equivalent to `accept-without-merge`). Use `accept-with-merge` if the client wants the user to take over the scout's progress.

**Response `204`:** No content.

---

#### `POST /api/groups/{group_id}/speltakken/{speltak_id}/members/{user_id}/accept-with-merge` — Accept speltak invite and merge scout progress 🔒

Must be called by the invitee. If the invite has a linked emailless scout (`source_scout_id`), their progress entries are merged into the user's account (scout wins on higher status, existing user wins on equal/lower). The scout record is then deleted. If there is no linked scout this behaves identically to `accept`.

**Response `204`:** No content.

---

#### `POST /api/groups/{group_id}/speltakken/{speltak_id}/members/{user_id}/deny` — Deny speltak invite 🔒

Must be called by the invitee. Deletes the record.

**Response `204`:** No content.

---

#### `POST /api/groups/{group_id}/speltakken/{speltak_id}/members/{user_id}/dismiss` — Dismiss withdrawn speltak invite 🔒

Must be called by the invitee. Deletes a withdrawn record.

**Response `204`:** No content.

---

#### `POST /api/groups/{group_id}/speltakken/{speltak_id}/scouts` — Add scout without account 🔒

Requires speltakleider or groepsleider. Creates a name-only user record (no email, no password) and adds them to the speltak as `scout`.

**Request body:**

```json
{ "name": "Piet" }
```

**Response `201`:**

```json
{ "id": "a1b2-...", "name": "Piet" }
```

---

#### `POST /api/groups/{group_id}/speltakken/{speltak_id}/members/{user_id}/set-email` — Attach email to emailless scout 🔒

Requires speltakleider or groepsleider.

- **Email unknown**: assigns the email to the scout's account, puts it in `pending`, moves the speltak membership to pending, and sends a registration invite.
- **Email belongs to active user**: merges progress into the existing user (higher status wins per step), deletes the emailless record, and creates a pending speltak invite for the existing user.

**Request body:**

```json
{ "email": "piet@example.com" }
```

**Response `204`:** No content.

**Response `409`:** Email already in use by a pending (not yet active) user.

---

### Invitations

#### `GET /api/invitations/me` — Current user's invitations 🔒

Returns all pending and withdrawn group and speltak invitations for the authenticated user.

**Response `200`:**

```json
{
  "group_invites": [
    {
      "group_id": "g1-...",
      "group_name": "Groep Noord",
      "role": "member",
      "withdrawn": false,
      "invited_by_id": "u1-..."
    }
  ],
  "speltak_invites": [
    {
      "speltak_id": "s1-...",
      "speltak_name": "Welpen",
      "group_id": "g1-...",
      "group_name": "Groep Noord",
      "role": "scout",
      "withdrawn": false,
      "invited_by_id": "u1-...",
      "source_scout_id": "u2-...",
      "scout_has_progress": true
    }
  ]
}
```

---

### `GET /api/requests` — All pending requests across groups (leader view) 🔒

Returns all pending membership requests for groups the authenticated user manages (i.e., is groepsleider of). Ordered by `created_at`.

**Response `200`:** `MembershipRequest[]`

---

## Data Models (Groups)

### `Group`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique identifier |
| `name` | string | Display name |
| `slug` | string | URL-safe identifier |
| `created_at` | datetime | ISO 8601 |

### `Speltak`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique identifier |
| `group_id` | UUID | Parent group |
| `name` | string | Display name |
| `slug` | string | URL-safe identifier (unique within group) |
| `peer_signoff` | boolean | If true, members may sign off each other's progress |

### `GroupMembership`

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | UUID | The member |
| `role` | string | `groepsleider` \| `member` |
| `approved` | boolean | `false` = pending invite |
| `withdrawn` | boolean | `true` = manager revoked, awaiting dismissal by invitee |
| `invited_by_id` | UUID \| null | Who sent the invite |

### `SpeltakMembership`

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | UUID | The member |
| `role` | string | `speltakleider` \| `scout` |
| `approved` | boolean | `false` = pending invite |
| `withdrawn` | boolean | `true` = manager revoked, awaiting dismissal by invitee |
| `invited_by_id` | UUID \| null | Who sent the invite |

### `MembershipRequest`

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique identifier |
| `user_id` | UUID | Requester |
| `group_id` | UUID | Target group |
| `speltak_id` | UUID \| null | Target speltak (null = group-level request) |
| `status` | string | `pending` \| `approved` \| `rejected` |
| `reviewed_by_id` | UUID \| null | Who approved or rejected |
| `created_at` | datetime | ISO 8601 |

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
| `GET` | `/contact` | Contact form |

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
| `POST` | `/progress/{id}/request-signoff` | Request sign-off via direct email (auth required) |
| `POST` | `/progress/{id}/request-signoff-speltak` | Request sign-off from all speltakleiders of a speltak (auth required) |
| `POST` | `/progress/{id}/request-signoff-members` | Request sign-off from selected peer members (auth required) |
| `POST` | `/progress/{id}/cancel-signoff` | Cancel all pending sign-off requests (auth required) |
| `POST` | `/progress/{id}/delete` | Delete a progress entry (auth required) |
| `GET` | `/signoff-requests/count` | Pending sign-off count badge for nav (auth required) |
| `POST` | `/progress/{id}/confirm-signoff` | Mentor confirms sign-off (auth required) |
| `POST` | `/progress/{id}/reject-signoff` | Mentor rejects sign-off — removes only this mentor's request; reverts to `work_done` only if no requests remain (auth required) |

### Groups HTML pages

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/groups` | List all groups, with pending request summary for leaders (auth required) |
| `GET` | `/groups/join` | Browse groups and request membership (auth required) |
| `GET` | `/groups/invite-leader` | Invite someone to create and lead a new group (auth required) |
| `GET` | `/groups/new` | Create group form (auth required) |
| `GET` | `/groups/{slug}` | Group detail — members, speltakken |
| `GET` | `/groups/{slug}/edit` | Edit group form |
| `GET` | `/groups/{slug}/speltakken/{speltak_slug}` | Speltak detail — members, pending invites |
| `GET` | `/groups/{slug}/speltakken/{speltak_slug}/edit` | Edit speltak form |
| `GET` | `/requests` | All pending membership requests across managed groups (auth required) |

### Groups HTML utility endpoints (JSON responses)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/groups/search?q=` | Search groups by name — returns `[{id, name, slug}]` |
| `GET` | `/groups/{slug}/members/check-email?email=` | Check if email belongs to an active user — returns `{exists}` |
| `GET` | `/groups/{slug}/speltakken/{speltak_slug}/members/check-email?email=` | Same, also returns `{exists, in_group}` |

### Groups HTML actions (form POST, redirect on success)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/groups/new` | Create group |
| `POST` | `/groups/join` | Submit membership request (also accepts `Accept: application/json`, returns `{ok}` or `{error}`) |
| `POST` | `/groups/invite-leader` | Send invite-to-create-group email |
| `POST` | `/groups/{slug}/edit` | Update group name/slug |
| `POST` | `/groups/{slug}/delete` | Delete group |
| `POST` | `/groups/{slug}/members/add` | Add member by email (direct if known, invite if not) |
| `POST` | `/groups/{slug}/members/invite` | Send group invite email |
| `POST` | `/groups/{slug}/members/{uid}/role` | Change groepsleider/member role |
| `POST` | `/groups/{slug}/members/{uid}/remove` | Remove member |
| `POST` | `/groups/{slug}/members/{uid}/assign-speltak` | Assign a group member to a speltak |
| `POST` | `/groups/{slug}/members/{uid}/withdraw` | Revoke pending invite (returns 204, called via fetch) |
| `POST` | `/requests/{req_id}/approve` | Approve a membership request (leader only) |
| `POST` | `/requests/{req_id}/reject` | Reject a membership request (leader only) |
| `POST` | `/my-requests/{req_id}/cancel` | Cancel own membership request |
| `POST` | `/my-requests/cancel-all` | Cancel all own membership requests |
| `POST` | `/groups/{slug}/speltakken/new` | Create speltak |
| `POST` | `/groups/{slug}/speltakken/{speltak_slug}/edit` | Update speltak |
| `POST` | `/groups/{slug}/speltakken/{speltak_slug}/delete` | Delete speltak |
| `POST` | `/groups/{slug}/speltakken/{speltak_slug}/members/add` | Add speltak member by email |
| `POST` | `/groups/{slug}/speltakken/{speltak_slug}/members/invite` | Send speltak invite email |
| `POST` | `/groups/{slug}/speltakken/{speltak_slug}/members/new-scout` | Add scout without account |
| `POST` | `/groups/{slug}/speltakken/{speltak_slug}/members/{uid}/role` | Change speltakleider/scout role |
| `POST` | `/groups/{slug}/speltakken/{speltak_slug}/members/{uid}/transfer` | Transfer scout to another speltak |
| `POST` | `/groups/{slug}/speltakken/{speltak_slug}/members/{uid}/remove` | Remove speltak member |
| `POST` | `/groups/{slug}/speltakken/{speltak_slug}/members/{uid}/withdraw` | Revoke pending invite (fetch, returns JSON `{reverted}`) |
| `POST` | `/groups/{slug}/speltakken/{speltak_slug}/members/{uid}/set-email` | Attach email to emailless scout |
| `GET` | `/groups/{slug}/speltakken/{speltak_slug}/members/check-email` | Check if email is known (JSON `{exists, in_group}`) |
| `POST` | `/invitations/group/{group_id}/accept` | Accept group invite |
| `POST` | `/invitations/group/{group_id}/deny` | Deny group invite |
| `POST` | `/invitations/speltak/{speltak_id}/accept` | Accept speltak invite (shows merge prompt if linked to an emailless scout with progress) |
| `POST` | `/invitations/speltak/{speltak_id}/accept-with-merge` | Accept speltak invite and merge progress from linked emailless scout |
| `POST` | `/invitations/speltak/{speltak_id}/accept-without-merge` | Accept speltak invite and discard linked emailless scout's progress |
| `POST` | `/invitations/speltak/{speltak_id}/deny` | Deny speltak invite |
| `POST` | `/invitations/group/{group_id}/dismiss` | Dismiss withdrawn group invite |
| `POST` | `/invitations/speltak/{speltak_id}/dismiss` | Dismiss withdrawn speltak invite |

### Speltakleider progress HTML pages

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/my-speltakken` | Dispatch: redirects to speltak progress if only one; lists all explicit speltakleider memberships otherwise (auth required) |
| `GET` | `/groups/{slug}/progress` | Group progress hub — lists all speltakken with member counts and links; groepsleider/admin only (auth required) |
| `GET` | `/groups/{slug}/speltakken/{speltak_slug}/progress` | Badge-first progress overview for all scouts in the speltak; requires speltakleider or groepsleider (auth required) |

**Query parameters for speltak progress page:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `only_favorites` | boolean | `false` | Show only badges marked as favorites for this speltak |

### Speltakleider progress HTML actions (HTMX partials / form POST)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/groups/{slug}/speltakken/{speltak_slug}/scouts/{scout_id}/progress/set` | HTMX: cycle a scout's step status; returns updated `leider_step_check` partial. Requires speltakleider. |
| `POST` | `/groups/{slug}/speltakken/{speltak_slug}/favorite-badge` | HTMX: toggle favorite status for a badge in this speltak; returns updated star span. Requires speltakleider. |

**Form fields for `progress/set`:**

| Field | Type | Description |
|-------|------|-------------|
| `badge_slug` | string | Badge being updated |
| `level_index` | integer | Eis index (0–4) |
| `step_index` | integer | Niveau index (0–2) |
| `status` | string | New status: `none` \| `in_progress` \| `work_done` \| `signed_off` |
| `message` | string | **Required** when downgrading a `signed_off` entry; stored as a `SignoffRejection`. |

**Form fields for `favorite-badge`:**

| Field | Type | Description |
|-------|------|-------------|
| `badge_slug` | string | Badge slug to toggle |

---

### Speltak and group favorite badge endpoints (JSON API)

#### `GET /api/groups/{group_id}/speltakken/{speltak_id}/favorite-badges` — List speltak favorites 🔒

Requires speltakleider or groepsleider.

**Response `200`:** `string[]` — list of badge slugs marked as favorites for this speltak.

---

#### `POST /api/groups/{group_id}/speltakken/{speltak_id}/favorite-badges/toggle` — Toggle speltak favorite 🔒

Requires speltakleider or groepsleider.

**Request body:**

```json
{ "badge_slug": "vredeslicht" }
```

**Response `200`:**

```json
{ "badge_slug": "vredeslicht", "is_favorite": true }
```

---

#### `GET /api/groups/{group_id}/favorite-badges` — List group favorites 🔒

Requires groepsleider.

**Response `200`:** `string[]` — list of badge slugs marked as favorites for this group.

---

#### `POST /api/groups/{group_id}/favorite-badges/toggle` — Toggle group favorite 🔒

Requires groepsleider.

**Request body:**

```json
{ "badge_slug": "vredeslicht" }
```

**Response `200`:**

```json
{ "badge_slug": "vredeslicht", "is_favorite": true }
```

---

#### `POST /api/groups/{group_id}/speltakken/{speltak_id}/scouts/{scout_id}/progress/set` — Set scout progress 🔒

Requires speltakleider or groepsleider. Sets a scout's step status. Downgrading a `signed_off` entry requires a non-empty `message`; the reason is stored as a `SignoffRejection`.

**Request body:**

```json
{
  "badge_slug": "vredeslicht",
  "level_index": 0,
  "step_index": 1,
  "status": "in_progress",
  "message": "Needs more practice"
}
```

`status` must be `none`, `in_progress`, `work_done`, or `signed_off`. `none` deletes the entry. `message` is optional unless the entry is currently `signed_off` and `status` is not `signed_off`.

**Response `200`:** Updated `ProgressEntry`, or `{}` when `status` is `none` (entry deleted).

**Response `403`:** Not authorized to manage this speltak, or attempting to edit own progress, or scout is not in this speltak.

**Response `409`:** Entry is in `pending_signoff` status and cannot be changed.

**Response `422`:** Downgrading a `signed_off` entry without a `message`.

---

## Contact

---

#### `GET /api/contact/captcha` — Get a captcha challenge

Returns a signed math question for anonymous contact form submissions. The token embeds a 10-minute time bucket and is signed with a key derived from the server secret (independent of the JWT signing key).

Public endpoint (no token required).

**Response `200`:**

```json
{ "token": "<signed-token>", "a": 3, "b": 5 }
```

The client must display "Wat is {a} + {b}?" and submit the user's answer together with the token.

---

#### `POST /api/contact` — Send a contact message

Forwards the message to all configured system administrators by email.

- **Authenticated** (`Authorization: Bearer <token>`): `sender_email`, `captcha_token`, and `captcha_answer` are ignored; the user's registered email is used.
- **Anonymous**: `sender_email`, `captcha_token`, and `captcha_answer` are all required. The captcha must have been obtained from `GET /api/contact/captcha` within the last ~20 minutes.

**Request body (authenticated):**

```json
{ "subject": "Mijn vraag", "body": "Hallo..." }
```

**Request body (anonymous):**

```json
{
  "subject": "Mijn vraag",
  "body": "Hallo...",
  "sender_email": "user@example.com",
  "captcha_token": "<token from GET /api/contact/captcha>",
  "captcha_answer": 8
}
```

**Response `202`:** `{ "detail": "Message sent." }`

**Response `400`:** Invalid or expired captcha answer.

**Response `422`:** Missing required fields for anonymous submission.

---

### Contact HTML pages

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/contact` | Contact form — anonymous users see email field + math captcha; authenticated users see only subject + body |
| `POST` | `/contact` | Submit contact form — sends message to admins; returns success or re-renders form with error |
