## Frontend API Flow

The frontend makes 3 sequential Supabase inserts on form submission.

### Step 1 — Insert registration

```json
POST → registrations
{
  "country": "DE",
  "karyakarta": "Rajesh Patel",
  "member_count": 3,
  "terms_accepted": true
}
```

Returns: `{ id: "a3f2c1d0-...", reference: "YDS-2026-00042" }`

---

### Step 2 — Insert members (array)

```json
POST → members
[
  {
    "registration_id": "a3f2c1d0-...",
    "first_name": "Amit",
    "middle_name": "",
    "last_name": "Shah",
    "gender": "male",
    "dob": "1990-05-14",
    "email": "amit@example.com",
    "phone": "+49123456789"
  },
  {
    "registration_id": "a3f2c1d0-...",
    "first_name": "Priya",
    "middle_name": "R",
    "last_name": "Shah",
    "gender": "female",
    "dob": "1992-08-22",
    "email": "priya@example.com",
    "phone": null
  }
]
```

Returns: members with auto-generated `ticket_number` per row.

---

### Step 3 — Insert payment

```json
POST → payments
{
  "registration_id": "a3f2c1d0-...",
  "status": "pending",
  "amount": 104.00,
  "currency": "EUR",
  "payment_method": "stripe"
}
```

---

### Step 4 — Stripe/PayPal webhook updates payment

```json
PATCH → payments (where registration_id = "a3f2c1d0-...")
{
  "status": "paid",
  "transaction_id": "ch_3Pxyz...",
  "paid_at": "2026-08-10T14:30:00Z"
}
```
