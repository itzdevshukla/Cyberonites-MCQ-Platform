"""
Automated tests for Dashboard Admin Submission Inspector.
Verifies:
1. Strict access control: unauthenticated users redirected to admin login.
2. Non-staff participants cannot inspect other participants' submissions.
3. Staff administrators can inspect submissions with full forensic breakdown.
4. Accuracy, score deltas, and answer statuses are properly calculated.
5. VIEW_SUBMISSION action is recorded in immutable AuditLog.
"""
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from quiz.models import Quiz, Question, Option, QuizParticipation, Answer
from core.models import AuditLog, ViolationLog

User = get_user_model()


class AdminSubmissionInspectorTests(TestCase):

    def setUp(self):
        # Create staff admin user
        self.admin_user = User.objects.create_user(
            username='super_admin',
            email='admin@qarena.com',
            password='AdminPassword123!',
            full_name='Platform Administrator',
            is_staff=True
        )

        # Create student participant user
        self.student_user = User.objects.create_user(
            username='student_one',
            email='student1@college.edu',
            password='StudentPass123!',
            full_name='First Student',
            college='Tech Institute'
        )

        # Create another student participant user
        self.student_two = User.objects.create_user(
            username='student_two',
            email='student2@college.edu',
            password='StudentPass123!',
            full_name='Second Student',
            college='Tech Institute'
        )

        # Create quiz
        self.quiz = Quiz.objects.create(
            title='Forensic Security Test Quiz',
            description='Testing question-level inspector',
            duration_minutes=30,
            status='COMPLETED',
            created_by=self.admin_user,
        )

        # Create Question 1 (marks=2, negative_marks=0.5)
        self.q1 = Question.objects.create(
            quiz=self.quiz,
            text='What protocol secures web communications?',
            topic='Networking',
            difficulty='EASY',
            order=1,
            marks=2,
            negative_marks=0.5,
            description='HTTPS encrypts traffic over TLS.'
        )
        self.q1_opt_a = Option.objects.create(question=self.q1, label='A', text='HTTP', is_correct=False)
        self.q1_opt_b = Option.objects.create(question=self.q1, label='B', text='HTTPS', is_correct=True)

        # Create Question 2 (marks=3, negative_marks=1.0)
        self.q2 = Question.objects.create(
            quiz=self.quiz,
            text='Which asymmetric algorithm uses elliptic curves?',
            topic='Cryptography',
            difficulty='HARD',
            order=2,
            marks=3,
            negative_marks=1.0,
            description='Ed25519 uses Curve25519.'
        )
        self.q2_opt_a = Option.objects.create(question=self.q2, label='A', text='Ed25519', is_correct=True)
        self.q2_opt_b = Option.objects.create(question=self.q2, label='B', text='MD5', is_correct=False)

        # Create Question 3 (Skipped by student)
        self.q3 = Question.objects.create(
            quiz=self.quiz,
            text='What port does SSH use by default?',
            topic='Linux',
            difficulty='MEDIUM',
            order=3,
            marks=1,
            negative_marks=0,
            description='Port 22 is default SSH port.'
        )
        self.q3_opt_a = Option.objects.create(question=self.q3, label='A', text='22', is_correct=True)
        self.q3_opt_b = Option.objects.create(question=self.q3, label='B', text='80', is_correct=False)

        self.quiz.recalculate_total_marks()

        # Create participation for student_one
        self.part1 = QuizParticipation.objects.create(
            quiz=self.quiz,
            participant=self.student_user,
            status='SUBMITTED',
            is_submitted=True,
            score=1.0,  # Q1 correct (+2), Q2 wrong (-1) = 1.0
            time_taken=125.0,
            violation_count=1,
            question_order=[self.q1.id, self.q2.id, self.q3.id],
            option_orders={
                str(self.q1.id): [self.q1_opt_a.id, self.q1_opt_b.id],
                str(self.q2.id): [self.q2_opt_a.id, self.q2_opt_b.id],
            }
        )

        # Student answered Q1 correctly
        Answer.objects.create(
            participation=self.part1,
            question=self.q1,
            selected_option=self.q1_opt_b,
            is_correct=True
        )

        # Student answered Q2 incorrectly
        Answer.objects.create(
            participation=self.part1,
            question=self.q2,
            selected_option=self.q2_opt_b,
            is_correct=False
        )

        # Q3 skipped (no Answer or Answer with selected_option=None)

        # Add a violation log for student_one
        ViolationLog.objects.create(
            quiz=self.quiz,
            participant=self.student_user,
            violation_type='TAB_SWITCH',
            details='Candidate switched away from browser tab',
            ip_address='127.0.0.1'
        )

    def test_anonymous_user_access_denied(self):
        """Unauthenticated user must be redirected to admin login."""
        client = Client()
        url = reverse('dashboard:participant_submission', kwargs={
            'quiz_id': self.quiz.id,
            'participant_id': self.student_user.id
        })
        response = client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:admin_login'), response.url)

    def test_non_staff_participant_access_denied(self):
        """Regular candidate cannot inspect submissions."""
        client = Client()
        client.login(username='student_two', password='StudentPass123!')
        url = reverse('dashboard:participant_submission', kwargs={
            'quiz_id': self.quiz.id,
            'participant_id': self.student_user.id
        })
        response = client.get(url)
        self.assertEqual(response.status_code, 302)
        # Should redirect with error message
        self.assertIn(reverse('accounts:login'), response.url)

    def test_admin_submission_inspection_success(self):
        """Staff admin successfully accesses submission with complete breakdown and audit logging."""
        client = Client()
        client.login(username='super_admin', password='AdminPassword123!')
        url = reverse('dashboard:participant_submission', kwargs={
            'quiz_id': self.quiz.id,
            'participant_id': self.student_user.id
        })
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'dashboard/admin/submission_detail.html')

        # Verify context metrics
        ctx = response.context
        self.assertEqual(ctx['total_questions'], 3)
        self.assertEqual(ctx['correct_count'], 1)
        self.assertEqual(ctx['wrong_count'], 1)
        self.assertEqual(ctx['skipped_count'], 1)
        self.assertEqual(ctx['violation_count'], 1)
        self.assertEqual(ctx['participant'], self.student_user)

        # Verify HTML rendered elements
        content = response.content.decode('utf-8')
        self.assertIn('Submission Inspector', content)
        self.assertIn('QArena', content)
        self.assertIn('First Student', content)
        self.assertIn('What protocol secures web communications?', content)
        self.assertIn("Candidate's Choice (Correct)", content)
        self.assertIn("Candidate's Choice (Wrong)", content)
        self.assertIn('Correct Answer', content)
        self.assertIn('HTTPS encrypts traffic over TLS.', content)

        # Verify AuditLog entry was created
        audit_entry = AuditLog.objects.filter(
            action='VIEW_SUBMISSION',
            target_model='QuizParticipation',
            target_id=str(self.part1.id)
        ).first()
        self.assertIsNotNone(audit_entry)
        self.assertEqual(audit_entry.actor, self.admin_user)
        self.assertEqual(audit_entry.details['participant_id'], self.student_user.id)

    def test_reopen_completed_quiz(self):
        """Verify an admin can successfully reopen an accidentally completed quiz and reset participant states."""
        client = Client()
        client.login(username='super_admin', password='AdminPassword123!')

        # Quiz is currently COMPLETED, student is SUBMITTED
        self.assertEqual(self.quiz.status, 'COMPLETED')
        self.assertTrue(self.part1.is_submitted)

        url = reverse('dashboard:quiz_control', kwargs={'quiz_id': self.quiz.id})
        response = client.post(url, {
            'action': 'reopen',
            'extra_minutes': 20,
            'reopen_participants': 'on'
        })
        self.assertEqual(response.status_code, 302)

        # Refresh quiz and participation
        self.quiz.refresh_from_db()
        self.part1.refresh_from_db()

        self.assertEqual(self.quiz.status, 'ACTIVE')
        self.assertFalse(self.part1.is_submitted)
        self.assertEqual(self.part1.status, 'IN_PROGRESS')
        self.assertIsNone(self.part1.finished_at)
