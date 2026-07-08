"""
Fetch all NON-German members from Supabase and send them the Google Form link
via Email (Resend).

No prefill — everyone gets the same plain form link.

Configuration comes from the shared pydantic Settings (app/core/config.py), so
every knob lives in the same .env as the API:
    FORM_URL                Override the Google Form link

Run from the repo root so `app` is importable:
    python -m scripts.send_form_non_germany --dry-run   # preview only, sends nothing
    python -m scripts.send_form_non_germany             # actually send
    python -m scripts.send_form_non_germany -v          # verbose (DEBUG) console

Send tracking: every attempt is upserted into form_reminder_sends (run
sql/form_reminder_sends.sql once first), and members already marked 'sent' on
a channel are skipped on later runs — so re-running only reaches the
unreached. A per-run CSV receipt (send_report.csv) is written incrementally,
one flushed row per member, so even an interrupted run leaves a receipt.
Emails are masked in the log file; full addresses live only in the CSV.
Both artifacts contain member data and are gitignored — never commit them.
Per-recipient failures are logged and recorded, never aborting the whole run.
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

# Country code that counts as "German" and is therefore EXCLUDED.
GERMAN_COUNTRY_CODE = "DE"

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
class ChannelResult:
    outcome: Outcome
    detail: str = ""  # failure reason, or why the channel was skipped

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
    """Neutralise spreadsheet formula injection: names are user input, and a
    leading =, +, - or @ would execute as a formula when opened in Excel."""
    return "'" + value if value[:1] in "=+-@" else value


def _run_channel(channel: str, member: Member, send: Callable[[Member], None]) -> ChannelResult:
    """Run one send, converting any exception into a FAILED result.

    Never raises — a single recipient's failure must not abort the whole run.
    The short reason is kept on the result (and CSV); the full traceback goes
    to the log file at DEBUG so nothing is lost.
    """
    try:
        send(member)
        logger.info("%s -> %s: OK", channel, _mask_email(member.email))
        return ChannelResult(Outcome.OK)
    except Exception as exc:
        logger.warning("%s -> %s: FAILED: %s", channel, _mask_email(member.email), exc)
        logger.debug("Traceback for %s send", channel, exc_info=True)
        return ChannelResult(Outcome.FAILED, str(exc))


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


def fetch_non_german_members() -> list[Member]:
    """All members whose registration.country != 'DE', deduped by email.

    Rows are ordered by id so the dedupe picks the same member on every run;
    within one shared email (family registrations) the first row wins. The
    other family members are intentionally not contacted separately — one form
    link per email address.
    """
    logger.info("Fetching non-German members from Supabase...")
    try:
        rows = _fetch_all(lambda: (
            supabase.table("members")
            # Inner join members -> registrations, filtering on the embedded country.
            .select("id, first_name, last_name, email, registrations!inner(country)")
            .neq("registrations.country", GERMAN_COUNTRY_CODE)
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


def fetch_prior_sends() -> dict[tuple[str, str], dict]:
    """Existing form_reminder_sends rows keyed by (member_id, channel), used
    to skip already-sent members and to carry the attempts counter forward."""
    try:
        rows = _fetch_all(lambda: (
            supabase.table("form_reminder_sends")
            .select("member_id, channel, status, attempts")
            .order("id")
        ))
    except Exception as exc:
        raise RuntimeError(
            "Could not read form_reminder_sends — did you run "
            f"sql/form_reminder_sends.sql in Supabase? ({exc})"
        ) from exc
    return {(r["member_id"], r["channel"]): r for r in rows}


def record_send(member: Member, channel: str, result: ChannelResult,
                prior: dict[tuple[str, str], dict]) -> None:
    """Upsert this attempt into form_reminder_sends so later runs skip the
    member. A tracking failure is logged but never aborts the run."""
    now = datetime.now(timezone.utc).isoformat()
    previous = prior.get((member.member_id, channel))
    row = {
        "member_id": member.member_id,
        "email": member.email,
        "full_name": member.full_name,
        "channel": channel,
        "status": "sent" if result.outcome is Outcome.OK else "failed",
        "error_detail": result.detail or None,
        "form_url": FORM_URL,
        "attempts": (previous["attempts"] if previous else 0) + 1,
        "sent_at": now if result.outcome is Outcome.OK else None,
        "last_attempt_at": now,
    }
    try:
        supabase.table("form_reminder_sends").upsert(row, on_conflict="member_id,channel").execute()
    except Exception as exc:
        logger.warning("Could not record %s send for %s: %s",
                       channel, _mask_email(member.email), exc)


# ---------------------------------------------------------------------------
# Senders
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


def _print_dry_run(members: list[Member], prior: dict[tuple[str, str], dict]) -> None:
    """Full member details are shown here on purpose — verifying the recipient
    list is the point of a dry run — and both log targets stay local/gitignored."""
    for m in members:
        already = ("  [already sent]"
                   if prior.get((m.member_id, "email"), {}).get("status") == "sent" else "")
        logger.info("  %s | %s | %s%s", m.full_name, m.email, m.country, already)
    logger.info("Form link: %s", FORM_URL)
    logger.info("Dry run — nothing sent.")


def _channel_result(channel: str, member: Member, send: Callable[[Member], None],
                    disabled: bool, prior: dict[tuple[str, str], dict]) -> ChannelResult:
    """Decide skip vs attempt for one channel, then run to send."""
    if disabled:
        return ChannelResult(Outcome.SKIPPED)
    previous = prior.get((member.member_id, channel))
    if previous and previous["status"] == "sent":
        return ChannelResult(Outcome.SKIPPED, "already sent")
    return _run_channel(channel, member, send)


def _run(args: argparse.Namespace) -> None:
    members = fetch_non_german_members()
    if not members:
        logger.info("No non-German members found — nothing to do.")
        return
    prior = fetch_prior_sends()
    logger.info("Found %d non-German member(s); %d prior send record(s).",
                len(members), len(prior))

    if args.dry_run:
        _print_dry_run(members, prior)
        return

    logger.info(
        "Sending (email=%s, whatsapp=%s) with %.1fs delay between recipients.",
        "off" if args.no_email else "on",
        "off" if args.no_whatsapp else "on",
        SEND_DELAY_SECONDS,
    )

    failed_members = 0
    with open(REPORT_FILE, "w", newline="", encoding="utf-8") as report:
        writer = csv.DictWriter(
            report, fieldnames=["name", "email", "email_status", "whatsapp_status"],
            delimiter=";",
        )
        writer.writeheader()
        for i, member in enumerate(members, start=1):
            logger.info("[%d/%d] %s <%s>", i, len(members),
                        member.full_name, _mask_email(member.email))
            email_result = _channel_result("email", member, send_email, args.no_email, prior)
            whatsapp_result = _channel_result(
                "whatsapp", member, send_whatsapp, args.no_whatsapp, prior)

            for channel, result in (("email", email_result), ("whatsapp", whatsapp_result)):
                if result.outcome is not Outcome.SKIPPED:
                    record_send(member, channel, result, prior)

            writer.writerow({
                "name": _csv_cell(member.full_name),
                "email": member.email,
                "email_status": email_result.render(),
                "whatsapp_status": whatsapp_result.render(),
            })
            report.flush()  # a row survives even if the run is interrupted

            if Outcome.FAILED in (email_result.outcome, whatsapp_result.outcome):
                failed_members += 1
            attempted = (email_result.outcome is not Outcome.SKIPPED
                         or whatsapp_result.outcome is not Outcome.SKIPPED)
            if attempted and i < len(members):
                time.sleep(SEND_DELAY_SECONDS)  # pace the external APIs

    logger.info("Done. %d processed, %d with failure(s). Report: %s",
                len(members), failed_members, REPORT_FILE)


def main() -> None:
    parser = argparse.ArgumentParser(description="Send the form link to all non-German members.")
    parser.add_argument("--dry-run", action="store_true", help="Preview recipients, send nothing.")
    parser.add_argument("--no-email", action="store_true", help="Skip email sending.")
    parser.add_argument("--no-whatsapp", action="store_true", help="Skip WhatsApp sending.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose (DEBUG) console output.")
    args = parser.parse_args()

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
