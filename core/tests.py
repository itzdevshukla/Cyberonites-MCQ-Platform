"""
Automated unit tests for Ed25519 cryptographic attestation and session binding.
Verifies remediation of CRIT-01 (eliminates static shared-secret spoofing).
"""
import time
import uuid
from django.test import TestCase, RequestFactory, Client
from django.contrib.auth import get_user_model
from django.core.cache import cache
from cryptography.hazmat.primitives.asymmetric import ed25519

from core.secure_app import (
    verify_secure_app_request,
    register_candidate_attestation_key,
    MAX_CLOCK_SKEW_SECONDS,
)
from core.audit import log_audit_event

User = get_user_model()


class Ed25519AttestationSecurityTests(TestCase):

    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username='teststudent',
            email='teststudent@cyberonites.com',
            password='TestPassword123!',
            full_name='Test Candidate',
            college='Engineering College'
        )

        # Generate ephemeral Ed25519 key pair for test client
        self.private_key = ed25519.Ed25519PrivateKey.generate()
        self.public_key = self.private_key.public_key()
        self.pub_hex = self.public_key.public_bytes_raw().hex()

    def _generate_signed_request(self, method='GET', path='/quiz/1/take/', timestamp=None, nonce=None, priv_key=None, pub_hex=None, tampered_path=None):
        if timestamp is None:
            timestamp = str(int(time.time() * 1000))
        if nonce is None:
            nonce = uuid.uuid4().hex
        if priv_key is None:
            priv_key = self.private_key
        if pub_hex is None:
            pub_hex = self.pub_hex

        # Canonical message: timestamp:nonce:method:path
        sign_path = tampered_path if tampered_path is not None else path
        msg = f"{timestamp}:{nonce}:{method.upper()}:{sign_path}".encode('utf-8')
        sig_hex = priv_key.sign(msg).hex()

        if method.upper() == 'POST':
            req = self.factory.post(path)
        else:
            req = self.factory.get(path)

        req.user = self.user
        req.session = self.client.session
        req.headers = {
            'X-Secure-App-Timestamp': timestamp,
            'X-Secure-App-Nonce': nonce,
            'X-Secure-App-Signature': sig_hex,
            'X-Secure-App-Public-Key': pub_hex,
        }
        return req

    def test_valid_ed25519_signature_succeeds(self):
        """A valid Ed25519 signed request must be accepted."""
        req = self._generate_signed_request()
        is_valid, reason = verify_secure_app_request(req, quiz_id=1)
        self.assertTrue(is_valid)
        self.assertEqual(reason, "Valid")

    def test_missing_attestation_headers_rejected(self):
        """Requests without attestation headers must fail immediately."""
        req = self.factory.get('/quiz/1/take/')
        req.user = self.user
        req.headers = {}
        is_valid, reason = verify_secure_app_request(req, quiz_id=1)
        self.assertFalse(is_valid)
        self.assertIn("Missing cryptographic attestation headers", reason)

    def test_clock_skew_expiration_rejected(self):
        """Requests with timestamps older than MAX_CLOCK_SKEW_SECONDS must be rejected."""
        old_time = str(int((time.time() - (MAX_CLOCK_SKEW_SECONDS + 30)) * 1000))
        req = self._generate_signed_request(timestamp=old_time)
        is_valid, reason = verify_secure_app_request(req, quiz_id=1)
        self.assertFalse(is_valid)
        self.assertIn("Request expired or clock drift excessive", reason)

    def test_nonce_replay_attack_rejected(self):
        """Replaying the exact same request/nonce must be blocked by the nonce cache."""
        fixed_nonce = uuid.uuid4().hex
        req1 = self._generate_signed_request(nonce=fixed_nonce)
        is_valid1, _ = verify_secure_app_request(req1, quiz_id=1)
        self.assertTrue(is_valid1)

        # Attempt replay with identical nonce
        req2 = self._generate_signed_request(nonce=fixed_nonce)
        is_valid2, reason2 = verify_secure_app_request(req2, quiz_id=1)
        self.assertFalse(is_valid2)
        self.assertIn("Replay attack detected", reason2)

    def test_tampered_signature_rejected(self):
        """Altered signature bytes must fail cryptographic verification."""
        req = self._generate_signed_request()
        # Flip hex characters in signature
        bad_sig = "00" * 64
        req.headers['X-Secure-App-Signature'] = bad_sig
        is_valid, reason = verify_secure_app_request(req, quiz_id=1)
        self.assertFalse(is_valid)
        self.assertIn("Invalid cryptographic client signature", reason)

    def test_tampered_path_or_method_rejected(self):
        """Signing for one endpoint but calling another must fail verification."""
        # Signature is calculated for /quiz/1/take/ but sent to /quiz/1/save-answer/
        req = self._generate_signed_request(path='/quiz/1/save-answer/', tampered_path='/quiz/1/take/')
        is_valid, reason = verify_secure_app_request(req, quiz_id=1)
        self.assertFalse(is_valid)
        self.assertIn("Invalid cryptographic client signature", reason)

    def test_session_bound_public_key_mismatch_rejected(self):
        """A different public key presented for an already bound session must be rejected."""
        # First request binds self.pub_hex
        req1 = self._generate_signed_request()
        is_valid1, _ = verify_secure_app_request(req1, quiz_id=1)
        self.assertTrue(is_valid1)

        # Second device/key pair attempts to make requests for the same quiz and user
        rogue_priv = ed25519.Ed25519PrivateKey.generate()
        rogue_pub_hex = rogue_priv.public_key().public_bytes_raw().hex()
        req2 = self._generate_signed_request(priv_key=rogue_priv, pub_hex=rogue_pub_hex)
        is_valid2, reason2 = verify_secure_app_request(req2, quiz_id=1)
        self.assertFalse(is_valid2)
        self.assertIn("Attestation key mismatch", reason2)


class AuditLogSecurityTests(TestCase):
    """Automated unit tests for persistent immutable audit logging (HIGH-04)."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='adminuser',
            email='admin@cyberonites.com',
            password='AdminPassword123!',
            full_name='Security Admin'
        )
        self.student = User.objects.create_user(
            username='regularstudent',
            email='student@cyberonites.com',
            password='StudentPassword123!',
            full_name='Regular Student',
            is_staff=False
        )
        self.factory = RequestFactory()
        self.client = Client()

    def test_log_audit_event_helper(self):
        """log_audit_event creates a structured, persistent AuditLog record."""
        req = self.factory.post('/dashboard/quizzes/create/', HTTP_USER_AGENT='AdminBrowser/1.0')
        req.user = self.admin
        req.META['REMOTE_ADDR'] = '198.51.100.42'

        entry = log_audit_event(
            request=req,
            action='QUIZ_CREATE',
            target_model='Quiz',
            target_id='99',
            details={'title': 'Test Hardened Quiz', 'duration': 45}
        )

        self.assertIsNotNone(entry)
        self.assertEqual(entry.actor, self.admin)
        self.assertEqual(entry.actor_email, 'admin@cyberonites.com')
        self.assertEqual(entry.action, 'QUIZ_CREATE')
        self.assertEqual(entry.target_model, 'Quiz')
        self.assertEqual(entry.target_id, '99')
        self.assertEqual(entry.ip_address, '198.51.100.42')
        self.assertEqual(entry.details['title'], 'Test Hardened Quiz')
        self.assertIn('AdminBrowser', entry.user_agent)

    def test_audit_log_immutability_prevents_update(self):
        """Updating an existing AuditLog row must raise PermissionError."""
        from core.models import AuditLog
        log = AuditLog.objects.create(
            actor=self.admin,
            actor_email='admin@cyberonites.com',
            action='QUIZ_CREATE',
            target_model='Quiz',
            target_id='100'
        )

        log.action = 'QUIZ_DELETE'
        with self.assertRaises(PermissionError):
            log.save()

    def test_audit_log_immutability_prevents_deletion(self):
        """Deleting an AuditLog row must raise PermissionError."""
        from core.models import AuditLog
        log = AuditLog.objects.create(
            actor=self.admin,
            actor_email='admin@cyberonites.com',
            action='QUIZ_START',
            target_model='Quiz',
            target_id='101'
        )

        with self.assertRaises(PermissionError):
            log.delete()

    def test_admin_quiz_creation_and_delete_audited(self):
        """Admin creating and deleting a quiz generates persistent audit entries."""
        from core.models import AuditLog
        from quiz.models import Quiz

        self.client.login(username='adminuser', password='AdminPassword123!')

        # Create quiz
        response = self.client.post('/dashboard/quizzes/create/', {
            'title': 'Audit Exam Test',
            'duration_minutes': '40',
            'max_violations': '3',
        })
        self.assertEqual(response.status_code, 302)

        created_quiz = Quiz.objects.get(title='Audit Exam Test')
        create_log = AuditLog.objects.filter(
            action='QUIZ_CREATE',
            target_model='Quiz',
            target_id=str(created_quiz.id)
        ).first()
        self.assertIsNotNone(create_log)
        self.assertEqual(create_log.actor_email, 'admin@cyberonites.com')

        # Delete quiz
        del_response = self.client.post(f'/dashboard/quizzes/{created_quiz.id}/delete/')
        self.assertEqual(del_response.status_code, 302)

        del_log = AuditLog.objects.filter(
            action='QUIZ_DELETE',
            target_model='Quiz',
            target_id=str(created_quiz.id)
        ).first()
        self.assertIsNotNone(del_log)
        self.assertEqual(del_log.details['title'], 'Audit Exam Test')

    def test_audit_trail_view_authorization(self):
        """Only staff members can view the audit trail page."""
        # Non-staff student access rejected with 404 (concealed stealth URL)
        self.client.login(username='regularstudent', password='StudentPassword123!')
        res_student = self.client.get('/dashboard/audit-logs/')
        self.assertEqual(res_student.status_code, 404)

        # Admin access granted
        self.client.login(username='adminuser', password='AdminPassword123!')
        res_admin = self.client.get('/dashboard/audit-logs/')
        self.assertEqual(res_admin.status_code, 200)
        self.assertContains(res_admin, "Security Audit Trail")

