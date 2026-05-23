# HP Registration API

**Base URL:** `http://localhost:8000` (local) | `https://hp-registration-api.onrender.com` (production)

**Swagger Docs:** `{BASE_URL}/docs`

---

## GET `/countries`

Return the canonical list of countries open for registration, sourced from the `country_quotas` table. **FE must fetch the country dropdown options from this endpoint** — do not hardcode the list.

### Response — `200 OK`

```json
[
  { "code": "AT", "max_members": 50 },
  { "code": "CH", "max_members": 50 },
  { "code": "DE", "max_members": 100 }
]
```

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
  "amount": 290.00,
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
| `country` | string | Yes | 2-letter ISO code. Must exist in `country_quotas` (fetch the list via `GET /countries`) |
| `karyakarta` | string | Yes | Group leader / coordinator name (1–200 chars) |
| `terms_accepted` | boolean | Yes | Must be `true` |
| `amount` | number | Yes | Total amount in EUR (FE-calculated) |
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
  "payment_url": "https://checkout.stripe.com/c/pay/cs_test_...",
  "reference": "HP-2026-00001"
}
```

**FE action:** redirect the browser to `payment_url`. That's the Stripe-hosted checkout page. After the user approves/pays, the provider redirects back to:

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

Look up payment status by Stripe Checkout Session ID. Useful for FE polling on the success page.

### Response — `200 OK`

```json
{ "status": "paid", "reference": "HP-2026-00001" }
```

`status` is one of: `"paid"`, `"pending"`, `"processing"`, `"not_found"`. `reference` is only set when `"paid"`.

---

## What happens after a successful payment?

The Stripe webhook (`/webhooks/stripe`) fires server-to-server. The backend then:

1. Inserts each member with a unique ticket number (e.g. `HP-2026-00001-M1`, `HP-2026-00001-M2`)
2. Generates a QR code per member (encodes the ticket number)
3. Sends **3 emails** per member:
   - **Registration confirmation** — ticket number + QR code image
   - **Travel guide** — event travel information
   - **WhatsApp & Instagram** — social media QR codes to connect
4. If a member has no email, all 3 emails go to the first member's email instead

---

## GET `/health`

Health check endpoint.

### Response — `200 OK`

```json
{
  "status": "ok"
}
```
