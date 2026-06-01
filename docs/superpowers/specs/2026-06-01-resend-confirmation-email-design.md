# Resend Confirmation Email — Design

- **Date:** 2026-06-01
- **Status:** Approved (pending spec review)
- **Author:** Nisarg Mewada (with Claude)
- **Repos affected:** `BE/api-hp-registration` (FastAPI), `FE/hp-landing-page` (React SPA)

## 1. Problem

Registrants who delete their confirmation email by mistake currently have **no way to get it back**. There is no resend mechanism anywhere in the system. We need an easy, safe way for an admin to resend the original confirmation (with QR code[s]) to a registrant.

## 2. Goal & non-goals

**Goal:** An admin can enter a registrant's email and resend the **exact** confirmation email that address originally received — same template, same QR code(s).

**Non-goals (deliberately out of scope):**
- No public / self-service resend page.
- No resend audit-log table (server logs already record every send).
- No QR image storage — QR codes regenerate deterministically from the ticket number.
- No change to the existing email template, QR logic, or payment flow.
- Not fixing the pre-existing `payments.emails_sent` column that is referenced in `payment_service.py:172` but missing from `sql/create_table.sql`. Noted, but separate.

## 3. Key facts about the current system (why this is easy)

- Emails are sent by `send_combined_qr_email()` (`app/services/email_service.py`), orchestrated by `process_qr_and_emails()` (`app/services/registration_service.py`). This runs today only as a post-payment background task.
- **QR generation is deterministic:** `qrcode.make(ticket_number)` (`app/services/qr_service.py:8`). The same ticket number always produces a byte-identical QR. QR images are **not** stored (`members.qr_url` is unused); they are regenerated on every send. A resend therefore reuses the same code path and is byte-identical to the original.
- **All recipient emails live in the `members` table.** The "primary" recipient is simply the first member's email (`data.members[0].email`, `payment_service.py:170`). There is no separate contact field.
- Original recipient logic (`registration_service.py:108-110`):
  ```python
  recipients = [(primary_email, all_qrs)] + [
      (q["email"], [q]) for q in all_qrs if q["email"] and q["email"] != primary_email
  ]
  ```
  i.e. the **lead member** receives the combined email (all members' QR cards); each **secondary member with a distinct email** receives only their own card.
- **The FE already has real admin auth via Supabase Auth.** Admins sign in at `/admin/login` (`supabase.auth.signInWithPassword`), and `/admin/scan` is behind `ProtectedRoute`. There is no public signup. Every admin carries a Supabase JWT in their session.
- The FE already reads `members` / `registrations` / `payments` directly via the Supabase JS client (anon key + RLS + the admin's authenticated session) — see `src/api/admin.ts`. We reuse this pattern for verification.

## 4. Architecture decisions (approved)

| Decision | Choice |
|---|---|
| Trigger | Admin-only (no public self-service) |
| Backend auth | Verify the admin's existing Supabase JWT (`Authorization: Bearer <token>`). No new shared secret. |
| Lookup / verification | Done **on the FE**, querying Supabase directly. Backend stays minimal. |
| Recipient | **Only the entered email.** Never an arbitrary/redirected address. |
| Resent content | Exactly what that address originally received: combined all-members email if it is the lead member's address; the individual card if it is a secondary member's address. |
| QR / template / payment code | **Unchanged** — reused verbatim. |
| Schema changes | **None.** |

## 5. Frontend design — new "Resend Email" tab

Location: `FE/hp-landing-page/src/pages/admin/AdminScan.tsx` (adds a third tab next to **Scanner** and **Dashboard**).

**UI:**
- A single email input.
- **Auto-verification against the registered emails** as the admin types (debounced ~400ms) or on a "Verify" action: the FE queries the `members` table via the Supabase client (admin is authenticated; reuses the `src/api/admin.ts` pattern). It joins to `registrations`/`payments` to confirm the registration is paid.
  - **Match found** → inline confirmation: `✓ HP-2026-00042 · <Lead name> (+N) · <Country> · Paid`. Enables the **Resend** button.
  - **No match** → `✗ No registration found for this email.` Resend button disabled.
  - **Multiple registrations for one email** → list them; admin selects which to resend (button disabled until one is chosen).
- **Resend** button → `POST {VITE_API_URL}/resend-confirmation` with body `{ "email": "<entered email>" }` and header `Authorization: Bearer ${session.access_token}` (from `supabase.auth.getSession()`).
- Result → MUI success toast (`Resent to <email>`) or error toast (maps backend error message).

**New / changed FE files:**
- `src/pages/admin/AdminScan.tsx` — add the tab + panel.
- `src/api/` — add `resendConfirmation(email, token)` (backend call) and a Supabase verification query helper (alongside `admin.ts`).

## 6. Backend design — new `POST /resend-confirmation`

A new lightweight router. The backend's only job is to **authenticate and send**; it does its own safety re-check but does not power the FE autocomplete.

**Auth dependency (`get_current_admin`):**
- Read `Authorization: Bearer <token>`.
- Verify via `supabase.auth.get_user(token)`. Missing/invalid/expired → `401 Unauthorized`.
- Because there is no public signup, a valid Supabase session = an admin. (Optional future hardening: check the user's email against an allowlist.)

**Request:** `{ "email": "user@example.com", "reference": "HP-2026-00042" }` — `reference` is **optional**; it is required only to disambiguate when the email matches more than one registration.

**Logic:**
1. Normalize the email (trim, lowercase for comparison).
2. Look up `members` rows whose `email` matches. None → `404 {"message": "No registration found for this email."}`.
3. Resolve the `registration_id`:
   - If `reference` was supplied, use that registration (and verify the entered email actually belongs to it → else `404`).
   - Else if the email maps to exactly one registration, use it.
   - Else (email maps to **multiple** registrations and no `reference` given) → `409` with the candidate list `{reference, lead_name, member_count, country}`. The FE shows the choices and re-calls with the chosen `reference`.
4. Confirm the registration is **paid** (join `payments`, `status = 'paid'`). Not paid → `404`.
5. Load all members for the registration (ordered by `ticket_number`), regenerate QR bytes per member (same as `process_qr_and_emails`).
6. Rebuild the original recipient tuples and **filter to the entered email only**:
   ```python
   primary_email = members[0]["email"]
   recipients = [(primary_email, all_qrs)] + [
       (q["email"], [q]) for q in all_qrs if q["email"] and q["email"] != primary_email
   ]
   targets = [(to, qrs) for (to, qrs) in recipients if to.lower() == entered_email.lower()]
   ```
7. For each target, call the existing `send_combined_qr_email(to, qrs, reference)`. Count successes.
8. **Response:** `200 {"sent": <int>, "reference": "HP-2026-00042"}`.

**Rate limiting:** apply a light `slowapi` cap (e.g. a few/minute per IP) as defense-in-depth, even though the endpoint is JWT-gated.

**New / changed BE files:**
- `app/routers/resend.py` (or add to an existing admin router) — the endpoint + `get_current_admin` dependency.
- `app/main.py` — register the new router.
- A small lookup helper in `app/services/registration_service.py` (find members by email, build targets) — reuses existing `generate_qr_image` / `send_combined_qr_email` with **no change** to those functions.

## 7. Security considerations

- **JWT verified server-side** — FE hiding the tab is not the security boundary; the endpoint independently authenticates.
- **Recipient is constrained to a registered, paid email** the backend itself re-resolves from the DB. The caller cannot redirect a QR pass to an arbitrary address, so even if auth were bypassed the blast radius is "spam a real registrant's inbox," not pass theft.
- **Rate-limited** to blunt enumeration/spam.
- Reuses `_safe()` header-injection defenses already in `send_combined_qr_email`.

## 8. Testing plan

**Backend (pytest):**
- 401 when no / invalid bearer token.
- 404 for an unknown email; 404 for an email tied only to a non-paid registration.
- 200 + `sent == 1` for a lead-member email → combined email built (assert recipient + member count in the mocked `send_combined_qr_email`).
- 200 + `sent == 1` for a secondary-member email → only that member's card.
- 409 + candidate list when an email maps to multiple registrations.
- Resend is repeatable (no idempotency lock) and does not mutate DB state.

**Frontend (manual / component):**
- Verify-as-you-type shows found/not-found correctly.
- Resend button disabled until a valid single match is selected.
- Success and error toasts render; bearer token attached to the request.

## 9. Open questions

None blocking. Optional future items: admin allowlist on the JWT check; a resend audit log if compliance ever needs it.
