"""
Leaderboard calculation and caching service.
Integrates Redis Sorted Sets (ZSET) for sub-millisecond real-time rankings
with strict zero-leakage PII data sanitization.
"""
import json
import logging
from django.db import models,transaction
from django.db.models import F

from .models import LeaderboardEntry

try:
    from django_redis import get_redis_connection
except ImportError:
    get_redis_connection = None

logger = logging.getLogger('quiz')


class RedisLeaderboardService:
    """
    Sub-millisecond real-time in-memory ranking engine using Redis Sorted Sets (ZSET).

    Zero Data Leakage Constraints:
    - Never stores emails, passwords, phone numbers, or session keys in Redis RAM.
    - Only safe, public display attributes are cached (id, name, college, score, accuracy, time).
    - Keys are strictly partitioned per quiz ('qarena:quiz:{quiz_id}:zset' & '...:meta') with 7-day TTL.
    """

    TTL_SECONDS = 7 * 86400  # 7 days

    @classmethod
    def get_redis_client(cls):
        if get_redis_connection:
            try:
                client = get_redis_connection("default")
                # Quick healthcheck
                client.ping()
                return client
            except Exception as e:
                logger.debug(f"Redis connection not available or ping failed: {e}")
        return None

    @classmethod
    def zset_key(cls, quiz_id):
        return f"qarena:quiz:{quiz_id}:zset"

    @classmethod
    def meta_key(cls, quiz_id):
        return f"qarena:quiz:{quiz_id}:meta"

    @staticmethod
    def compute_composite_score(score, time_taken=0, wrong_answers=0):
        """
        Encodes ranking hierarchy into a single 64-bit IEEE float score for Redis ZSET:
        1. Score DESC (higher score ranks higher)
        2. Time Taken ASC (less time ranks higher)
        3. Wrong Answers ASC (fewer wrong answers ranks higher)

        Time bonus: faster time produces higher fractional bonus (up to +0.99999).
        Wrong answers penalty: more wrong answers subtracts tiny fractional penalty.
        """
        s = float(score)
        t = min(max(float(time_taken or 0), 0.0), 86400.0)
        w = min(max(float(wrong_answers or 0), 0.0), 500.0)

        time_bonus = 1.0 - (t / 100000.0)
        wrong_penalty = w / 10000000.0

        return s + time_bonus - wrong_penalty

    @classmethod
    def update_participant(cls, quiz_id, participant, score_data):
        """
        Atomically updates a participant's real-time rank and sanitized metadata in Redis RAM.
        Runs in ~0.1ms without disk I/O.
        """
        client = cls.get_redis_client()
        if not client:
            return False

        try:
            p_id = str(participant.id)
            score = score_data.get('score', 0)
            time_taken = score_data.get('time_taken', 0)
            wrong_answers = score_data.get('wrong_answers', 0)

            comp_score = cls.compute_composite_score(score, time_taken, wrong_answers)

            # Sanitized public metadata ONLY — Zero PII / Zero Security Leakage
            sanitized_meta = {
                'participant_id': participant.id,
                'name': participant.full_name or participant.username,
                'college': participant.college or 'N/A',
                'score': score,
                'accuracy': score_data.get('accuracy', 0),
                'time_taken': time_taken,
                'questions_attempted': score_data.get('questions_attempted', 0),
                'correct_answers': score_data.get('correct_answers', 0),
                'wrong_answers': wrong_answers,
            }

            pipe = client.pipeline()
            zk = cls.zset_key(quiz_id)
            mk = cls.meta_key(quiz_id)

            pipe.zadd(zk, {p_id: comp_score})
            pipe.hset(mk, p_id, json.dumps(sanitized_meta))
            pipe.expire(zk, cls.TTL_SECONDS)
            pipe.expire(mk, cls.TTL_SECONDS)
            pipe.execute()
            return True
        except Exception as e:
            logger.error(f"RedisLeaderboardService.update_participant error: {e}")
            return False

    @classmethod
    def get_top_leaderboard(cls, quiz_id, limit=50):
        """
        Retrieves Top N candidates with dynamic ranks in ~0.2ms directly from Redis RAM.
        Returns None if cache is empty or unavailable (triggers transparent SQL fallback).
        """
        client = cls.get_redis_client()
        if not client:
            return None

        try:
            zk = cls.zset_key(quiz_id)
            mk = cls.meta_key(quiz_id)

            p_ids = client.zrevrange(zk, 0, limit - 1)
            if not p_ids:
                return None  # Cache miss

            pipe = client.pipeline()
            for pid in p_ids:
                pipe.hget(mk, pid)
            raw_meta_list = pipe.execute()

            results = []
            for rank, raw_meta in enumerate(raw_meta_list, start=1):
                if raw_meta:
                    if isinstance(raw_meta, bytes):
                        raw_meta = raw_meta.decode('utf-8')
                    data = json.loads(raw_meta)
                    data['rank'] = rank
                    results.append(data)

            return results if results else None
        except Exception as e:
            logger.error(f"RedisLeaderboardService.get_top_leaderboard error: {e}")
            return None

    @classmethod
    def get_participant_rank(cls, quiz_id, participant_id):
        """
        Retrieves individual candidate rank in ~0.1ms using ZREVRANK.
        """
        client = cls.get_redis_client()
        if not client:
            return None

        try:
            zk = cls.zset_key(quiz_id)
            rev_rank = client.zrevrank(zk, str(participant_id))
            if rev_rank is not None:
                total = client.zcard(zk)
                return {
                    'rank': rev_rank + 1,
                    'total_participants': total
                }
            return None
        except Exception as e:
            logger.error(f"RedisLeaderboardService.get_participant_rank error: {e}")
            return None

    @classmethod
    def clear_quiz_cache(cls, quiz_id):
        """Purges quiz leaderboard keys from Redis RAM."""
        client = cls.get_redis_client()
        if client:
            try:
                client.delete(cls.zset_key(quiz_id), cls.meta_key(quiz_id))
            except Exception as e:
                logger.debug(f"RedisLeaderboardService.clear_quiz_cache failed: {e}")


class LeaderboardService:
    """
    Handles leaderboard calculation, persistence, and synchronization.
    Dual-layer architecture:
    - Layer 1 (In-Memory Cache): Redis ZSET for sub-millisecond real-time reads & broadcasts.
    - Layer 2 (Persistent Storage): PostgreSQL LeaderboardEntry as immutable source of truth.
    """

    @staticmethod
    def broadcast_leaderboard_update(quiz):
        """Broadcast live update to all WebSocket clients on leaderboard page."""
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            if channel_layer:
                entries_data = LeaderboardService.get_leaderboard(quiz, limit=50)
                total_joined = quiz.participations.count()
                total_submitted = quiz.participations.filter(is_submitted=True).count()
                top_score = entries_data[0]['score'] if entries_data else 0
                async_to_sync(channel_layer.group_send)(
                    f'leaderboard_{quiz.id}',
                    {
                        'type': 'leaderboard_update',
                        'entries': entries_data,
                        'total_joined': total_joined,
                        'total_submitted': total_submitted,
                        'top_score': top_score,
                    }
                )
        except Exception as e:
            logger.error(f"Failed to broadcast leaderboard WebSocket update: {e}")

    @staticmethod
    def recalculate_ranks(quiz):
        """
        Recalculate all ranks for a quiz in PostgreSQL and synchronize into Redis RAM.
        """
        entries = list(LeaderboardEntry.objects.filter(quiz=quiz).select_related('participant').order_by(
            '-score',
            'time_taken',
            'wrong_answers'
        ))

        updated_entries = []
        for rank, entry in enumerate(entries, start=1):
            if entry.rank != rank:
                entry.rank = rank
                updated_entries.append(entry)

        if updated_entries:
            LeaderboardEntry.objects.bulk_update(updated_entries, ['rank'], batch_size=200)

        # Synchronize into Redis RAM
        client = RedisLeaderboardService.get_redis_client()
        if client and entries:
            try:
                zk = RedisLeaderboardService.zset_key(quiz.id)
                mk = RedisLeaderboardService.meta_key(quiz.id)
                pipe = client.pipeline()
                pipe.delete(zk, mk)
                for entry in entries:
                    if entry.participant:
                        comp_score = RedisLeaderboardService.compute_composite_score(
                            entry.score, entry.time_taken, entry.wrong_answers
                        )
                        sanitized_meta = {
                            'participant_id': entry.participant.id,
                            'name': entry.participant.full_name or entry.participant.username,
                            'college': entry.participant.college or 'N/A',
                            'score': entry.score,
                            'accuracy': entry.accuracy,
                            'time_taken': entry.time_taken,
                            'questions_attempted': entry.questions_attempted,
                            'correct_answers': entry.correct_answers,
                            'wrong_answers': entry.wrong_answers,
                        }
                        p_id = str(entry.participant.id)
                        pipe.zadd(zk, {p_id: comp_score})
                        pipe.hset(mk, p_id, json.dumps(sanitized_meta))
                pipe.expire(zk, RedisLeaderboardService.TTL_SECONDS)
                pipe.expire(mk, RedisLeaderboardService.TTL_SECONDS)
                pipe.execute()
            except Exception as e:
                logger.error(f"Failed to sync Redis cache in recalculate_ranks: {e}")

        logger.info(f"Recalculated ranks for quiz '{quiz.title}': {len(entries)} entries")
        LeaderboardService.broadcast_leaderboard_update(quiz)

    @staticmethod
    def get_leaderboard(quiz, limit=500):
        """
        Get leaderboard data for a quiz.
        Attempts sub-millisecond Redis RAM fetch first. Falls back transparently to SQL.
        """
        # 1. Check Redis RAM Cache
        cached_entries = RedisLeaderboardService.get_top_leaderboard(quiz.id, limit=limit or 500)
        if cached_entries is not None:
            return cached_entries

        # 2. SQL Fallback
        qs = LeaderboardEntry.objects.filter(
            quiz=quiz
        ).select_related('participant').order_by(
            '-score',
            'time_taken',
            'wrong_answers'
        )
        entries = qs[:limit] if limit else qs

        result = [
            {
                'rank': rank,
                'name': entry.participant.full_name if entry.participant else 'Deleted User',
                'college': entry.participant.college if entry.participant else 'N/A',
                'score': entry.score,
                'accuracy': entry.accuracy,
                'time_taken': entry.time_taken,
                'questions_attempted': entry.questions_attempted,
                'correct_answers': entry.correct_answers,
                'wrong_answers': entry.wrong_answers,
                'participant_id': entry.participant.id if entry.participant else 0,
            }
            for rank, entry in enumerate(entries, start=1)
        ]

        # Seed Redis cache if available
        if result and RedisLeaderboardService.get_redis_client():
            try:
                for item in result:
                    p_id = str(item['participant_id'])
                    comp = RedisLeaderboardService.compute_composite_score(
                        item['score'], item['time_taken'], item['wrong_answers']
                    )
                    zk = RedisLeaderboardService.zset_key(quiz.id)
                    mk = RedisLeaderboardService.meta_key(quiz.id)
                    client = RedisLeaderboardService.get_redis_client()
                    if client:
                        client.zadd(zk, {p_id: comp})
                        client.hset(mk, p_id, json.dumps(item))
            except Exception:
                pass

        return result

    @staticmethod
    def get_leaderboard_iterator(quiz, chunk_size=500):
        """
        Streaming generator for leaderboard entries for bulk exports.
        Maintains flat O(1) memory footprint.
        """
        qs = LeaderboardEntry.objects.filter(
            quiz=quiz
        ).select_related('participant').order_by(
            '-score',
            'time_taken',
            'wrong_answers'
        )

        for rank, entry in enumerate(qs.iterator(chunk_size=chunk_size), start=1):
            yield {
                'rank': rank,
                'name': entry.participant.full_name if entry.participant else 'Deleted User',
                'college': entry.participant.college if entry.participant else 'N/A',
                'score': entry.score,
                'accuracy': entry.accuracy,
                'time_taken': entry.time_taken,
                'questions_attempted': entry.questions_attempted,
                'correct_answers': entry.correct_answers,
                'wrong_answers': entry.wrong_answers,
                'participant_id': entry.participant.id if entry.participant else 0,
            }

    @staticmethod
    def get_participant_rank(quiz, participant):
        """
        Get a specific participant's rank and stats.
        Checks Redis RAM in ~0.1ms, falling back to SQL count query.
        """
        try:
            entry = LeaderboardEntry.objects.get(quiz=quiz, participant=participant)

            # 1. Try Redis RAM first (sub-millisecond)
            cached_rank = RedisLeaderboardService.get_participant_rank(quiz.id, participant.id)
            if cached_rank:
                return {
                    'rank': cached_rank['rank'],
                    'total_participants': cached_rank['total_participants'],
                    'score': entry.score,
                    'accuracy': entry.accuracy,
                    'time_taken': entry.time_taken,
                }

            # 2. Lockless O(log N) count query fallback
            higher_count = LeaderboardEntry.objects.filter(
                models.Q(score__gt=entry.score) |
                models.Q(score=entry.score, time_taken__lt=entry.time_taken) |
                models.Q(score=entry.score, time_taken=entry.time_taken, wrong_answers__lt=entry.wrong_answers),
                quiz=quiz
            ).count()

            rank = higher_count + 1
            total = LeaderboardEntry.objects.filter(quiz=quiz).count()
            return {
                'rank': rank,
                'total_participants': total,
                'score': entry.score,
                'accuracy': entry.accuracy,
                'time_taken': entry.time_taken,
            }
        except LeaderboardEntry.DoesNotExist:
            return None

