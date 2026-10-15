/**
 * Shared Utilities
 * CSRF helper, fetch wrapper, toast notifications.
 */

// Get CSRF token from cookie
function getCSRFToken() {
    const name = 'csrftoken';
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        cookie = cookie.trim();
        if (cookie.startsWith(name + '=')) {
            return decodeURIComponent(cookie.substring(name.length + 1));
        }
    }
    return '';
}

// Fetch wrapper with CSRF and JSON support
async function apiFetch(url, options = {}) {
    const defaults = {
        headers: {
            'X-CSRFToken': getCSRFToken(),
            'X-Requested-With': 'XMLHttpRequest',
            'Content-Type': 'application/json',
        },
        credentials: 'same-origin',
    };

    const config = { ...defaults, ...options };
    if (options.headers) {
        config.headers = { ...defaults.headers, ...options.headers };
    }

    try {
        const response = await fetch(url, config);
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            const err = new Error(errorData.error || `HTTP ${response.status}`);
            err.data = errorData;
            err.status = response.status;
            throw err;
        }
        return await response.json();
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

// Toast notification system
function showToast(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toast-container') || createToastContainer();
    
    const toast = document.createElement('div');
    toast.className = `cyber-toast cyber-toast-${type}`;
    
    const icons = {
        success: 'fas fa-check-circle',
        error: 'fas fa-exclamation-circle',
        warning: 'fas fa-exclamation-triangle',
        info: 'fas fa-info-circle',
    };

    toast.innerHTML = `
        <div class="toast-icon"><i class="${icons[type] || icons.info}"></i></div>
        <div class="toast-message">${message}</div>
    `;

    container.appendChild(toast);
    
    // Animate in
    requestAnimationFrame(() => toast.classList.add('show'));

    // Auto remove
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

function createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
    return container;
}

// Format seconds to HH:MM:SS (if >= 1 hour) or MM:SS
function formatTime(seconds) {
    if (seconds <= 0) return '00:00';
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    if (hours > 0) {
        return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    }
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

// Debounce function
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

// Global Cyber Exam App Exit Modal
window.__showCyberExitModal = function() {
    if (document.getElementById('cyberonites-exit-modal-overlay')) return;
    console.log('__APP:MODAL_OPENED__');

    const overlay = document.createElement('div');
    overlay.id = 'cyberonites-exit-modal-overlay';
    overlay.style.cssText = 'position: fixed !important; inset: 0 !important; width: 100vw !important; height: 100vh !important; background: rgba(4, 8, 16, 0.85) !important; backdrop-filter: blur(14px) !important; -webkit-backdrop-filter: blur(14px) !important; z-index: 2147483647 !important; display: flex !important; align-items: center !important; justify-content: center !important; animation: cyberExitFadeIn 0.2s ease-out !important; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Inter", sans-serif !important;';

    overlay.innerHTML = `
        <div style="background: linear-gradient(145deg, #111827, #0b0f19) !important; border: 1px solid rgba(255, 71, 87, 0.45) !important; border-radius: 18px !important; padding: 34px 38px !important; max-width: 440px !important; width: 90% !important; text-align: center !important; box-shadow: 0 25px 60px rgba(0, 0, 0, 0.85), 0 0 35px rgba(255, 71, 87, 0.25) !important; animation: cyberExitScale 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;">
            <div style="width: 58px !important; height: 58px !important; margin: 0 auto 18px !important; background: rgba(255, 71, 87, 0.12) !important; border: 1px solid rgba(255, 71, 87, 0.35) !important; border-radius: 50% !important; display: flex !important; align-items: center !important; justify-content: center !important; color: #ff4757 !important; box-shadow: 0 0 20px rgba(255, 71, 87, 0.25) !important;">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
                    <polyline points="16 17 21 12 16 7"></polyline>
                    <line x1="21" y1="12" x2="9" y2="12"></line>
                </svg>
            </div>
            <h3 style="margin: 0 0 10px !important; color: #ffffff !important; font-size: 20px !important; font-weight: 700 !important; letter-spacing: -0.3px !important;">Exit Secure Exam Browser?</h3>
            <p style="margin: 0 0 26px !important; color: #94a3b8 !important; font-size: 13.5px !important; line-height: 1.55 !important;">
                Exiting will immediately terminate your active examination session and forfeit unsubmitted answers. Are you sure you want to exit?
            </p>
            <div style="display: flex !important; gap: 14px !important; justify-content: center !important;">
                <button id="cyber-exit-cancel-btn" type="button" style="flex: 1 !important; padding: 12px 18px !important; border-radius: 10px !important; background: rgba(255, 255, 255, 0.08) !important; border: 1px solid rgba(255, 255, 255, 0.15) !important; color: #e2e8f0 !important; font-size: 13.5px !important; font-weight: 600 !important; cursor: pointer !important; transition: all 0.2s ease !important;">Stay in Exam</button>
                <button id="cyber-exit-confirm-btn" type="button" style="flex: 1 !important; padding: 12px 18px !important; border-radius: 10px !important; background: linear-gradient(135deg, #ef4444, #dc2626) !important; border: 1px solid #f87171 !important; color: #ffffff !important; font-size: 13.5px !important; font-weight: 600 !important; cursor: pointer !important; transition: all 0.2s ease !important; box-shadow: 0 4px 15px rgba(239, 68, 68, 0.4) !important;">Exit Application</button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);

    const cancelBtn = overlay.querySelector('#cyber-exit-cancel-btn');
    const confirmBtn = overlay.querySelector('#cyber-exit-confirm-btn');

    cancelBtn.onmouseenter = () => { cancelBtn.style.background = 'rgba(255, 255, 255, 0.14)'; };
    cancelBtn.onmouseleave = () => { cancelBtn.style.background = 'rgba(255, 255, 255, 0.08)'; };

    confirmBtn.onmouseenter = () => { confirmBtn.style.transform = 'translateY(-1px)'; confirmBtn.style.boxShadow = '0 6px 20px rgba(239, 68, 68, 0.55)'; };
    confirmBtn.onmouseleave = () => { confirmBtn.style.transform = 'none'; confirmBtn.style.boxShadow = '0 4px 15px rgba(239, 68, 68, 0.4)'; };

    const closeModal = () => {
        document.removeEventListener('keydown', escHandler);
        if (overlay && overlay.parentNode) {
            overlay.remove();
        }
        console.log('__APP:CANCEL_EXIT__');
    };

    const escHandler = (e) => {
        if (e.key === 'Escape') {
            closeModal();
        }
    };
    document.addEventListener('keydown', escHandler);

    cancelBtn.onclick = closeModal;

    confirmBtn.onclick = () => {
        confirmBtn.disabled = true;
        confirmBtn.innerText = 'Exiting...';
        console.log('__APP:CONFIRM_EXIT__');
    };
};

