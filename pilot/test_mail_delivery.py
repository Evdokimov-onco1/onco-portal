"""Delivery failures and concurrency, using synthetic recipients only."""
import json
import smtplib
import tempfile
import unittest
from email.parser import BytesParser
from pathlib import Path
from unittest import mock

from pilot.auth import AccountStore
from pilot.mailer import Mailer, MailError, mailer_from_env
from pilot.test_auth import make_auth_stack, run_post, FlakyMailer, extract_token


class MailDeliveryTests(unittest.TestCase):
    def test_accepted_resend_keeps_previously_delivered_link(self):
        with tempfile.TemporaryDirectory() as td:
            sink = []
            pilot, _, store, _, _ = make_auth_stack(Path(td), mailer=FlakyMailer(sink))
            body = {'email': 'synthetic@example.test', 'name': 'Synthetic'}
            self.assertEqual(run_post(pilot, '/api/auth/register', body)[0], 200)
            first = extract_token(sink)
            self.assertEqual(run_post(pilot, '/api/auth/register', body)[0], 200)
            second = extract_token(sink)
            self.assertEqual(run_post(pilot, '/api/auth/verify', {'token': first, 'password': 'Synthetic-password-123'})[0], 200)
            self.assertEqual(run_post(pilot, '/api/auth/verify', {'token': second, 'password': 'Synthetic-password-123'})[0], 400)

    def test_failed_resend_keeps_previous_link_and_logs_no_secret(self):
        with tempfile.TemporaryDirectory() as td:
            sink = []
            mailer = FlakyMailer(sink)
            pilot, _, store, _, _ = make_auth_stack(Path(td), mailer=mailer)
            body = {'email': 'synthetic@example.test', 'name': 'Synthetic'}
            self.assertEqual(run_post(pilot, '/api/auth/register', body)[0], 200)
            token = extract_token(sink)
            mailer.fail_next = 1
            self.assertEqual(run_post(pilot, '/api/auth/register', body)[0], 503)
            with store._connect() as con:
                events = [dict(r) for r in con.execute('SELECT * FROM mail_events ORDER BY started')]
            self.assertEqual([r['status'] for r in events], ['accepted', 'failed'])
            self.assertIsNone(events[0]['category'])
            self.assertNotIn(token, json.dumps(events))
            self.assertNotIn(body['email'], json.dumps(events))
            self.assertEqual(run_post(pilot, '/api/auth/verify', {'token': token, 'password': 'Synthetic-password-123'})[0], 200)

    def test_out_of_order_delivery_never_revokes_newer_link(self):
        with tempfile.TemporaryDirectory() as td:
            store = AccountStore(Path(td)/'accounts.db')
            _, a = store.register('a@example.test', 'Synthetic', 'ip')
            ea = store.begin_mail('verify', a)
            _, b = store.register('a@example.test', 'Synthetic', 'ip')
            eb = store.begin_mail('verify', b)
            store.finish_mail(eb, b)
            store.finish_mail(ea, a)
            store.verify(b, 'Synthetic-password-123', 'ip')

    def test_smtp_configuration_wins_over_legacy_sendmail(self):
        mailer = mailer_from_env({'PILOT_SMTP_HOST':'smtp.example.test', 'PILOT_SENDMAIL_PATH':'/usr/sbin/sendmail', 'PILOT_MAIL_FROM':'onco@example.test'})
        self.assertEqual(mailer.config['transport'], 'smtp')
        for port in ('bad', None, 25):
            self.assertFalse(Mailer({'smtp_host':'smtp.example.test', 'smtp_port':port, 'mail_from':'a@example.test'}).configured())

    def test_smtp_recipient_refusal_is_failure_not_success(self):
        mailer = Mailer({'smtp_host':'smtp.example.test', 'mail_from':'onco@example.test'})
        with mock.patch('pilot.mailer.smtplib.SMTP') as cls:
            smtp = cls.return_value.__enter__.return_value
            smtp.send_message.return_value = {'a@example.test':(550,b'secret response')}
            with self.assertRaises(MailError) as caught:
                mailer.send('a@example.test','Subject','Body')
            self.assertEqual(caught.exception.category,'recipient')
            self.assertEqual(caught.exception.code,550)
            self.assertNotIn('secret',str(caught.exception))
            smtp.send_message.side_effect = smtplib.SMTPAuthenticationError(535,b'secret')
            with self.assertRaises(MailError) as caught:
                mailer.send('a@example.test','Subject','Body')
            self.assertEqual(caught.exception.category,'authentication')

    def test_sendmail_envelope_headers_and_crlf(self):
        mailer = Mailer({'transport':'sendmail','sendmail_path':'/usr/sbin/sendmail','mail_from':'onco@example.test'})
        with mock.patch('pilot.mailer.os.path.isfile',return_value=True), mock.patch('pilot.mailer.subprocess.run') as run:
            run.return_value.returncode = 0
            message_id = mailer.send('a@example.test','Тема','Текст')
            self.assertEqual(run.call_args.args[0][-2:],['-f','onco@example.test'])
            payload = run.call_args.kwargs['input']
            msg = BytesParser().parsebytes(payload)
            self.assertEqual(msg['Message-ID'],message_id)
            self.assertIsNotNone(msg['Date'])
            self.assertNotIn(b'\n',payload.replace(b'\r\n',b''))

    def test_invalid_credential_encoding_is_controlled_failure(self):
        mailer = Mailer({'smtp_host':'smtp.example.test', 'mail_from':'onco@example.test', 'smtp_user':'onco@example.test', 'smtp_password':'synthetic'})
        with mock.patch('pilot.mailer.smtplib.SMTP') as cls:
            smtp = cls.return_value.__enter__.return_value
            smtp.login.side_effect = UnicodeEncodeError('ascii', 'я', 0, 1, 'synthetic')
            with self.assertRaises(MailError) as caught:
                mailer.send('a@example.test','Subject','Body')
            self.assertEqual(caught.exception.category,'authentication')
            smtp.send_message.assert_not_called()


if __name__ == '__main__':
    unittest.main()
