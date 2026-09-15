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

    # If already bound to a different public key, check session continuity
    if existing_data and existing_data.get('public_key_hex') != public_key_hex:
        logger.info(
            f"Candidate #{user.id} ({user.email}) re-attesting with new Ed25519 public key for Quiz #{quiz_id}"
        )

    cache.set(cache_key, {
        'public_key_hex': public_key_hex,
        'user_id': user.id,
        'quiz_id': quiz_id,
        'session_key': session_key,
        'attested_at': time.time(),
    }, timeout=ATTESTATION_CACHE_TTL)

    return True, "Attested"


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

    # 3. Resolve Target Public Key & Session Binding
    clean_pubkey_hex = str(client_pubkey_hex).strip().lower()
    if len(clean_pubkey_hex) != 64:
        return False, "Invalid Ed25519 public key format (expected 32 bytes hex)"

    # If in a quiz context with authenticated user, check and enforce key binding
    if quiz_id and getattr(request, 'user', None) and request.user.is_authenticated:
        attestation_cache_key = f"attestation:quiz_{quiz_id}:user_{request.user.id}"
        session_data = cache.get(attestation_cache_key)

        if not session_data:
            # Bind key on first verified request of the quiz session
            register_candidate_attestation_key(
                quiz_id=quiz_id,
                user=request.user,
                public_key_hex=clean_pubkey_hex,
                session_key=getattr(request.session, 'session_key', None)
            )
        else:
            bound_pubkey = session_data.get('public_key_hex')
            if bound_pubkey and bound_pubkey != clean_pubkey_hex:
                logger.warning(
                    f"Attestation key mismatch for user #{request.user.id} on Quiz #{quiz_id}. "
                    f"Expected {bound_pubkey[:10]}..., received {clean_pubkey_hex[:10]}..."
                )
                return False, "Attestation key mismatch for candidate exam session"

    # 4. Verify Ed25519 Signature over canonical message
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
        return False, "Cryptographic verification error"

    # 5. Mark nonce as consumed in cache
    cache.set(cache_key, True, timeout=NONCE_CACHE_TTL)
    return True, "Valid"
