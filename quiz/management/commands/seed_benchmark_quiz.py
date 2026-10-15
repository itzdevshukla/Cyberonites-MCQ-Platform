"""
Django management command to seed a benchmark quiz for 200-concurrent-user load validation.
Safe and idempotent.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from quiz.models import Quiz, Question, Option


class Command(BaseCommand):
    help = "Seeds a clean synthetic benchmark quiz with realistic MCQ questions for 200-user concurrency testing."

    def add_arguments(self, parser):
        parser.add_argument(
            '--questions',
            type=int,
            default=20,
            help='Number of questions to seed in the benchmark quiz (default: 20)'
        )
        parser.add_argument(
            '--duration',
            type=int,
            default=60,
            help='Quiz duration in minutes (default: 60)'
        )
        parser.add_argument(
            '--proctored',
            action='store_true',
            default=False,
            help='Enable proctoring requirements (default: False for open browser benchmark)'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            default=False,
            help='Force recreation of the benchmark quiz if it already exists'
        )

    def handle(self, *args, **options):
        num_questions = options['questions']
        duration_minutes = options['duration']
        is_proctored = options['proctored']
        force = options['force']

        benchmark_title = "200-User Concurrent Exam Benchmark"

        existing_quiz = Quiz.objects.filter(title=benchmark_title).first()
        if existing_quiz:
            if force:
                self.stdout.write(self.style.WARNING(f"Removing existing benchmark quiz (ID: {existing_quiz.id})..."))
                existing_quiz.delete()
            else:
                # Ensure it is ACTIVE
                if existing_quiz.status != 'ACTIVE':
                    existing_quiz.status = 'ACTIVE'
                    existing_quiz.save(update_fields=['status'])
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Benchmark quiz already exists (ID: {existing_quiz.id}) with {existing_quiz.questions.count()} questions. "
                        f"Status: {existing_quiz.status}, Proctored: {existing_quiz.is_proctored}"
                    )
                )
                return

        self.stdout.write(f"Creating new benchmark quiz '{benchmark_title}' with {num_questions} questions...")

        with transaction.atomic():
            quiz = Quiz.objects.create(
                title=benchmark_title,
                description=(
                    "Standardized concurrent examination for performance benchmarking, "
                    "database concurrency validation, and answer durability testing."
                ),
                duration_minutes=duration_minutes,
                status='ACTIVE',
                start_time=timezone.now(),
                end_time=timezone.now() + timezone.timedelta(hours=24),
                randomize_questions=True,
                randomize_options=True,
                allow_back_navigation=True,
                is_proctored=is_proctored,
                max_violations=5 if is_proctored else 0,
                access_code='',
                enable_question_timer=False,
            )

            # Bank of realistic Computer Science and Systems topics
            sample_topics = [
                ("Operating Systems", "What is the primary role of a translation lookaside buffer (TLB)?",
                 [("A", "Cache virtual-to-physical address translations", True),
                  ("B", "Store disk blocks in RAM", False),
                  ("C", "Manage page replacement algorithms", False),
                  ("D", "Schedule thread executions on CPU cores", False)]),

                ("Computer Networks", "Which TCP mechanism prevents network congestion by throttling sender window size?",
                 [("A", "Congestion Avoidance and Fast Retransmit", True),
                  ("B", "Checksum error detection", False),
                  ("C", "Maximum Segment Size negotiation", False),
                  ("D", "Subnet mask translation", False)]),

                ("Databases", "In PostgreSQL, which transaction isolation level prevents phantom reads?",
                 [("A", "Serializable", True),
                  ("B", "Read Committed", False),
                  ("C", "Read Uncommitted", False),
                  ("D", "Repeatable Read without predicate locks", False)]),

                ("Algorithms", "What is the time complexity of searching an element in a balanced AVL tree with N nodes?",
                 [("A", "O(log N)", True),
                  ("B", "O(N)", False),
                  ("C", "O(1)", False),
                  ("D", "O(N log N)", False)]),

                ("Security", "Which header protects web applications from clickjacking attacks?",
                 [("A", "X-Frame-Options: DENY", True),
                  ("B", "Access-Control-Allow-Origin: *", False),
                  ("C", "Strict-Transport-Security: max-age=0", False),
                  ("D", "X-Content-Type-Options: nosniff", False)]),
            ]

            for i in range(1, num_questions + 1):
                topic_data = sample_topics[(i - 1) % len(sample_topics)]
                topic, question_prompt, options_list = topic_data

                q_text = f"Q{i}: {question_prompt}"
                question = Question.objects.create(
                    quiz=quiz,
                    text=q_text,
                    topic=topic,
                    difficulty='MEDIUM',
                    order=i,
                    marks=1,
                    negative_marks=0.0,
                )

                for label, opt_text, is_corr in options_list:
                    Option.objects.create(
                        question=question,
                        label=label,
                        text=opt_text,
                        is_correct=is_corr,
                    )

            quiz.recalculate_total_marks()

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully seeded benchmark quiz!\n"
                f"   - Quiz ID: {quiz.id}\n"
                f"   - Title: {quiz.title}\n"
                f"   - Questions: {quiz.questions.count()}\n"
                f"   - Total Marks: {quiz.total_marks}\n"
                f"   - Proctored: {quiz.is_proctored}\n"
                f"   - Status: {quiz.status}"
            )
        )
