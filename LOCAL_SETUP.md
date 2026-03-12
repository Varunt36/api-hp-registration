# Local Setup Guide

## Prerequisites

- Python 3.9+
- Docker Desktop (optional, recommended for Windows)
- Stripe CLI
- Supabase project (free tier works)
- Resend account (for emails)
- Stripe account (test mode)

### Installing Stripe CLI

| OS | Command |
|----|---------|
| **macOS** | `brew install stripe/stripe-cli/stripe` |
| **Windows** | `scoop install stripe` or download from [github.com/stripe/stripe-cli/releases](https://github.com/stripe/stripe-cli/releases) |
| **Linux** | `curl -s https://packages.stripe.dev/api/security/keypair/stripe-cli-gpg/public | gpg --dearmor \| sudo tee /usr/share/keyrings/stripe.gpg` then `apt install stripe` |

---

## Option A: Without Docker (macOS / Linux / Windows)

### 1. Clone & Install

**macOS / Linux:**
```bash
git clone <repo-url>
cd api-hp-registration

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

**Windows (PowerShell):**
```powershell
git clone <repo-url>
cd api-hp-registration

python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Environment Setup

**macOS / Linux:**
```bash
cp .env.example .env
```

**Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

Edit `.env` with your credentials:

```env
# Supabase (get from: Supabase Dashboard → Settings → API)
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJhbG...

# Email (get from: resend.com/api-keys)
RESEND_API_KEY=re_xxxxxxxx
RESEND_FROM_EMAIL=noreply@yourdomain.com

# Frontend URL (default for Vite)
FRONTEND_URL=http://localhost:5173

# Stripe (get from: dashboard.stripe.com/test/apikeys)
STRIPE_SECRET_KEY=sk_test_xxxxxxxx
STRIPE_WEBHOOK_SECRET=whsec_xxxxxxxx   # from stripe listen (Step 5)

# Pricing
PAYMENT_AMOUNT_PER_MEMBER=250.00
```

### 3. Database Setup

Run the SQL schema in **Supabase Dashboard → SQL Editor**:

Copy contents of `sql/create_table.sql` and execute in Supabase SQL Editor.

This creates: `registrations`, `members`, `payments`, `country_quotas` tables.

### 4. Start the Server

**macOS / Linux:**
```bash
cd api-hp-registration
source venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

**Windows (PowerShell):**
```powershell
cd api-hp-registration
venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```

Verify: open `http://localhost:8000/health` in browser → `{"status":"ok"}`

### 5. Start Stripe Webhook Listener

In a **separate terminal** (works the same on all OS):

```bash
stripe login                # first time only — opens browser to authorize
stripe listen --forward-to localhost:8000/webhooks/stripe
```

It prints:
```
Ready! Your webhook signing secret is whsec_abc123...
```

**Copy that `whsec_...` value into your `.env`** as `STRIPE_WEBHOOK_SECRET`, then restart the server.

---

## Option B: With Docker (Recommended for Windows)

### 1. Install Docker Desktop

Download from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) and install.

### 2. Clone & Setup `.env`

```powershell
git clone <repo-url>
cd api-hp-registration
Copy-Item .env.example .env
```

Edit `.env` with your credentials (same as Option A, Step 2).

### 3. Database Setup

Same as Option A, Step 3 — run `sql/create_table.sql` in Supabase SQL Editor.

### 4. Start the Server

```bash
docker-compose up --build
```

Server runs at `http://localhost:8000`.

### 5. Start Stripe Webhook Listener

In a **separate terminal** (outside Docker):

```bash
stripe login
stripe listen --forward-to localhost:8000/webhooks/stripe
```

Copy the `whsec_...` into `.env`, then restart:

```bash
docker-compose down
docker-compose up
```

---

## 6. Test the Full Flow

### Create a payment:

**macOS / Linux:**
```bash
curl -X POST http://localhost:8000/create-payment \
  -H "Content-Type: application/json" \
  -d '{
    "payment_method": "stripe",
    "country": "DE",
    "karyakarta": "Test Leader",
    "terms_accepted": true,
    "members": [
      {
        "first_name": "Test",
        "last_name": "User",
        "gender": "male",
        "dob": "1995-01-15",
        "email": "your-email@example.com"
      }
    ]
  }'
```

**Windows (PowerShell):**
```powershell
Invoke-RestMethod -Uri http://localhost:8000/create-payment -Method POST -ContentType "application/json" -Body '{
  "payment_method": "stripe",
  "country": "DE",
  "karyakarta": "Test Leader",
  "terms_accepted": true,
  "members": [
    {
      "first_name": "Test",
      "last_name": "User",
      "gender": "male",
      "dob": "1995-01-15",
      "email": "your-email@example.com"
    }
  ]
}'
```

Response:
```json
{
  "reference": "HP-2026-00001",
  "payment_url": "https://checkout.stripe.com/c/pay/cs_test_..."
}
```

### Complete the payment:

1. Open the `payment_url` in your browser
2. Pay with test card: `4242 4242 4242 4242` (any future expiry, any CVC)
3. Watch the `stripe listen` terminal — you should see `checkout.session.completed [200]`
4. Check your email — you should receive registration confirmation + travel guide

### Verify in database:

Check Supabase Dashboard → Table Editor:
- `registrations` — new row with reference
- `members` — member rows linked to registration
- `payments` — status should be `"paid"` with `transaction_id` and `paid_at`

---

## Stripe Test Cards

| Card Number | Result |
|-------------|--------|
| `4242 4242 4242 4242` | Payment succeeds |
| `4000 0000 0000 3220` | 3D Secure authentication required |
| `4000 0000 0000 0002` | Payment declined |

Use any future expiry date and any 3-digit CVC.

---

## API Docs

When `DEBUG=True` (default), Swagger docs are available at:
- http://localhost:8000/docs
- http://localhost:8000/redoc

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Server hangs (macOS/Linux) | `lsof -ti :8000 \| xargs kill` then restart |
| Server hangs (Windows) | `netstat -ano \| findstr :8000` → `taskkill /PID <pid> /F` then restart |
| `ModuleNotFoundError: No module named 'app'` | Make sure you're in the `api-hp-registration` directory |
| `ModuleNotFoundError: stripe` | Run `pip install stripe` in your venv |
| Webhook returns 400 | Check `STRIPE_WEBHOOK_SECRET` matches the one from `stripe listen` |
| No emails received | Check `RESEND_API_KEY` and `RESEND_FROM_EMAIL` in `.env` |
| Country quota error | Check `country_quotas` table in Supabase |
| Docker port conflict | Stop other services on port 8000 first |
