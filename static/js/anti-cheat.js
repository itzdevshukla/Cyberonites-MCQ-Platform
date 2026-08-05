/**
 * Streamlined Anti-Cheat & Question AI Exterminator Module
 * Strictly monitors 3 real cheat vectors & obliterates AI Solver extensions (Question AI, Solvely, etc.):
 * 1. FULLSCREEN_EXIT — Exiting HTML5 Fullscreen mode.
 * 2. TAB_SWITCH — Switching browser tabs or minimizing the browser window.
 * 3. EXTENSION_DETECTED — Unauthorized browser extension iframes, Question AI overlays, or injected scripts.
 * 4. KEY_VIOLATION — Blocking ALL Ctrl+Any, Shift+Any, Alt+Any, CapsLock+Any, Tab, Win/Cmd, and F1-F12 shortcuts.
 * 
 * Special Counter-Measures:
 * - Immediate stopImmediatePropagation() on all modifier combinations.
 * - Active DOM Sentinel: Detects & purges injected extension nodes, shadow roots, and custom components.
 * - Selection clearing & click boundary protection.
 */
class AntiCheat {
    constructor(quizId, maxViolations = 3, initialViolations = 0) {
        this.quizId = quizId;
        this.maxViolations = parseInt(maxViolations) || 3;
        this.violationCount = parseInt(initialViolations) || 0;
        this.isActive = true;
        this.isSubmitting = false;
        this.isNavigating = false;
        this.reportUrl = `/quiz/${quizId}/violation/`;
        this.lastReported = {}; // Throttling map
        
        this._bindEvents();
        this._initExtensionProtection();
        this._initFullscreenEnforcement();
        this._startDomSentinel();
    }

    _bindEvents() {
        const captureOptions = { capture: true, passive: false };

        // 1. Tab switch / visibility change (100% reliable for detecting tab/window switching)
        document.addEventListener('visibilitychange', () => {
            if (document.hidden && this._canReport()) {
                this._report('TAB_SWITCH', 'Tab switched or browser window minimized');
            }
        }, captureOptions);

        // 2. Complete Blocking of Ctrl+Any, Shift+Any, Alt+Any, CapsLock+Any, Tab+Any, Win/Cmd, F1-F12
        ['keydown', 'keyup'].forEach(eventType => {
            document.addEventListener(eventType, (e) => {
                if (!this._canReport()) return;

                const rawKey = e.key || '';
                const keyUpper = rawKey.toUpperCase();
                const codeUpper = (e.code || '').toUpperCase();

                const isCtrl = e.ctrlKey || keyUpper === 'CONTROL';
                const isShift = e.shiftKey || keyUpper === 'SHIFT';
                const isAlt = e.altKey || keyUpper === 'ALT';
                const isMeta = e.metaKey || keyUpper === 'META' || keyUpper === 'OS' || codeUpper.includes('META');
                const isCapsLock = (e.getModifierState && e.getModifierState('CapsLock')) || keyUpper === 'CAPSLOCK';
                const isTab = keyUpper === 'TAB';
                const isFunctionKey = keyUpper.startsWith('F') && keyUpper.length >= 2 && !isNaN(keyUpper.substring(1));
                const isForbiddenKey = keyUpper === 'PRINTSCREEN' || keyUpper === 'SNAPSHOT' || keyUpper === 'CONTEXTMENU';

                // If ANY modifier combo or forbidden key is pressed
                if (isCtrl || isShift || isAlt || isMeta || isCapsLock || isTab || isFunctionKey || isForbiddenKey) {
                    e.preventDefault();
                    e.stopPropagation();
                    if (e.stopImmediatePropagation) {
                        e.stopImmediatePropagation();
                    }

                    if (eventType === 'keydown') {
                        let comboParts = [];
                        if (isCtrl) comboParts.push('Ctrl');
                        if (isAlt) comboParts.push('Alt');
                        if (isShift) comboParts.push('Shift');
                        if (isMeta) comboParts.push('Win/Cmd');
                        if (isCapsLock) comboParts.push('CapsLock');
                        if (isTab) comboParts.push('Tab');
                        if (!['CONTROL', 'SHIFT', 'ALT', 'META', 'CAPSLOCK', 'TAB'].includes(keyUpper)) {
                            comboParts.push(keyUpper);
                        }

                        const desc = comboParts.join(' + ') || 'Forbidden Shortcut';
                        this._report('KEY_VIOLATION', `Forbidden shortcut blocked: ${desc}`);
                    }
                    return false;
                }
            }, captureOptions);
        });

        // 3. Selection Clearing Safeguard
        ['selectionchange', 'selectstart'].forEach(evt => {
            document.addEventListener(evt, () => {
                if (!this._canReport()) return;
                const sel = window.getSelection();
                if (sel && sel.removeAllRanges) {
                    sel.removeAllRanges();
                }
            }, captureOptions);
        });

        // 4. DevTools window resize detection
        window.addEventListener('resize', () => {
            if (!this._canReport()) return;
            const threshold = 180;
            const widthDiff = window.outerWidth - window.innerWidth > threshold;
            const heightDiff = window.outerHeight - window.innerHeight > threshold;
            if (widthDiff || heightDiff) {
                this._report('DEVTOOLS', 'DevTools window dock/resize detected');
            }
        });
    }

    _initFullscreenEnforcement() {
        const overlay = document.getElementById('fullscreen-overlay');
        const btnOverlay = document.getElementById('btn-enter-fullscreen');
        const btnToggle = document.getElementById('btn-fullscreen-toggle');

        const updateFullscreenState = () => {
            const isFS = !!(document.fullscreenElement || document.webkitFullscreenElement || document.mozFullScreenElement || document.msFullscreenElement);
            if (overlay) {
                overlay.style.display = isFS ? 'none' : 'flex';
            }
            if (btnToggle) {
                btnToggle.innerHTML = isFS ? '<i class="fas fa-compress"></i> Fullscreen' : '<i class="fas fa-expand text-warning"></i> Fullscreen';
            }
            return isFS;
        };

        if (btnOverlay) {
            btnOverlay.addEventListener('click', () => {
                this.requestFullscreen();
            });
        }
        if (btnToggle) {
            btnToggle.addEventListener('click', () => {
                this.requestFullscreen();
            });
        }

        updateFullscreenState();

        ['fullscreenchange', 'webkitfullscreenchange', 'mozfullscreenchange', 'MSFullscreenChange'].forEach(evt => {
            document.addEventListener(evt, () => {
                const isFS = updateFullscreenState();
                if (!isFS && this._canReport()) {
                    this._report('FULLSCREEN_EXIT', 'Exited fullscreen mode');
                }
            });
        });
    }

    requestFullscreen() {
        const docEl = document.documentElement;
        try {
            if (docEl.requestFullscreen) {
                docEl.requestFullscreen().catch(() => {});
            } else if (docEl.webkitRequestFullscreen) {
                docEl.webkitRequestFullscreen().catch(() => {});
            } else if (docEl.msRequestFullscreen) {
                docEl.msRequestFullscreen().catch(() => {});
            }
        } catch (e) {}
    }

    _initExtensionProtection() {
        // MutationObserver to detect and instantly destroy injected extension elements / iframes
        const observer = new MutationObserver((mutations) => {
            if (!this._canReport()) return;
            for (const mutation of mutations) {
                for (const node of mutation.addedNodes) {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        this._inspectAndDestroyExtensionNode(node);
                    }
                }
            }
        });

        observer.observe(document.documentElement, {
            childList: true,
            subtree: true,
        });
        this.observer = observer;
    }

    _inspectAndDestroyExtensionNode(node) {
        if (!node || node.nodeType !== Node.ELEMENT_NODE) return;

        const tag = node.tagName ? node.tagName.toLowerCase() : '';
        const src = (node.src || '').toLowerCase();
        const id = (node.id || '').toLowerCase();
        const className = (typeof node.className === 'string' ? node.className : '').toLowerCase();
        const outerHtml = (node.outerHTML || '').toLowerCase();

        const extensionKeywords = [
            'question-ai', 'questionai', 'solvely', 'sider', 'monica', 'gauth',
            'harpa', 'chatgpt', 'copilot', 'ai-helper', 'cheat', 'chrome-extension',
            'moz-extension', 'solver', 'qai'
        ];

        let matchedKeyword = null;
        for (const kw of extensionKeywords) {
            if (id.includes(kw) || className.includes(kw) || tag.includes(kw) || src.includes(kw) || outerHtml.includes(kw)) {
                matchedKeyword = kw;
                break;
            }
        }

        const isExtensionIframe = tag === 'iframe' && (src.startsWith('chrome-extension://') || src.startsWith('moz-extension://') || src.startsWith('blob:'));
        const isCustomExtensionTag = tag.includes('-') && !tag.startsWith('bs-') && !tag.startsWith('fa-');

        if (matchedKeyword || isExtensionIframe || isCustomExtensionTag || node.shadowRoot) {
            try {
                node.remove();
            } catch (e) {}
            this._report('EXTENSION_DETECTED', `Question AI / Solver Extension detected & destroyed (${matchedKeyword || tag})`);
        }
    }

    _startDomSentinel() {
        this.sentinelTimer = setInterval(() => {
            if (!this._canReport()) return;
            const elements = document.body ? document.body.querySelectorAll('*') : [];
            elements.forEach(node => {
                if (node.tagName.toLowerCase().includes('question') ||
                    node.id.toLowerCase().includes('question') ||
                    node.id.toLowerCase().includes('solvely') ||
                    node.tagName.toLowerCase().includes('solvely') ||
                    node.tagName.toLowerCase().includes('sider') ||
                    node.shadowRoot) {
                    this._inspectAndDestroyExtensionNode(node);
                }
            });
        }, 1500);
    }

    _canReport() {
        return this.isActive && !this.isSubmitting && !this.isNavigating;
    }

    async _report(type, details) {
        if (!this._canReport()) return;

        // Throttling: Ignore exact same violation type within 3 seconds
        const now = Date.now();
        if (this.lastReported[type] && (now - this.lastReported[type] < 3000)) {
            return;
        }
        this.lastReported[type] = now;

        const expectedCount = this.violationCount + 1;
        const remaining = Math.max(0, this.maxViolations - expectedCount);

        if (remaining > 0) {
            showToast(
                `⚠️ Violation detected: ${details}. ${remaining} warning(s) remaining before auto-submit.`,
                'warning',
                5000
            );
        }

        try {
            const response = await apiFetch(this.reportUrl, {
                method: 'POST',
                body: JSON.stringify({ type, details }),
            });

            if (response && response.violation_count !== undefined) {
                this.violationCount = response.violation_count;
            }

            if (response && response.auto_submitted) {
                this.isActive = false;
                this.isSubmitting = true;
                showToast(
                    '🚫 Quiz auto-submitted due to reaching maximum violations!',
                    'error',
                    10000
                );
                setTimeout(() => {
                    window.location.href = `/dashboard/result/${this.quizId}/`;
                }, 1800);
            }
        } catch (error) {
            console.error('Failed to report anti-cheat violation:', error);
        }
    }

    destroy() {
        this.isActive = false;
        if (this.observer) {
            this.observer.disconnect();
        }
        if (this.sentinelTimer) {
            clearInterval(this.sentinelTimer);
        }
    }
}
