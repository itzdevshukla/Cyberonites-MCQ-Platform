"""
Audit logging service for security, administrative, and lifecycle actions.
"""
import logging
from core.models import AuditLog
from core.utils import get_client_ip

logger = logging.getLogger('audit')


def log_audit_event(
    request=None,
    actor=None,
    action=None,
    target_model='',
    target_id='',
    details=None
):
    """
    Record an immutable security audit trail event in the database.
    
    Args:
        request: HttpRequest object (optional, extracts actor, IP, User-Agent)
        actor: Explicit user/participant object if request not provided or overridden
        action: AuditLog.ACTION_CHOICES action string (e.g. 'QUIZ_CREATE', 'QUIZ_STOP')
        target_model: Name of the impacted model (e.g. 'Quiz', 'Question')
        target_id: String identifier/PK of the target entity
        details: Dict of additional forensic context (parameters, before/after diffs)
    
    Returns:
        AuditLog instance or None if an error occurs.
    """
    if not action:
        logger.warning("Attempted to log audit event without action specified.")
        return None

    try:
        resolved_actor = None
        actor_email = ''
        ip_address = None
        user_agent = ''

        if request is not None:
            if hasattr(request, 'user') and request.user.is_authenticated:
                resolved_actor = request.user
                actor_email = getattr(request.user, 'email', '') or str(request.user)
            ip_address = get_client_ip(request)
            user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]

        if actor is not None:
            resolved_actor = actor
            actor_email = getattr(actor, 'email', '') or str(actor)

        if not actor_email and resolved_actor:
            actor_email = getattr(resolved_actor, 'email', '')

        if details is None:
            details = {}

        audit_entry = AuditLog.objects.create(
            actor=resolved_actor,
            actor_email=actor_email,
            action=action,
            target_model=target_model,
            target_id=str(target_id) if target_id is not None else '',
            details=details,
            ip_address=ip_address,
            user_agent=user_agent
        )

        logger.info(
            f"[AUDIT] {action} by {actor_email or 'ANONYMOUS'} "
            f"on {target_model}:{target_id} from IP {ip_address or 'UNKNOWN'}"
        )
        return audit_entry

    except Exception as e:
        logger.error(f"Failed to record audit log for action {action}: {e}", exc_info=True)
        return None
