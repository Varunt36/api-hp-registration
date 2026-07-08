"""
Fetch all members of ONE country from Supabase and send them the Google Form
link via Email (Resend).

The country is required (--country CODE, e.g. GB) so every send is a deliberate,
per-country roll-out — you can never accidentally email everyone. Only members
whose registration.country matches the given code are emailed and recorded.

No prefill — everyone gets the same plain form link.

Configuration comes from the shared pydantic Settings (app/core/config.py), so
every knob lives in the same .env as the API:
    FORM_URL                Override the Google Form link

Run from the repo root so `app` is importable:
    python -m scripts.send_form_non_germany --country GB --dry-run  # preview only
    python -m scripts.send_form_non_germany --country GB            # actually send
    python -m scripts.send_form_non_germany --country GB -v         # verbose console

Send tracking: every attempt is upserted into form_reminder_sends (run
sql/form_reminder_sends.sql once first), and members already marked 'sent' are
skipped on later runs — so re-running only reaches the unreached. A per-run CSV
receipt (send_report.csv) is written incrementally, one flushed row per member,
so even an interrupted run leaves a receipt. Emails are masked in the log file;
full addresses live only in the CSV. Both artifacts contain member data and are
gitignored — never commit them. Per-recipient failures are logged and recorded,
never aborting the whole run.
"""

import argparse
import csv
import html
import logging
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import resend

from app.core.config import BLUE_MIRAGE_FONT_URL, settings
from app.core.supabase import supabase

logger = logging.getLogger("send_form_non_germany")
LOG_FILE = "send_form_non_germany.log"
REPORT_FILE = "send_report.csv"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# The Google Form link attendees are asked to fill in — the public share link.
FORM_URL = settings.form_url

# The only delivery channel; stored on every form_reminder_sends row so the
# table can still distinguish channels if another is ever added back.
CHANNEL = "email"

# People shown in the email's "For any queries" section.
CONTACTS: list[tuple[str, str]] = [
    ("Nirmaan Mewada", "+49 176 74715077"),
    ("Varun Thaker", "+49 176 85645884"),
]

EMAIL_SUBJECT = "Travel & Accommodation details — HariPrabodham Amrut Mahotsav Germany 2026"
resend.api_key = settings.resend_api_key

SEND_DELAY_SECONDS = 1.0

# PostgREST silently caps unpaginated selects at the server's max-rows
# (1000 by default on Supabase), so all fetches page through .range().
SUPABASE_PAGE_SIZE = 1000

# A single `.in_(...)` filter is serialised into the query string, so a huge id
# list would blow past PostgREST's URL length limit — prior sends are looked up
# in chunks of this size.
PRIOR_LOOKUP_CHUNK = 200

_TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "app", "templates", "form_reminder_email.html"
)
try:
    with open(_TEMPLATE_PATH, encoding="utf-8") as _f:
        _EMAIL_TEMPLATE = _f.read()
except OSError as exc:  # missing/unreadable template is a hard config error
    raise RuntimeError(f"Could not load email template {_TEMPLATE_PATH}: {exc}") from exc


# ---------------------------------------------------------------------------
# Domain
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Member:
    member_id: str
    email: str
    full_name: str
    country: str


class Outcome(str, Enum):
    SKIPPED = "skipped"
    OK = "OK"
    FAILED = "FAILED"


@dataclass(frozen=True)
class SendResult:
    outcome: Outcome
    detail: str = ""  # failure reason, or why the send was skipped

    def render(self) -> str:
        """Display/CSV string: 'OK', 'skipped (why)', 'FAILED: <reason>'."""
        if self.outcome is Outcome.FAILED:
            return f"FAILED: {self.detail}"
        if self.outcome is Outcome.SKIPPED and self.detail:
            return f"skipped ({self.detail})"
        return self.outcome.value


def _mask_email(email: str) -> str:
    """a***@example.com for logs — mirrors app.services.email_service._mask_email
    (not imported: that module eagerly loads unrelated email assets)."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def _csv_cell(value: str) -> str:
    """Neutralise spreadsheet formula injection: names/emails are user input, and
    a leading =, +, - or @ would execute as a formula when opened in Excel."""
    return "'" + value if value[:1] in "=+-@" else value


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------

def _fetch_all(build_query: Callable[[], Any]) -> list[dict]:
    """Drain a PostgREST query page by page (see SUPABASE_PAGE_SIZE).

    `build_query` returns a fresh supabase select builder each call — builders
    are single-use, so the same query must be rebuilt for every page.
    """
    rows: list[dict] = []
    while True:
        start = len(rows)
        page = build_query().range(start, start + SUPABASE_PAGE_SIZE - 1).execute().data
        rows.extend(page)
        if len(page) < SUPABASE_PAGE_SIZE:
            return rows


def fetch_members_by_country(country: str) -> list[Member]:
    """All members whose registration.country == `country`, deduped by email.

    Rows are ordered by id so the dedupe picks the same member on every run;
    within one shared email (family registrations) the first row wins. The
    other family members are intentionally not contacted separately — one form
    link per email address.
    """
    logger.info("Fetching members for country %s from Supabase...", country)
    try:
        rows = _fetch_all(lambda: (
            supabase.table("members")
            # Inner join members -> registrations, filtering on the embedded country.
            .select("id, first_name, last_name, email, registrations!inner(country)")
            .eq("registrations.country", country)
            .order("id")
        ))
    except Exception as exc:
        raise RuntimeError(f"Supabase query for members failed: {exc}") from exc
    logger.debug("Supabase returned %d member row(s) before dedupe.", len(rows))

    members: dict[str, Member] = {}  # keyed by lowercased email to dedupe
    for r in rows:
        email = (r.get("email") or "").strip()
        if not email:
            continue
        key = email.lower()
        if key in members:  # first row per email wins (ordered by id)
            continue
        members[key] = Member(
            member_id=r["id"],
            email=email,
            # join+split collapses inner whitespace/newlines a validator missed.
            full_name=" ".join(f"{r.get('first_name') or ''} {r.get('last_name') or ''}".split()),
            country=(r.get("registrations") or {}).get("country", ""),
        )

    return sorted(members.values(), key=lambda m: m.full_name.lower())


def fetch_prior_sends(member_ids: list[str]) -> dict[str, dict]:
    """Prior email-channel form_reminder_sends for exactly this run's members,
    keyed by member_id. Scoping to the recipients (and channel) keeps the lookup
    cheap no matter how large the cross-campaign log grows. The UNIQUE
    (member_id, channel) constraint guarantees at most one row per member here.
    """
    prior: dict[str, dict] = {}
    for start in range(0, len(member_ids), PRIOR_LOOKUP_CHUNK):
        chunk = member_ids[start:start + PRIOR_LOOKUP_CHUNK]
        try:
            rows = (
                supabase.table("form_reminder_sends")
                .select("member_id, status, attempts")
                .eq("channel", CHANNEL)
                .in_("member_id", chunk)
                .execute()
                .data
            )
        except Exception as exc:
            raise RuntimeError(
                "Could not read form_reminder_sends — did you run "
                f"sql/form_reminder_sends.sql in Supabase? ({exc})"
            ) from exc
        for r in rows:
            prior[r["member_id"]] = r
    return prior


def fetch_sent_emails(emails: list[str]) -> set[str]:
    """Lowercased email addresses already marked 'sent', looked up by ADDRESS
    (not member_id). The same person can appear under several member rows —
    duplicate registrations, or one address shared across countries — so keying
    the skip on the address is what actually guarantees nobody is emailed twice.
    """
    sent: set[str] = set()
    # De-dupe + lowercase before querying; the DB stores the address as sent, so
    # exact case is what we match, but we compare case-insensitively downstream.
    unique = sorted({e.strip() for e in emails if e.strip()})
    for start in range(0, len(unique), PRIOR_LOOKUP_CHUNK):
        chunk = unique[start:start + PRIOR_LOOKUP_CHUNK]
        try:
            rows = (
                supabase.table("form_reminder_sends")
                .select("email")
                .eq("channel", CHANNEL)
                .eq("status", "sent")
                .in_("email", chunk)
                .execute()
                .data
            )
        except Exception as exc:
            raise RuntimeError(
                "Could not read form_reminder_sends — did you run "
                f"sql/form_reminder_sends.sql in Supabase? ({exc})"
            ) from exc
        for r in rows:
            sent.add((r.get("email") or "").strip().lower())
    return sent


def record_send(member: Member, result: SendResult, prior: dict[str, dict]) -> None:
    """Upsert this attempt into form_reminder_sends so later runs skip the
    member. A tracking failure is logged but never aborts the run."""
    now = datetime.now(timezone.utc).isoformat()
    previous = prior.get(member.member_id)
    sent = result.outcome is Outcome.OK
    row = {
        "member_id": member.member_id,
        "email": member.email,
        "full_name": member.full_name,
        "channel": CHANNEL,
        "status": "sent" if sent else "failed",
        "error_detail": result.detail or None,
        "form_url": FORM_URL,
        "attempts": (previous["attempts"] if previous else 0) + 1,
        "sent_at": now if sent else None,
        "last_attempt_at": now,
    }
    try:
        supabase.table("form_reminder_sends").upsert(row, on_conflict="member_id,channel").execute()
    except Exception as exc:
        logger.warning("Could not record send for %s: %s", _mask_email(member.email), exc)


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def _contacts_html() -> str:
    """Render the CONTACTS list into the rows injected at {{CONTACTS}}."""
    rows = []
    for name, phone in CONTACTS:
        tel = re.sub(r"[^\d+]", "", phone)  # tel: link — digits and leading '+'
        rows.append(
            '<p style="margin:3px 0; text-align:center; font-size:13px; '
            'line-height:1.6; color:#4a2872;">'
            f'<span style="font-weight:700;">{html.escape(name)}</span> '
            f'&mdash; <a href="tel:{tel}" style="color:#6b3fa0; '
            f'text-decoration:none; font-weight:600;">{html.escape(phone)}</a></p>'
        )
    return "\n".join(rows)


# Constant placeholders are rendered once; only {{MEMBER_NAME}} varies per
# recipient. The font URL is substituted raw: it sits inside <style>, an HTML
# raw-text context where entities are never decoded, so html-escaping would
# corrupt any '&' the signed URL may gain in the future.
_BASE_EMAIL_HTML = (
    _EMAIL_TEMPLATE
    .replace("{{BLUE_MIRAGE_FONT_URL}}", BLUE_MIRAGE_FONT_URL)
    .replace("{{FORM_URL}}", html.escape(FORM_URL))
    .replace("{{CONTACTS}}", _contacts_html())
)


def send_email(member: Member) -> None:
    body = _BASE_EMAIL_HTML.replace("{{MEMBER_NAME}}", html.escape(member.full_name))
    resend.Emails.send({
        "from": settings.resend_from_email,
        "to": [member.email],
        "subject": EMAIL_SUBJECT,
        "html": body,
    })


def send_to_member(member: Member, sent_emails: set[str]) -> SendResult:
    """Skip if this address was already emailed, else send and convert any
    exception into a FAILED result — a single recipient's failure must never
    abort the whole run. The skip is keyed on the email address (see
    fetch_sent_emails) so nobody is contacted twice. The short reason is kept on
    the result (and CSV); the full traceback goes to the log file at DEBUG.
    """
    if member.email.lower() in sent_emails:
        return SendResult(Outcome.SKIPPED, "already sent")
    try:
        send_email(member)
        logger.info("email -> %s: OK", _mask_email(member.email))
        return SendResult(Outcome.OK)
    except Exception as exc:
        logger.warning("email -> %s: FAILED: %s", _mask_email(member.email), exc)
        logger.debug("Traceback for email send", exc_info=True)
        return SendResult(Outcome.FAILED, str(exc))


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _configure_logging(verbose: bool) -> None:
    """Console at INFO (or DEBUG with --verbose) plus a DEBUG log file that
    always captures full tracebacks, so a failed run stays diagnosable."""
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(fmt)
    logger.addHandler(console)

    try:
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError as exc:  # e.g. read-only dir — keep going with console only
        logger.warning("Could not open log file %s: %s (console logging only)", LOG_FILE, exc)


def _print_dry_run(members: list[Member], sent_emails: set[str]) -> None:
    """Full member details are shown here on purpose — verifying the recipient
    list is the point of a dry run — and both log targets stay local/gitignored."""
    for m in members:
        already = "  [already sent — will skip]" if m.email.lower() in sent_emails else ""
        logger.info("  %s | %s | %s%s", m.full_name, m.email, m.country, already)
    logger.info("Form link: %s", FORM_URL)
    logger.info("Dry run — nothing sent.")


def _run(args: argparse.Namespace) -> None:
    members = fetch_members_by_country(args.country)
    if not members:
        logger.info("No members found for country %s — nothing to do.", args.country)
        return
    prior = fetch_prior_sends([m.member_id for m in members])
    sent_emails = fetch_sent_emails([m.email for m in members])
    logger.info("Found %d member(s) in %s; %d already emailed (will skip), "
                "%d prior send record(s).",
                len(members), args.country, len(sent_emails), len(prior))

    if args.dry_run:
        _print_dry_run(members, sent_emails)
        return

    logger.info("Sending to %s with %.1fs delay between recipients.",
                args.country, SEND_DELAY_SECONDS)

    failed_members = 0
    with open(REPORT_FILE, "w", newline="", encoding="utf-8") as report:
        writer = csv.DictWriter(
            report, fieldnames=["name", "email", "country", "status"], delimiter=";",
        )
        writer.writeheader()
        for i, member in enumerate(members, start=1):
            logger.info("[%d/%d] %s <%s>", i, len(members),
                        member.full_name, _mask_email(member.email))
            result = send_to_member(member, sent_emails)

            if result.outcome is not Outcome.SKIPPED:
                record_send(member, result, prior)
                if result.outcome is Outcome.OK:
                    # Guard against re-sending to the same address later in this
                    # same run, independent of the upfront recipient de-dupe.
                    sent_emails.add(member.email.lower())
                elif result.outcome is Outcome.FAILED:
                    failed_members += 1

            writer.writerow({
                "name": _csv_cell(member.full_name),
                "email": _csv_cell(member.email),
                "country": member.country,
                "status": result.render(),
            })
            report.flush()  # a row survives even if the run is interrupted

            # Pace the external API — but only when we actually hit it (skipped
            # already-sent members cost no call, so no need to wait on them).
            if result.outcome is not Outcome.SKIPPED and i < len(members):
                time.sleep(SEND_DELAY_SECONDS)

    logger.info("Done. %d processed, %d with failure(s). Report: %s",
                len(members), failed_members, REPORT_FILE)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send the form link to all members of one country.")
    parser.add_argument("--country", required=True,
                        help="Country code to target, e.g. GB. Only members whose "
                             "registration.country matches are emailed and recorded.")
    parser.add_argument("--dry-run", action="store_true", help="Preview recipients, send nothing.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose (DEBUG) console output.")
    args = parser.parse_args()

    args.country = args.country.strip().upper()  # DB stores codes uppercase (GB, US, IN)
    if not args.country:
        parser.error("--country must not be empty")

    _configure_logging(args.verbose)
    try:
        _run(args)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user — aborting. Rows already written to "
                       "%s and form_reminder_sends remain valid.", REPORT_FILE)
        sys.exit(130)
    except Exception:
        logger.exception("Fatal error — aborting.")
        sys.exit(1)


if __name__ == "__main__":
    main()
