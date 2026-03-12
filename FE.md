# Frontend Integration Guide

## Base URL
- **Dev:** `http://localhost:8000`
- **Prod:** `https://your-api-domain.com`

---

## API Endpoint

### `POST /create-payment`

Single endpoint that handles registration + payment. No other endpoints needed.

**Request:**
```json
{
  "payment_method": "stripe",
  "country": "DE",
  "karyakarta": "Group Leader Name",
  "terms_accepted": true,
  "members": [
    {
      "first_name": "John",
      "middle_name": "M",
      "last_name": "Doe",
      "gender": "male",
      "dob": "1995-05-15",
      "email": "john@example.com",
      "phone": "+491234567890"
    },
    {
      "first_name": "Jane",
      "last_name": "Doe",
      "gender": "female",
      "dob": "1998-03-20",
      "email": "",
      "phone": ""
    }
  ]
}
```

**Success Response (200):**
```json
{
  "reference": "HP-2026-00015",
  "payment_url": "https://checkout.stripe.com/c/pay/cs_test_..."
}
```

**After success:** Redirect the user to `payment_url`
```js
const res = await fetch("/create-payment", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(formData) });
const data = await res.json();
window.location.href = data.payment_url;
```

**Error Response (400):** Business logic errors
```json
{
  "detail": "Registration limit reached for country DE. Only 5 spots remain."
}
```

**Error Response (422):** Validation errors
```json
{
  "detail": [
    {
      "loc": ["body", "members", 0, "email"],
      "msg": "First member must have an email address"
    }
  ]
}
```

**Error Response (500):**
```json
{
  "detail": "Payment creation failed. Please try again."
}
```

---

## Validation Rules

FE should validate these before calling the API:

| Field | Rules |
|-------|-------|
| `payment_method` | `"stripe"` (only option for now) |
| `country` | One of: `DE`, `AT`, `CH`, `GB`, `US`, `IN`, `NZ` |
| `karyakarta` | 1–200 chars, no `<>` or `&` characters |
| `terms_accepted` | Must be `true` |
| `members` | 1–4 members per registration |
| `first_name` | Required, 1–100 chars, no `<>` or `&` |
| `middle_name` | Optional (send `""` or omit) |
| `last_name` | Required, 1–100 chars, no `<>` or `&` |
| `gender` | `"male"` or `"female"` |
| `dob` | `YYYY-MM-DD`, must not be in the future, must be after 1900 |
| `email` | **First member MUST have a valid email** (primary contact). Others optional. |
| `phone` | Optional, format: optional `+` followed by 7–20 digits/spaces/dashes/parens |

---

## Frontend Routes

After payment, Stripe redirects the user back to your app. You need these two routes:

| Route | When | What to show |
|-------|------|-------------|
| `/payment/success?ref=HP-2026-00015` | Payment succeeded | "Registration confirmed! You will receive a confirmation email with your QR code(s) shortly." |
| `/payment/cancel?ref=HP-2026-00015` | User cancelled payment | "Payment was cancelled. Please try again." with a retry/back button |

The `ref` query param contains the registration reference number. Display it on the success page.

---

## Flow

```
┌─────────────────────────────────────┐
│  Registration Form                  │
│  (country, karyakarta, members)     │
│  User clicks "Pay"                  │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  FE calls POST /create-payment      │
│  Receives { reference, payment_url } │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  FE redirects to payment_url        │
│  window.location.href = payment_url │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Stripe Checkout Page               │
│  (Card / PayPal / other methods)    │
│  User completes payment             │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  Stripe redirects to                │
│  /payment/success?ref=HP-2026-00015 │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│  FE shows success message           │
│  "You will receive an email..."     │
└─────────────────────────────────────┘

  (Meanwhile, backend receives Stripe webhook,
   marks payment as paid, generates QR codes,
   and sends emails automatically)
```

---

## Pricing

- **€250 per member** (calculated server-side)
- FE can display the total (members.length * 250) but backend is the source of truth

---

## Important Notes

- **No Stripe.js or publishable key needed** — backend creates the checkout session, FE just redirects
- **Do NOT call `/register`** — use `/create-payment` instead (it handles registration + payment together)
- **Emails are sent automatically** after payment via webhook — FE does not trigger them
- **Payment methods (Card, PayPal)** are configured in Stripe Dashboard, not in code
- **Health check:** `GET /health` returns `{ "status": "ok" }`
