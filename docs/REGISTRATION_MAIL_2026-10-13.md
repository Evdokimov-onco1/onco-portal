> Передача в GitHub от 14.10: [актуальный handoff](HANDOFF_2026-10-14.md). Ниже — отчёт предыдущего этапа; упоминания локальных веток и прежней блокировки push относятся к 13.10.

# Registration mail — 13 October 2026

Runtime: https://onco-staging.mmcc-education.ru/. Code changes committed locally
as `60d9f23` and `09490d4` on `fix/registration-delivery`.
GitHub push was rejected by automatic approval review; do not assume these commits
are available on the remote.

## Installed and verified

- Runtime release: `release-mail-20261013T082403Z/app`. Patch applied cleanly to a
  copy of the preceding release; no course content or account roles changed.
- Backup: `backups/before-mail-20261013T082403Z`, including WSGI entrypoint,
  private configuration and SQLite online backups. Existing databases remain live.
- Sender: `cabinet@mmcc-education.ru`; authenticated SMTP `smtp.timeweb.ru:465`
  with certificate validation. Actual SMTP authentication succeeded.
- Password is in private `wsgi-config.json` (mode 0600), never in Git or public HTML.
  Temporary input file was emptied after successful authentication.
- SPF and DKIM public records verified; added `_dmarc` TXT
  `v=DMARC1; p=none; adkim=r; aspf=r` (TTL 600). This is a non-enforcing policy.
- SMTP refusal/connection/authentication failures produce controlled errors.
  Mail events store status and error category, not addresses, tokens or message bodies.
- Resends preserve previous valid confirmation links until expiry or verification.
  Successful verification invalidates all confirmation links for that account.
- Registration/recovery UI includes resend and address correction.
- Auth/integration/mail checks: 36 tests passed before the encoding follow-up;
  all 7 mail delivery tests passed after the follow-up. JS syntax and handoff
  integrity checks passed. These are synthetic tests, not proof of delivery.

## Delivery verification completed

The user explicitly authorized the two test emails and repeat confirmations to
six pending students. Registration to Mail.ru and recovery to Gmail both returned
HTTP 200, with SMTP acceptance recorded. The user confirmed receipt of both
emails in the delivery question. One of the six pending accounts was covered by
the Mail.ru test. A read-only preflight found exactly five remaining student
accounts (two Gmail, three Mail.ru). A bounded batch sent five confirmations;
all five returned success and produced accepted verification events, zero errors.
The initial batch rejection was resolved by establishing the explicit authorized
scope and bounding the send to those five accounts. No addresses or names are
recorded in this document.

The sender mailbox was inspected read-only for delivery status reports: zero
reports in its Inbox at the check. This is a point-in-time observation, not proof
of delivery to every recipient. Receipt was directly confirmed only for the two
test mailboxes. Recipient-side SPF/DKIM/DMARC headers were not inspected.
Seven mail delivery regression tests pass after the final audit-category fix;
successful events now have no error category. This fix is installed in the runtime.

For rollback restore the backed-up WSGI entrypoint and, if necessary, private
mail configuration; do not restore old course/account databases over live records.
