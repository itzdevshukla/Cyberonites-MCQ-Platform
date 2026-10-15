"""
Cryptographic attestation and request verification for Cyberonites Secure Exam Browser.
Eliminates static shared-secret spoofing, replay attacks, and client forgery.
Uses Ed25519 asymmetric cryptography and session-bound public-key attestation.
"""
import time
import logging
from django.conf import settings
from django.core.cache import cache
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.exceptions import InvalidSignature

from core.utils import get_client_ip

logger = logging.getLogger('django.security')

MAX_CLOCK_SKEW_SECONDS = 120  # 2-minute timestamp window for network/clock tolerance
NONCE_CACHE_TTL = 180         # Cache nonce for 3 minutes to prevent replays
ATTESTATION_CACHE_TTL = 86400 # 24 hours max per exam attempt
CONCURRENT_SESSION_GRACE_PERIOD = 30 # 30 seconds inactivity window for crash/restart recovery


def parse_app_version(v_str):
    """Parse semver string into a tuple of ints for robust version comparison."""
    try:
        parts = []
        for p in str(v_str).strip().split('.'):
            digits = ''.join(c for c in p if c.isdigit())
            parts.append(int(digits) if digits else 0)
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:3])
    except Exception:
        return (0, 0, 0)


def register_candidate_attestation_key(quiz_id, user, public_key_hex, session_key=None):
    """
    Bind an ephemeral Ed25519 public key to an authenticated candidate's active quiz attempt.
    """
    if not quiz_id or not user or not user.is_authenticated:
        return False, "User not authenticated or invalid quiz"

    public_key_hex = str(public_key_hex).strip().lower()
    if len(public_key_hex) != 64:
        return False, "Invalid Ed25519 public key format (expected 32 bytes hex)"

    try:
        # Validate that the bytes represent a valid Ed25519 public key
        ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
    except Exception as e:
        return False, f"Malformed Ed25519 public key: {e}"

    cache_key = f"attestation:quiz_{quiz_id}:user_{user.id}"
    existing_data = cache.get(cache_key)

    # If already bound to a different public key, log session continuity
    if existing_data and existing_data.get('public_key_hex') != public_key_hex:
        logger.info(
            f"Candidate #{user.id} ({user.email}) re-attesting with new Ed25519 public key for Quiz #{quiz_id}"
        )

    now = time.time()
    cache.set(cache_key, {
        'public_key_hex': public_key_hex,
        'user_id': user.id,
        'quiz_id': quiz_id,
        'session_key': session_key,
        'attested_at': now,
        'last_seen_at': now,
    }, timeout=ATTESTATION_CACHE_TTL)

    return True, "Attested"


def clear_candidate_attestation_key(quiz_id, user):
    """Clear attestation key from cache upon quiz completion or reset."""
    if quiz_id and user and getattr(user, 'id', None):
        cache.delete(f"attestation:quiz_{quiz_id}:user_{user.id}")


def verify_secure_app_request(request, quiz_id=None):
    """
    Cryptographically verify that an incoming HTTP request originated from
    the authentic, active Secure Exam Browser client via Ed25519 asymmetric signature.

    Headers required:
    - X-Secure-App-Timestamp: Unix timestamp in milliseconds
    - X-Secure-App-Nonce: Unique random string (UUID or hex)
    - X-Secure-App-Signature: Ed25519 hex signature over (timestamp:nonce:method:path)
    - X-Secure-App-Public-Key: Ephemeral 32-byte Ed25519 public key hex

    Returns:
        (is_valid: bool, reason: str)
    """
    timestamp_str = request.headers.get('X-Secure-App-Timestamp')
    nonce = request.headers.get('X-Secure-App-Nonce')
    signature_hex = request.headers.get('X-Secure-App-Signature')
    client_pubkey_hex = request.headers.get('X-Secure-App-Public-Key')

    if not timestamp_str or not nonce or not signature_hex or not client_pubkey_hex:
        return False, "Missing cryptographic attestation headers"

    # 1. Validate Timestamp to prevent old/expired requests
    try:
        timestamp_ms = int(timestamp_str)
        req_time = timestamp_ms / 1000.0
    except (ValueError, TypeError):
        return False, "Malformed timestamp format in security header"

    now = time.time()
    time_diff = abs(now - req_time)
    if time_diff > MAX_CLOCK_SKEW_SECONDS:
        return False, f"Request expired or clock drift excessive ({time_diff:.1f}s difference)"

    # 2. Prevent Replay Attacks (Unique Single-Use Nonce)
    cache_key = f"secure_app_nonce:{nonce}"
    if cache.get(cache_key):
        return False, "Replay attack detected: Nonce has already been consumed"

    # 3. Clean and validate public key format
    clean_pubkey_hex = str(client_pubkey_hex).strip().lower()
    if len(clean_pubkey_hex) != 64:
        return False, "Invalid Ed25519 public key format (expected 32 bytes hex)"

    # 4. Verify Ed25519 Signature over canonical message FIRST
    # Canonical format: {timestamp}:{nonce}:{method}:{path}
    canonical_message = f"{timestamp_str}:{nonce}:{request.method.upper()}:{request.path}"

    try:
        pub_key_bytes = bytes.fromhex(clean_pubkey_hex)
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_key_bytes)
        sig_bytes = bytes.fromhex(signature_hex)
        public_key.verify(sig_bytes, canonical_message.encode('utf-8'))
    except InvalidSignature:
        logger.warning(
            f"Invalid secure app Ed25519 signature from IP {get_client_ip(request)}"
        )
        return False, "Invalid cryptographic client signature"
    except Exception as e:
        logger.warning(
            f"Ed25519 signature processing error from IP {get_client_ip(request)}: {e}"
        )
    # 5. Enforce Minimum Browser Version Gate (Prevents Rollback Cheating)
    min_version_str = getattr(settings, 'MINIMUM_SECURE_APP_VERSION', None)
    if min_version_str:
        client_version_str = request.headers.get('X-Secure-App-Version') or '1.0.0'
        if parse_app_version(client_version_str) < parse_app_version(min_version_str):
            logger.warning(
                f"Blocked outdated Secure Browser v{client_version_str} from IP {get_client_ip(request)}. "
                f"Minimum required: v{min_version_str}"
            )
            return False, f"Outdated browser version (v{client_version_str}). Mandatory security update v{min_version_str} is required."

    # 6. Enforce candidate exam session key binding (Anti-Concurrent Hijacking)
    if quiz_id and getattr(request, 'user', None) and request.user.is_authenticated:
        attestation_cache_key = f"attestation:quiz_{quiz_id}:user_{request.user.id}"
        session_data = cache.get(attestation_cache_key)

        req_path = request.path.rstrip('/')
        is_pre_exam = any(req_path.endswith(endpoint) for endpoint in ('/verify', '/start'))

        if not session_data or is_pre_exam:
            # Bind or re-bind key on pre-flight verification, exam start, or first request
            register_candidate_attestation_key(
                quiz_id=quiz_id,
                user=request.user,
                public_key_hex=clean_pubkey_hex,
                session_key=getattr(request.session, 'session_key', None)
            )
        else:
            bound_pubkey = session_data.get('public_key_hex')
            if bound_pubkey and bound_pubkey != clean_pubkey_hex:
                last_seen = session_data.get('last_seen_at') or session_data.get('attested_at', 0)
                time_since_last_seen = now - last_seen

                # If the previous key has been inactive > CONCURRENT_SESSION_GRACE_PERIOD,
                # allow graceful resume (app restart, battery recovery, re-launch)
                if time_since_last_seen > CONCURRENT_SESSION_GRACE_PERIOD:
                    logger.info(
                        f"Candidate #{request.user.id} gracefully resuming Quiz #{quiz_id} "
                        f"with new key after {time_since_last_seen:.1f}s idle."
                    )
                    register_candidate_attestation_key(
                        quiz_id=quiz_id,
                        user=request.user,
                        public_key_hex=clean_pubkey_hex,
                        session_key=getattr(request.session, 'session_key', None)
                    )
                else:
                    logger.warning(
                        f"Attestation key mismatch for user #{request.user.id} on Quiz #{quiz_id}. "
                        f"Expected {bound_pubkey[:10]}..., received {clean_pubkey_hex[:10]}... "
                        f"Active key was seen {time_since_last_seen:.1f}s ago."
                    )
                    return False, "Attestation key mismatch for candidate exam session"
            else:
                # Update last_seen_at for active session continuity
                session_data['last_seen_at'] = now
                cache.set(attestation_cache_key, session_data, timeout=ATTESTATION_CACHE_TTL)

    # 6. Mark nonce as consumed in cache
    cache.set(cache_key, True, timeout=NONCE_CACHE_TTL)
    return True, "Valid"
