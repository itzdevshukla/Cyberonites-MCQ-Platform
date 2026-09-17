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
from leaderboard.services import LeaderboardService

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
        """Unauthenticated user accessing admin endpoint receives 404 to conceal admin presence."""
        client = Client()
        url = reverse('dashboard:participant_submission', kwargs={
            'quiz_id': self.quiz.id,
            'participant_id': self.student_user.id
        })
        response = client.get(url)
        self.assertEqual(response.status_code, 404)

        # Main admin dashboard is also concealed as 404
        res_dash = client.get(reverse('dashboard:admin_dashboard'))
        self.assertEqual(res_dash.status_code, 404)

    def test_non_staff_participant_access_denied(self):
        """Regular candidate receives 404 to conceal admin presence."""
        client = Client()
        client.login(username='student_two', password='StudentPass123!')
        url = reverse('dashboard:participant_submission', kwargs={
            'quiz_id': self.quiz.id,
            'participant_id': self.student_user.id
        })
        response = client.get(url)
        self.assertEqual(response.status_code, 404)

        # Main admin dashboard is also concealed as 404
        res_dash = client.get(reverse('dashboard:admin_dashboard'))
        self.assertEqual(res_dash.status_code, 404)

    def test_secret_admin_login_accessible_and_old_is_404(self):
        """Secret admin login URL works, while old /accounts/admin-login/ returns 404."""
        client = Client()
        secret_url = '/byteviper_hackvajra_bitty_bold_shadow_cache/'
        res_secret = client.get(secret_url)
        self.assertEqual(res_secret.status_code, 200)
        self.assertTemplateUsed(res_secret, 'accounts/admin_login.html')

        res_secret_noslash = client.get('/byteviper_hackvajra_bitty_bold_shadow_cache')
        self.assertEqual(res_secret_noslash.status_code, 200)

        # Old url returns 404
        res_old = client.get('/accounts/admin-login/')
        self.assertEqual(res_old.status_code, 404)

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

    def test_quiz_model_defaults_to_proctored(self):
        """Verify new quizzes default to is_proctored=True to prevent accidental open-browser exams."""
        new_quiz = Quiz.objects.create(
            title='Default Proctoring Test Quiz',
            duration_minutes=15,
            created_by=self.admin_user
        )
        self.assertTrue(new_quiz.is_proctored)

    def test_memory_efficient_exports(self):
        """Verify streaming CSV and Excel exports work without error."""
        client = Client()
        client.login(username='super_admin', password='AdminPassword123!')

        # Create a leaderboard entry
        LeaderboardService.recalculate_ranks(self.quiz)

        # 1. Test Streaming CSV export
        csv_url = reverse('dashboard:export_results', kwargs={'quiz_id': self.quiz.id}) + '?format=csv'
        res_csv = client.get(csv_url)
        self.assertEqual(res_csv.status_code, 200)
        self.assertEqual(res_csv['Content-Type'], 'text/csv')
        self.assertTrue(res_csv.streaming)
        csv_content = b"".join(res_csv.streaming_content).decode('utf-8')
        self.assertIn('Rank,Name,College,Score', csv_content)

        # 2. Test Write-Only Excel export
        xlsx_url = reverse('dashboard:export_results', kwargs={'quiz_id': self.quiz.id}) + '?format=excel'
        res_xlsx = client.get(xlsx_url)
        self.assertEqual(res_xlsx.status_code, 200)
        self.assertIn('spreadsheetml', res_xlsx['Content-Type'])
        self.assertGreater(len(res_xlsx.content), 100)

    def test_quiz_edit_and_delete_audit_logging(self):
        """Verify quiz edit records field diffs and quiz delete records complete cascade stats in AuditLog."""
        client = Client()
        client.login(username='super_admin', password='AdminPassword123!')

        # 1. Edit quiz
        edit_url = reverse('dashboard:quiz_edit', kwargs={'quiz_id': self.quiz.id})
        res_edit = client.post(edit_url, {
            'title': 'Renamed Forensic Test Quiz',
            'description': 'Updated description',
            'duration_minutes': 45,
            'randomize_questions': 'on',
            'randomize_options': 'on',
            'allow_back_navigation': 'on',
            'is_proctored': 'on',
            'max_violations': 5,
            'access_code': 'SECRET123'
        })
        self.assertEqual(res_edit.status_code, 302)

        edit_audit = AuditLog.objects.filter(action='QUIZ_UPDATE', target_id=str(self.quiz.id)).first()
        self.assertIsNotNone(edit_audit)
        self.assertIn('changed_fields', edit_audit.details)
        self.assertIn('title', edit_audit.details['changed_fields'])

        # 2. Delete quiz
        del_quiz_id = self.quiz.id
        del_url = reverse('dashboard:quiz_delete', kwargs={'quiz_id': del_quiz_id})
        res_del = client.post(del_url)
        self.assertEqual(res_del.status_code, 302)

        del_audit = AuditLog.objects.filter(action='QUIZ_DELETE', target_id=str(del_quiz_id)).first()
        self.assertIsNotNone(del_audit)
        self.assertEqual(del_audit.details['title'], 'Renamed Forensic Test Quiz')
        self.assertGreaterEqual(del_audit.details['questions_count'], 3)
        self.assertGreaterEqual(del_audit.details['participations_count'], 1)
        self.assertEqual(del_audit.details['operator_username'], 'super_admin')

