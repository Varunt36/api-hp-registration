# HP Registration API

**Base URL:** `http://localhost:8000` (local) | `https://hp-registration-api.onrender.com` (production)

**Swagger Docs:** `{BASE_URL}/docs`

---

## POST `/create-payment`

Create a payment session for a group registration. Returns a hosted-checkout URL the FE redirects to. Registration is only finalized after the provider webhook confirms payment.

### Rules

- First member **must** have an email (primary contact)
- Other members: email and phone are **optional**
- If a member has no email, their QR code is sent to the first member's email
- All data is sent in **one request** after the form is fully filled
- `terms_accepted` **must** be `true`

### Request

```json
{
  "country": "DE",
  "karyakarta": "John Doe",
  "terms_accepted": true,
  "payment_method": "paypal",
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
    }
  ]
}
```

### Field Reference

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `country` | string | Yes | One of: `DE`, `AT`, `CH`, `GB`, `US`, `IN`, `NZ` |
| `karyakarta` | string | Yes | Group leader / coordinator name (1–200 chars) |
| `terms_accepted` | boolean | Yes | Must be `true` |
| `payment_method` | string | Yes | `"stripe"` or `"paypal"` |
| `members` | array | Yes | 1–4 members |
| `members[].first_name` | string | Yes | 1–100 chars |
| `members[].last_name` | string | Yes | 1–100 chars |
| `members[].gender` | string | Yes | `"male"` or `"female"` |
| `members[].dob` | string | Yes | `YYYY-MM-DD`, not in the future, year ≥ 1900 |
| `members[].email` | string | **Yes for 1st member**, optional for others | Emails/QR sent here |
| `members[].phone` | string | No | Digits / spaces / dashes / parens, 7–20 chars |

### Success Response — `200 OK`

```json
{
  "payment_url": "https://www.paypal.com/checkoutnow?token=...",
  "reference": "HP-2026-00001"
}
```

**FE action:** redirect the browser to `payment_url`. That's the provider-hosted checkout page (Stripe Checkout or PayPal approval). After the user approves/pays, the provider redirects back to:

- Success: `{FRONTEND_URL}/payment/success?ref=HP-2026-00001`
- Cancel:  `{FRONTEND_URL}/payment/cancel`

These two FE routes **must** exist. The `ref` query param is the registration reference.

> **Important:** the success redirect happens *before* the registration is finalized. Finalization (members inserted, emails sent) happens on the provider webhook, server-to-server. The success page should either poll `GET /payment/status/{session_id}` or simply tell the user "we're processing — confirmation emails are on the way."

### Error Responses

All errors follow the shape:

```json
{ "error": { "code": "QUOTA_EXCEEDED", "message": "…" } }
```

| Status | Code | Meaning |
|---|---|---|
| `409` | `QUOTA_EXCEEDED` | Country is full |
| `422` | `VALIDATION_ERROR` | Bad input — `error.details[]` lists each field |
| `502` | `PAYMENT_PROVIDER_UNREACHABLE` | Provider unreachable — FE: "try again" |
| `502` | `PAYMENT_PROVIDER_REJECTED` | Provider rejected our request — FE: "contact support" |
| `503` | `PAYMENT_NOT_CONFIGURED` | Provider credentials missing on backend |

---

## GET `/payment/status/{session_id}`

**Stripe only today.** Look up payment status by Stripe Checkout Session ID. Useful for FE polling on the success page.

### Response — `200 OK`

```json
{ "status": "paid", "reference": "HP-2026-00001" }
```

`status` is one of: `"paid"`, `"pending"`, `"processing"`, `"not_found"`. `reference` is only set when `"paid"`.

> PayPal does not currently have an equivalent endpoint — for PayPal, rely on the confirmation email or have the success page show a "processing" state.

---

## What happens after a successful payment?

The provider webhook (`/webhooks/stripe` or `/webhooks/paypal`) fires server-to-server. The backend then:

1. Inserts each member with a unique ticket number (e.g. `HP-2026-00001-M1`, `HP-2026-00001-M2`)
2. Generates a QR code per member (encodes the ticket number)
3. Sends **3 emails** per member:
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
