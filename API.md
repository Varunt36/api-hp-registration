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
  "payment_method": "stripe",
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

| Field                  | Type    | Required                                    | Notes                                                  |
| ---------------------- | ------- | ------------------------------------------- | ------------------------------------------------------ |
| `country`              | string  | Yes                                         | 2-letter ISO country code (uppercase)                  |
| `karyakarta`           | string  | Yes                                         | Group leader / coordinator name (1–200 chars)          |
| `terms_accepted`       | boolean | Yes                                         | Must be `true`                                         |
| `payment_method`       | string  | No                                          | `"stripe"` (default). Other values not supported.      |
| `members`              | array   | Yes                                         | 1–4 members                                            |
| `members[].first_name` | string  | Yes                                         | 1–100 chars                                            |
| `members[].last_name`  | string  | Yes                                         | 1–100 chars                                            |
| `members[].gender`     | string  | Yes                                         | `"male"` or `"female"`                                 |
| `members[].dob`        | string  | Yes                                         | `YYYY-MM-DD`, not in the future, year ≥ 1900           |
| `members[].email`      | string  | **Yes for 1st member**, optional for others | Emails/QR sent here                                    |
| `members[].phone`      | string  | No                                          | Digits / spaces / dashes / parens, 7–20 chars          |

> **Pricing is computed server-side.** Do not send `amount`. The backend charges `PRICE_PER_PERSON_EUR` (default €290, env-overridable) for each member who is **5 or older** on the event date (`2026-08-15`, hardcoded). Members under 5 are free.

### Success Response — `200 OK`

```json
{
  "payment_url": "https://checkout.stripe.com/c/pay/cs_test_...",
  "reference": "8a3f9e1c-2b4d-4f7a-9c0e-1234567890ab"
}
```

`reference` is the **payment intent UUID**, used to poll status after redirect-back. The human-readable registration reference (e.g. `HP-2026-00001`) is allocated *after* the Stripe webhook confirms payment, and is returned by `GET /payment/status/{reference}`.

**FE action:** persist `reference` (e.g. in `sessionStorage`), then redirect the browser to `payment_url`. After the user approves/pays, Stripe redirects back to:

- Success: `{FRONTEND_URL}/payment/success?ref={reference}`
- Cancel: `{FRONTEND_URL}/payment/cancel`

These two FE routes **must** exist.

> **Important:** the success redirect happens _before_ the registration is finalized. Finalization (members inserted, emails sent) happens on the provider webhook, server-to-server. The success page should poll `GET /payment/status/{reference}` until `status === "paid"` to obtain the final `reference` to show the user.

### Error Responses

All errors follow the shape:

```json
{ "error": { "code": "QUOTA_EXCEEDED", "message": "…" } }
```

| Status | Code                           | Meaning                                               |
| ------ | ------------------------------ | ----------------------------------------------------- |
| `409`  | `QUOTA_EXCEEDED`               | Country is full                                       |
| `422`  | `VALIDATION_ERROR`             | Bad input — `error.details[]` lists each field        |
| `502`  | `PAYMENT_PROVIDER_UNREACHABLE` | Provider unreachable — FE: "try again"                |
| `502`  | `PAYMENT_PROVIDER_REJECTED`    | Provider rejected our request — FE: "contact support" |
| `503`  | `PAYMENT_NOT_CONFIGURED`       | Provider credentials missing on backend               |

---

## GET `/payment/status/{reference}`

Look up payment status by the `reference` (intent UUID) returned from `/create-payment`. Useful for FE polling on the success page.

### Response — `200 OK`

```json
{ "status": "paid", "reference": "HP-2026-00001", "failure_reason": null }
```

`status` is one of: `"paid"`, `"pending"`, `"consumed"`, `"expired"`, `"failed"`, `"not_found"`. The `reference` field here is the **human-readable registration reference** (e.g. `HP-2026-00001`), set only when `status === "paid"`. `failure_reason` is set when `status` is `"failed"` or `"expired"`.

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
