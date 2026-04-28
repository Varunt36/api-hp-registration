# HP Registration API

**Base URL:** `http://localhost:8000` (local) | `https://hp-registration-api.onrender.com` (production)

**Swagger Docs:** `{BASE_URL}/docs`

---

## POST `/register`

Register a group with one or more members. Generates QR codes and sends 3 emails per member.

### Rules

- First member **must** have an email (primary contact)
- Other members: email and phone are **optional**
- If a member has no email, their QR code is sent to the first member's email
- All data is sent in **one request** after the form is fully filled

### Request

```json
{
  "country": "DE",
  "karyakarta": "John Doe",
  "members": [
    {
      "first_name": "John",
      "last_name": "Doe",
      "gender": "male",
      "dob": "1990-05-15",
      "email": "john@example.com",
      "phone": "+491234567890"
    },
    {
      "first_name": "Jane",
      "last_name": "Doe",
      "gender": "female",
      "dob": "1992-08-20"
    },
    {
      "first_name": "Bob",
      "last_name": "Smith",
      "gender": "male",
      "dob": "1985-03-10",
      "email": "bob@example.com"
    }
  ]
}
```

### Field Reference

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `country` | string | Yes | Country code: `DE`, `AT`, `CH`, `GB`, `US`, `IN`, `NZ` |
| `karyakarta` | string | Yes | Group leader / coordinator name |
| `members` | array | Yes | At least 1 member |
| `members[].first_name` | string | Yes | |
| `members[].last_name` | string | Yes | |
| `members[].gender` | string | Yes | `"male"` or `"female"` |
| `members[].dob` | string | Yes | Date format: `YYYY-MM-DD` |
| `members[].email` | string | **Yes for 1st member**, optional for others | Emails/QR sent here |
| `members[].phone` | string | No | |

### Success Response — `200 OK`

```json
{
  "success": true,
  "reference": "HP-2026-00001",
  "member_count": 3
}
```

### Error Responses

**400 — Validation error:**
```json
{
  "detail": "First member must have an email address"
}
```

**400 — Country quota exceeded:**
```json
{
  "detail": "Registration limit reached for country DE. Only 5 spots remain."
}
```

---

## What happens after a successful registration?

1. Each member gets a unique ticket number (e.g. `HP-2026-00001-M1`, `HP-2026-00001-M2`)
2. A QR code is generated for each member (encodes their ticket number)
3. **3 emails** are sent per member:
   - **Registration confirmation** — ticket number + QR code image
   - **Travel guide** — event travel information
   - **WhatsApp & Instagram** — social media QR codes to connect
4. If a member has no email, all 3 emails go to the first member's email instead

---

## POST `/admin/registration`

Admin-only. Insert a registration directly into the DB, **bypassing payment** (no Stripe session, no payment row, no QR code, no emails). Useful for manual entries (comps, sponsors, on-the-day walk-ins).

### Auth

The request MUST include a Supabase Auth JWT in `Authorization: Bearer <jwt>`. The backend verifies the token against Supabase and checks that the user has `app_metadata.role = "admin"`.

- The role MUST live in `app_metadata` (server-set via the service role key). `user_metadata` is user-editable and is intentionally ignored for authorization.
- To grant admin to a user, set `raw_app_meta_data` on `auth.users`:
  ```sql
  update auth.users
  set raw_app_meta_data = jsonb_set(coalesce(raw_app_meta_data, '{}'::jsonb), '{role}', '"admin"')
  where email = 'admin@example.com';
  ```
  The change appears in the JWT after the user's next token refresh.
- The endpoint is rate-limited (20 req/min per IP).

### Request

```json
{
  "full_name": "Jane Doe",
  "email": "jane@example.com",
  "dob": "1990-05-15",
  "gender": "female",
  "country": "DE"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `full_name` | string | Yes | 1–200 chars. Split on the first space → `first_name` / `last_name`. Single-word names get `last_name = "-"` (stop-gap; will be made nullable when the schema is updated) |
| `email` | string | Yes | Valid email address |
| `dob` | string | Yes | `YYYY-MM-DD`, between 1900-01-01 and today |
| `gender` | string | Yes | `"male"` or `"female"` |
| `country` | string | Yes | One of: `DE`, `AT`, `CH`, `GB`, `US`, `IN`, `NZ` |

### Defaults applied

`karyakarta=Admin` and `terms_accepted=true` are set automatically — admin-created rows are visibly tagged with `karyakarta=Admin`.

### Quota

The country quota is checked before insert. **Caveat:** the quota count today only counts registrations with a paid payment row, so admin-created rows do not consume quota for *future* checks. Admins can therefore push country totals past the cap. Acceptable for the comp/sponsor/walk-in use case; revisit if admin volume grows.

### Success Response — `200 OK`

```json
{
  "reference": "HP-2026-00042",
  "ticket_number": "HP-2026-00042-M1"
}
```

### Error Responses

- `401 ADMIN_UNAUTHORIZED` — missing/malformed `Authorization` header, or expired/invalid JWT
- `403 ADMIN_FORBIDDEN` — valid JWT but user is not an admin
- `409 QUOTA_EXCEEDED` — country quota is full
- `422 VALIDATION_ERROR` — invalid `full_name`, `email`, `dob`, `gender`, or `country`
- `429 RATE_LIMITED` — too many requests
- `500 REGISTRATION_FAILED` — DB insert failed (registration is rolled back)

---

## GET `/health`

Health check endpoint.

### Response — `200 OK`

```json
{
  "status": "ok"
}
```
