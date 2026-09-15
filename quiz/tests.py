"""
Automated tests for anti-cheat violation reporting and CRIT-03 remediation.
Verifies:
1. Native Ed25519-signed violation reporting from Electron Main Process succeeds.
2. Unattested reports of desktop-level violations (PROHIBITED_PROCESS) are rejected (HTTP 403).
3. Tampered Ed25519 signatures are rejected (HTTP 403).
4. Auto-submit triggers when maximum violations threshold is reached.
"""
import json
import time
import uuid
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.cache import cache
from cryptography.hazmat.primitives.asymmetric import ed25519

from core.models import ViolationLog
from core.secure_app import register_candidate_attestation_key
from quiz.models import Quiz, QuizParticipation

User = get_user_model()


class ViolationReportingSecurityTests(TestCase):

    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = User.objects.create_user(
            username='exam_student',
            email='exam_student@cyberonites.com',
            password='ExamPassword123!',
            full_name='Exam Candidate',
            college='Engineering College'
        )
        self.client.login(username='exam_student', password='ExamPassword123!')

        self.quiz = Quiz.objects.create(
            title='Security Proctored Quiz',
            description='Testing Anti-Cheat Engine',
            duration_minutes=60,
            start_time=timezone.now(),
            end_time=timezone.now() + timezone.timedelta(hours=2),
            status='ACTIVE',
            max_violations=3,
            is_proctored=True,
        )

        self.participation = QuizParticipation.objects.create(
            quiz=self.quiz,
            participant=self.user,
            is_submitted=False,
            violation_count=0,
            started_at=timezone.now(),
        )

        # Generate ephemeral Ed25519 key pair
        self.private_key = ed25519.Ed25519PrivateKey.generate()
        self.public_key = self.private_key.public_key()
        self.pub_hex = self.public_key.public_bytes_raw().hex()

        # Register key with candidate attempt session
        register_candidate_attestation_key(
            quiz_id=self.quiz.id,
            user=self.user,
            public_key_hex=self.pub_hex,
            session_key=self.client.session.session_key or 'test-session-key'
        )

    def _sign_request_headers(self, method, path):
        timestamp = str(int(time.time() * 1000))
        nonce = uuid.uuid4().hex
        msg = f"{timestamp}:{nonce}:{method.upper()}:{path}".encode('utf-8')
        sig_hex = self.private_key.sign(msg).hex()
        return {
            'HTTP_X_SECURE_APP_TIMESTAMP': timestamp,
            'HTTP_X_SECURE_APP_NONCE': nonce,
            'HTTP_X_SECURE_APP_SIGNATURE': sig_hex,
            'HTTP_X_SECURE_APP_PUBLIC_KEY': self.pub_hex,
        }

    def test_native_ed25519_violation_report_succeeds(self):
        """Native Electron process sending signed violation report is recorded."""
        path = f'/quiz/{self.quiz.id}/violation/'
        headers = self._sign_request_headers('POST', path)

        payload = {
            'type': 'PROHIBITED_PROCESS',
            'details': 'Prohibited application detected running: AnyDesk (anydesk.exe)',
        }

        response = self.client.post(
            path,
            data=json.dumps(payload),
            content_type='application/json',
            **headers
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'recorded')
        self.assertEqual(data.get('violation_count'), 1)
        self.assertFalse(data.get('auto_submitted'))

        # Verify DB entry
        self.participation.refresh_from_db()
        self.assertEqual(self.participation.violation_count, 1)

        v_log = ViolationLog.objects.filter(quiz=self.quiz, participant=self.user).first()
        self.assertIsNotNone(v_log)
        self.assertEqual(v_log.violation_type, 'PROHIBITED_PROCESS')
        self.assertIn('AnyDesk', v_log.details)

    def test_unattested_prohibited_process_rejected(self):
        """Unattested request (e.g. from Chrome console) claiming PROHIBITED_PROCESS must be rejected."""
        path = f'/quiz/{self.quiz.id}/violation/'
        payload = {
            'type': 'PROHIBITED_PROCESS',
            'details': 'Spoofed process violation',
        }

        # Send POST without Ed25519 headers
        response = self.client.post(
            path,
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)
        self.participation.refresh_from_db()
        self.assertEqual(self.participation.violation_count, 0)

    def test_tampered_ed25519_violation_report_rejected(self):
        """A violation report with a tampered signature must be rejected."""
        path = f'/quiz/{self.quiz.id}/violation/'
        headers = self._sign_request_headers('POST', path)
        headers['HTTP_X_SECURE_APP_SIGNATURE'] = '0' * 128  # Invalid signature

        payload = {
            'type': 'PROHIBITED_PROCESS',
            'details': 'Prohibited application detected',
        }

        response = self.client.post(
            path,
            data=json.dumps(payload),
            content_type='application/json',
            **headers
        )

        self.assertEqual(response.status_code, 403)
        self.participation.refresh_from_db()
        self.assertEqual(self.participation.violation_count, 0)

    def test_auto_submit_on_max_violations_via_native_report(self):
        """When violations reach max_violations, the participation is auto-submitted."""
        path = f'/quiz/{self.quiz.id}/violation/'

        # Send 3 violations
        for i in range(1, 4):
            headers = self._sign_request_headers('POST', path)
            payload = {
                'type': 'PROHIBITED_PROCESS',
                'details': f'Prohibited app instance #{i}',
            }
            response = self.client.post(
                path,
                data=json.dumps(payload),
                content_type='application/json',
                **headers
            )
            self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data.get('violation_count'), 3)
        self.assertTrue(data.get('auto_submitted'))

        self.participation.refresh_from_db()
        self.assertTrue(self.participation.is_submitted)
        self.assertIsNotNone(self.participation.finished_at)


class AttemptStateMachineSecurityTests(TestCase):
    """
    Automated security tests for CRIT-04 (Attempt Lifecycle State Machine).
    Verifies that state transitions cannot be manipulated or regressed.
    """

    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = User.objects.create_user(
            username='sm_student',
            email='sm_student@cyberonites.com',
            password='Password123!',
            full_name='State Machine Student',
        )
        self.client.login(username='sm_student', password='Password123!')

        self.quiz = Quiz.objects.create(
            title='State Machine Test Quiz',
            duration_minutes=30,
            status='ACTIVE',
            is_proctored=False,  # Test in standard mode to isolate state machine
        )

        from quiz.models import Question, Option
        self.q1 = Question.objects.create(
            quiz=self.quiz,
            text='What is 2+2?',
            marks=1,
        )
        self.opt1 = Option.objects.create(
            question=self.q1,
            text='4',
            is_correct=True,
            label='A',
        )

        self.participation = QuizParticipation.objects.create(
            quiz=self.quiz,
            participant=self.user,
            status='CREATED',
            is_submitted=False,
            started_at=timezone.now(),
        )

    def test_valid_lifecycle_transitions(self):
        """State machine allows CREATED -> IN_PROGRESS -> SUBMITTED -> EVALUATED."""
        self.assertEqual(self.participation.status, 'CREATED')
        self.assertFalse(self.participation.is_submitted)

        self.participation.transition_to('IN_PROGRESS')
        self.assertEqual(self.participation.status, 'IN_PROGRESS')
        self.assertFalse(self.participation.is_submitted)

        self.participation.transition_to('SUBMITTED')
        self.assertEqual(self.participation.status, 'SUBMITTED')
        self.assertTrue(self.participation.is_submitted)

        self.participation.transition_to('EVALUATED')
        self.assertEqual(self.participation.status, 'EVALUATED')
        self.assertTrue(self.participation.is_submitted)

    def test_invalid_lifecycle_transition_raises_validation_error(self):
        """Terminal or completed states cannot regress to earlier states."""
        from django.core.exceptions import ValidationError

        self.participation.status = 'SUBMITTED'
        self.participation.save()

        # Cannot regress from SUBMITTED to IN_PROGRESS
        with self.assertRaises(ValidationError):
            self.participation.transition_to('IN_PROGRESS')

        # Cannot regress from SUBMITTED to CREATED
        with self.assertRaises(ValidationError):
            self.participation.transition_to('CREATED')

        self.participation.status = 'INVALIDATED'
        self.participation.save()

        # Terminal state INVALIDATED cannot transition to any state
        with self.assertRaises(ValidationError):
            self.participation.transition_to('IN_PROGRESS')
        with self.assertRaises(ValidationError):
            self.participation.transition_to('SUBMITTED')

    def test_save_answer_rejected_when_not_in_progress(self):
        """Saving answers is strictly rejected if attempt is not IN_PROGRESS."""
        self.participation.status = 'SUBMITTED'
        self.participation.is_submitted = True
        self.participation.save()

        response = self.client.post(
            f'/quiz/{self.quiz.id}/save-answer/',
            data=json.dumps({
                'question_id': self.q1.id,
                'selected_option_id': self.opt1.id,
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('Cannot save answer', response.json().get('error', ''))

    def test_submit_quiz_idempotency_preserves_evaluation(self):
        """Calling submit multiple times transitions properly and does not break."""
        self.participation.status = 'IN_PROGRESS'
        self.participation.is_submitted = False
        self.participation.save()

        # First submission
        res1 = self.client.post(f'/quiz/{self.quiz.id}/submit/')
        self.assertEqual(res1.status_code, 200)

        self.participation.refresh_from_db()
        self.assertEqual(self.participation.status, 'EVALUATED')
        self.assertTrue(self.participation.is_submitted)

        # Second submission (idempotency check)
        res2 = self.client.post(f'/quiz/{self.quiz.id}/submit/')
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.json().get('status'), 'submitted')
        self.assertIn('Already submitted', res2.json().get('message', ''))

