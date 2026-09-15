/**
 * Admin Controls
 * Quiz start/stop/pause/resume/extend via AJAX.
 */
class AdminControls {
    constructor(quizId) {
        this.quizId = quizId;
        this.controlUrl = `/dashboard/quizzes/${quizId}/control/action/`;
        this._bindEvents();
    }

    _bindEvents() {
        document.querySelectorAll('[data-action]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const action = btn.dataset.action;
                
                if (action === 'stop') {
                    if (!confirm('Stop quiz? All pending submissions will be auto-submitted.')) return;
                }
                
                this.execute(action, btn);
            });
        });
    }

    async execute(action, btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing...';

        const formData = new FormData();
        formData.append('action', action);

        if (action === 'extend') {
            const minutes = document.getElementById('extend-minutes')?.value || 5;
            formData.append('extra_minutes', minutes);
        }

        if (action === 'resume') {
            const remaining = document.getElementById('remaining-display')?.dataset.remaining || 0;
            formData.append('remaining_seconds', remaining);
        }

        try {
            const response = await fetch(this.controlUrl, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-CSRFToken': getCSRFToken(),
                    'X-Requested-With': 'XMLHttpRequest',
                },
                credentials: 'same-origin',
            });

            const data = await response.json();
            showToast(`Quiz ${action} successful!`, 'success');
            
            // Reload page to reflect new state
            setTimeout(() => location.reload(), 1000);
        } catch (error) {
            showToast(`Failed to ${action} quiz.`, 'error');
            btn.disabled = false;
        }
    }
}

// Announcement broadcast
async function sendAnnouncement(quizId) {
    const input = document.getElementById('announcement-input');
    const message = input?.value?.trim();
    if (!message) return;

    try {
        await apiFetch(`/dashboard/quizzes/${quizId}/announce/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCSRFToken(),
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: `message=${encodeURIComponent(message)}`,
        });
        input.value = '';
        showToast('Announcement sent!', 'success');
    } catch (error) {
        showToast('Failed to send announcement.', 'error');
    }
}
