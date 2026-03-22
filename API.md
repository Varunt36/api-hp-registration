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

## GET `/health`

Health check endpoint.

### Response — `200 OK`

```json
{
  "status": "ok"
}
```
