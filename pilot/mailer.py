"""Отправка писем (stdlib). В тестах подменяется фейковым транспортом."""
import os
import re
import smtplib
import ssl
import subprocess
from email.message import EmailMessage
from email.utils import parseaddr

_SENDMAIL_ALLOWLIST = frozenset(('/usr/sbin/sendmail', '/usr/lib/sendmail'))
_SENDMAIL_TIMEOUT = 20
_ADDR_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class MailError(Exception):
    pass


class Mailer:
    def __init__(self, config):
        self.config = config or {}

    def _valid_sender(self):
        addr = (self.config.get('mail_from') or '').strip()
        if not addr or not _ADDR_RE.match(addr):
            return False
        name, email = parseaddr(addr)
        return bool(email) and _ADDR_RE.match(email)

    def configured(self):
        if self.config.get('transport') == 'fake':
            return True
        if not self._valid_sender():
            return False
        if self.config.get('transport') == 'sendmail':
            path = self.config.get('sendmail_path') or ''
            return path in _SENDMAIL_ALLOWLIST and os.path.isfile(path)
        return bool(self.config.get('smtp_host'))

    def send(self, to_addr, subject, body_text):
        if not self.configured():
            raise MailError('Почта не настроена.')
        if self.config.get('transport') == 'fake':
            sink = self.config.get('sink')
            if sink is not None:
                sink.append({'to': to_addr, 'subject': subject, 'body': body_text})
            return
        msg = EmailMessage()
        msg['From'] = self.config['mail_from'].strip()
        msg['To'] = to_addr
        msg['Subject'] = subject
        msg.set_content(body_text)
        if self.config.get('transport') == 'sendmail':
            path = self.config['sendmail_path']
            if path not in _SENDMAIL_ALLOWLIST:
                raise MailError('Недопустимый путь sendmail.')
            try:
                proc = subprocess.run(
                    [path, '-t', '-oi'],
                    input=msg.as_bytes(),
                    capture_output=True,
                    timeout=_SENDMAIL_TIMEOUT,
                )
            except (OSError, subprocess.TimeoutExpired):
                raise MailError('Не удалось отправить письмо.') from None
            if proc.returncode != 0:
                raise MailError('Не удалось отправить письмо.')
            return
        host = self.config['smtp_host']
        port = int(self.config.get('smtp_port', 587))
        user = self.config.get('smtp_user') or ''
        password = self.config.get('smtp_password') or ''
        ctx = ssl.create_default_context()
        try:
            if port == 465:
                with smtplib.SMTP_SSL(host, port, timeout=_SENDMAIL_TIMEOUT, context=ctx) as smtp:
                    if user:
                        smtp.login(user, password)
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=_SENDMAIL_TIMEOUT) as smtp:
                    smtp.starttls(context=ctx)
                    if user:
                        smtp.login(user, password)
                    smtp.send_message(msg)
        except (smtplib.SMTPException, OSError, subprocess.TimeoutExpired):
            raise MailError('Не удалось отправить письмо.')


def mailer_from_env(env):
    if env.get('PILOT_MAIL_TRANSPORT') == 'fake':
        return Mailer({'transport': 'fake', 'sink': env.get('PILOT_MAIL_SINK')})
    mail_from = env.get('PILOT_MAIL_FROM', '').strip()
    if env.get('PILOT_SENDMAIL_PATH'):
        path = env['PILOT_SENDMAIL_PATH']
        if path in _SENDMAIL_ALLOWLIST:
            return Mailer({'transport': 'sendmail', 'sendmail_path': path, 'mail_from': mail_from})
    if env.get('PILOT_SMTP_HOST'):
        return Mailer({
            'transport': 'smtp',
            'smtp_host': env['PILOT_SMTP_HOST'].strip(),
            'smtp_port': env.get('PILOT_SMTP_PORT', '587'),
            'smtp_user': env.get('PILOT_SMTP_USER', ''),
            'smtp_password': env.get('PILOT_SMTP_PASSWORD', ''),
            'mail_from': mail_from,
        })
    return Mailer({'mail_from': mail_from})
