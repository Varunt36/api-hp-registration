# Pre-Launch Checklist

## 1. Database Migrations

Run these in **Supabase Dashboard → SQL Editor** (in order):

```sql
-- If not already run:
-- sql/create_table.sql (full schema: registrations, members, payments, country_quotas)

-- Migration 003: Add email tracking to payments
ALTER TABLE payments ADD COLUMN emails_sent BOOLEAN DEFAULT NULL;
```

Verify tables exist: `registrations`, `members`, `payments`, `country_quotas`

---

## 2. Production Environment Variables (.env)

```env
# ── Supabase ──
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=eyJhbG...              # Settings → API → service_role key

# ── Email (Resend) ──
RESEND_API_KEY=re_xxxxxxxx                   # resend.com/api-keys
RESEND_FROM_EMAIL=noreply@yourdomain.com     # Must be verified domain in Resend

# ── App ──
FRONTEND_URL=https://your-frontend-domain.com  # Production frontend URL
DEBUG=false                                     # MUST be false in production

# ── Stripe (LIVE keys) ──
STRIPE_SECRET_KEY=sk_live_xxxxxxxx            # dashboard.stripe.com/apikeys (LIVE mode)
STRIPE_WEBHOOK_SECRET=whsec_xxxxxxxx          # From Stripe webhook endpoint (Step 3)

# ── Email Images (host on Supabase Storage or CDN) ──
EMAIL_BANNER_URL=https://your-cdn/banner.png
EMAIL_LOGO_URL=https://your-cdn/logo.png

# ── Social Links (sent in email after payment) ──
WHATSAPP_GROUP_URL=https://chat.whatsapp.com/your-group
TELEGRAM_GROUP_URL=https://t.me/+IT1zhtSm-HA3Y2Yy
INSTAGRAM_URL=https://instagram.com/your-page
YOUTUBE_URL=https://youtube.com/your-channel
```

---

## 3. Stripe Live Webhook Setup

1. Go to **[Stripe Dashboard → Developers → Webhooks](https://dashboard.stripe.com/webhooks)** (make sure you're in **LIVE** mode, not test)
2. Click **"Add endpoint"**
3. Set:
   - **Endpoint URL:** `https://your-api-domain.com/webhooks/stripe`
   - **Events to listen:** `checkout.session.completed`
4. After creating, copy the **Signing secret** (`whsec_...`)
5. Paste into `.env` as `STRIPE_WEBHOOK_SECRET`

---

## 4. Stripe Payment Methods

1. Go to **[Stripe Dashboard → Settings → Payment methods](https://dashboard.stripe.com/settings/payment_methods)**
2. Enable the methods you want:
   - [x] Card (Visa, Mastercard, Amex)
   - [x] PayPal (if needed)

---

## 5. Domain & CORS

- [ ] `FRONTEND_URL` in `.env` matches your actual frontend domain exactly
- [ ] Frontend is deployed and accessible
- [ ] Frontend has routes: `/payment/success` and `/payment/cancel`
- [ ] HTTPS is enabled on both frontend and backend

---

## 6. Country Quotas

Verify quotas in Supabase → Table Editor → `country_quotas`:

| Country | Max Members |
|---------|-------------|
| DE | 100 |
| AT | 50 |
| CH | 50 |
| GB | 30 |
| US | 20 |
| IN | 30 |
| NZ | 20 |

Update as needed:
```sql
UPDATE country_quotas SET max_members = 200 WHERE country_code = 'DE';
```

---

## 7. Email Templates

- [ ] Banner image uploaded and URL set in `EMAIL_BANNER_URL`
- [ ] Logo image uploaded and URL set in `EMAIL_LOGO_URL`
- [ ] WhatsApp QR image uploaded and URL set in `WHATSAPP_QR_URL`
- [ ] Telegram QR image uploaded and URL set in `TELEGRAM_QR_URL`
- [ ] Resend domain verified (SPF, DKIM, DMARC configured)
- [ ] Test email delivery (check spam folder)

---

## 8. Security Checks

- [ ] `DEBUG=false` in production `.env`
- [ ] `.env` is NOT committed to git (`git status` should not show it)
- [ ] All API keys are **live** keys (not `sk_test_`, `re_test_`, etc.)
- [ ] Stripe webhook secret is from the **live** webhook endpoint
- [ ] HTTPS enforced on backend (HSTS header auto-enabled when DEBUG=false)
- [ ] Rate limiting active (5 requests/min per IP on `/create-payment`)

---

## 9. Deployment

### Option A: Docker
```bash
docker-compose up --build -d
```

### Option B: Direct
```bash
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Verify deployment:
```bash
curl https://your-api-domain.com/health
# Expected: {"status":"ok"}
```

---

## 10. Post-Deployment Smoke Test

### Test 1: Health check
```bash
curl https://your-api-domain.com/health
# ✅ {"status":"ok"}
```

### Test 2: Create a real payment
```bash
curl -X POST https://your-api-domain.com/create-payment \
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
# ✅ {"payment_url":"https://checkout.stripe.com/..."}
```

### Test 3: Complete payment
1. Open the `payment_url` in browser
2. Pay with a real card (this is LIVE mode — you'll be charged €250)
3. Verify:
   - [ ] Redirected to `/payment/success` page
   - [ ] Registration email received with QR code
   - [ ] Travel guide email received
   - [ ] Social links email received
   - [ ] Supabase: `registrations` table has new row
   - [ ] Supabase: `members` table has member row
   - [ ] Supabase: `payments` table has row with `status=paid`
4. Refund the test payment in Stripe Dashboard → Payments → click payment → Refund

---

## 11. Monitoring

After launch, monitor:
- **Stripe Dashboard:** Payment success/failure rates
- **Server logs:** Errors in webhook processing, email failures
- **Supabase:** `payments` table → check for `emails_sent=false` (failed email delivery)

### Query to find failed emails (run in Supabase SQL Editor):
```sql
SELECT p.*, r.reference
FROM payments p
JOIN registrations r ON r.id = p.registration_id
WHERE p.status = 'paid' AND (p.emails_sent = false OR p.emails_sent IS NULL);
```

---

## Quick Reference: API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/countries` | GET | List allowed countries from DB (FE source of truth) |
| `/create-payment` | POST | Create registration + Stripe session |
| `/register` | POST | Validate registration data only (no DB) |
| `/webhooks/stripe` | POST | Stripe webhook (called by Stripe, not FE) |
| `/docs` | GET | Swagger docs (DEBUG=true only) |
