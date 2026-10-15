from django.apps import AppConfig
import logging

logger = logging.getLogger('quiz')


class QuizConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'quiz'
    verbose_name = 'Quiz Engine'

    def ready(self):
        """Auto-heal missing database columns on server startup to prevent 500 errors if migrations were skipped."""
        from django.db import connection
        try:
            with connection.cursor() as cursor:
                vendor = connection.vendor
                if vendor == 'postgresql':
                    cursor.execute("""
                        ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS enable_question_timer boolean DEFAULT false;
                        ALTER TABLE quizzes ADD COLUMN IF NOT EXISTS question_timer_seconds integer DEFAULT 20;
                        ALTER TABLE questions ADD COLUMN IF NOT EXISTS timer_seconds integer;
                        DO $$ 
                        BEGIN 
                            BEGIN
                                ALTER TABLE quiz_participations ADD COLUMN IF NOT EXISTS question_timings jsonb DEFAULT '{}'::jsonb;
                            EXCEPTION WHEN undefined_table THEN 
                                NULL;
                            END;
                            BEGIN
                                ALTER TABLE quizparticipations ADD COLUMN IF NOT EXISTS question_timings jsonb DEFAULT '{}'::jsonb;
                            EXCEPTION WHEN undefined_table THEN 
                                NULL;
                            END;
                        END $$;
                    """)
                elif vendor == 'sqlite':
                    # SQLite fallback
                    try:
                        cursor.execute("ALTER TABLE quizzes ADD COLUMN enable_question_timer bool DEFAULT 0")
                    except Exception:
                        pass
                    try:
                        cursor.execute("ALTER TABLE quizzes ADD COLUMN question_timer_seconds integer DEFAULT 20")
                    except Exception:
                        pass
                    try:
                        cursor.execute("ALTER TABLE questions ADD COLUMN timer_seconds integer")
                    except Exception:
                        pass
        except Exception as e:
            # Silent fallback during collectstatic or initial bootstrap
            pass

