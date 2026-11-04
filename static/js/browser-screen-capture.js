/**
 * Mandatory Browser-based Screen Capture (WebRTC Engine)
 * Enforces strict Entire Screen sharing and continuous streaming for browser-based exams.
 * The exam remains locked behind the Mandatory Security Gate until the candidate
 * shares their Entire Screen (displaySurface === 'monitor') and enters Fullscreen mode.
 * Optimized for High-Definition crystal-clear text readability with minimal server overhead.
 */
class BrowserScreenCapture {
    constructor(options = {}) {
        this.quizWs = options.quizWs || null;
        this.stream = null;
        this.isStreaming = false;
        this.streamInterval = null;
        this.isAcquiring = false; // Mutex to strictly prevent double prompts
        this.fps = options.fps || 2.5; // ~2.5 FPS for optimal clarity & low network overhead
        this.maxWidth = options.maxWidth || 1440; // High-Definition 1440px width for razor-sharp text
        this.quality = options.quality || 0.78; // High-definition 78% JPEG (crystal clear text)
        this.isElectron = navigator.userAgent.includes('CyberonitesSecureBrowser') || !!window.__ELECTRON_ENV__;

        // Hidden video and canvas elements for continuous frame extraction
        this.video = document.createElement('video');
        this.video.autoplay = true;
        this.video.playsInline = true;
        this.video.muted = true;
        this.video.style.display = 'none';
        this.video.setAttribute('aria-hidden', 'true');
        document.body.appendChild(this.video);

        this.canvas = document.createElement('canvas');
        this.canvas.style.display = 'none';
        this.canvas.setAttribute('aria-hidden', 'true');
        document.body.appendChild(this.canvas);
        this.ctx = this.canvas.getContext('2d', { alpha: false });

        this._bindEvents();
        this._initGateState();
    }

    _bindEvents() {
        window.addEventListener('beforeunload', () => this.cleanup());
        window.addEventListener('pagehide', () => this.cleanup());
    }

    _initGateState() {
        if (this.isElectron) {
            // Electron is native fullscreen kiosk — remove gate overlay
            const gate = document.getElementById('security-gate-overlay') || document.getElementById('fullscreen-overlay');
            if (gate) gate.remove();
            return;
        }

        // Initialize gate UI on load
        setTimeout(() => this.updateGateUI(), 100);
    }

    /**
     * Strictly verifies whether an active Entire Screen stream is currently alive.
     */
    isEntireScreenActive() {
        if (this.isElectron) return true;
        if (!this.stream || !this.stream.active) return false;
        const tracks = this.stream.getVideoTracks();
        if (!tracks || tracks.length === 0 || tracks[0].readyState !== 'live') return false;

        const settings = tracks[0].getSettings ? tracks[0].getSettings() : {};
        // If browser provides displaySurface, strictly verify it is 'monitor' (Entire Screen)
        if (settings.displaySurface && settings.displaySurface !== 'monitor') {
            return false;
        }
        return true;
    }

    /**
     * Primary action called when candidate clicks "Share Entire Screen & Start Exam"
     */
    async verifyAndUnlockExam() {
        if (this.isElectron) return true;
        if (this.isAcquiring) return false;
        this.isAcquiring = true;

        try {
            this.hideGateWarning();

            // 1. If screen is not yet shared, acquire display media
            if (!this.isEntireScreenActive()) {
                const acquired = await this.requestDisplayStream();
                if (!acquired) {
                    return false;
                }
            }

            // 2. Request Fullscreen Mode
            await this.requestFullscreen();

            // 3. Update gate state and hide overlay if fully verified
            const isFS = !!(document.fullscreenElement || document.webkitFullscreenElement || document.mozFullScreenElement || document.msFullscreenElement);
            if (this.isEntireScreenActive() && isFS) {
                this.hideGateOverlay();
                // On-demand streaming: only pump frames over network when proctor is actively watching
                if (window.__wantsLiveStream) {
                    this.startSendingFrames();
                }
                if (typeof showToast === 'function') {
                    showToast('✅ Entire Screen verified. Examination unlocked!', 'success', 3500);
                }
                return true;
            } else {
                this.updateGateUI();
                return false;
            }
        } finally {
            this.isAcquiring = false;
        }
    }

    /**
     * Calls navigator.mediaDevices.getDisplayMedia and validates displaySurface === 'monitor'.
     */
    async requestDisplayStream() {
        if (this.isElectron) return true;
        if (this.isEntireScreenActive()) return true; // Already active, never prompt twice!

        if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
            this.showGateWarning('Your browser does not support the Screen Capture API. Please use Google Chrome, Microsoft Edge, or Mozilla Firefox.');
            return false;
        }

        try {
            const stream = await navigator.mediaDevices.getDisplayMedia({
                video: {
                    displaySurface: 'monitor', // Instruct browser dialog to highlight 'Entire Screen'
                    cursor: 'always',
                    frameRate: { max: 15 }
                },
                audio: false
            });

            const videoTrack = stream.getVideoTracks()[0];
            const settings = videoTrack.getSettings ? videoTrack.getSettings() : {};

            // STRICT ENTIRE SCREEN ENFORCEMENT: Reject single window or single tab
            if (settings.displaySurface && settings.displaySurface !== 'monitor') {
                videoTrack.stop();
                this.stream = null;
                this.showGateWarning('❌ Entire Screen Mode Required! You shared an application window or single tab. You MUST select "Entire Screen" in the prompt to take this quiz.');
                this.updateGateUI();
                return false;
            }

            // Text-optimized clarity hint for crisp vector text rendering
            if ('contentHint' in videoTrack) {
                videoTrack.contentHint = 'text';
            }

            // Valid Entire Screen
            this.stream = stream;
            this.video.srcObject = stream;
            await this.video.play().catch(() => {});

            videoTrack.onended = () => {
                this.handleMandatoryShareEnded();
            };

            this.updateGateUI();
            return true;

        } catch (err) {
            console.warn('[WebRTC Mandatory Screen Capture] Capture rejected or dismissed:', err);
            this.showGateWarning('Screen sharing permission was cancelled or denied. Entire Screen sharing is mandatory to take this quiz.');
            this.updateGateUI();
            return false;
        }
    }

    /**
     * Triggered if candidate clicks browser's native "Stop sharing" mid-exam
     */
    handleMandatoryShareEnded() {
        this.stopSendingFrames();
        this.stream = null;

        // Show urgent warning on gate overlay and lock the screen immediately
        this.showGateOverlay();
        this.showGateWarning('⚠️ Security Alert: Screen sharing was disconnected! Entire Screen sharing is mandatory. Re-share your Entire Screen immediately to resume.');
        this.updateGateUI();

        if (typeof showToast === 'function') {
            showToast('⚠️ Screen sharing disconnected! Examination paused.', 'danger', 7000);
        }

        // Report anti-cheat violation to proctor forensic log
        if (window.antiCheat && typeof window.antiCheat._report === 'function') {
            window.antiCheat._report('WINDOW_BLUR', 'Terminated mandatory screen share mid-exam');
        }
    }

    updateGateUI() {
        const isScreenOk = this.isEntireScreenActive();
        const isFS = !!(document.fullscreenElement || document.webkitFullscreenElement || document.mozFullScreenElement || document.msFullscreenElement);

        const screenBadge = document.getElementById('gate-screen-badge');
        const fsBadge = document.getElementById('gate-fullscreen-badge');
        const btnText = document.getElementById('btn-gate-text');
        const btnIcon = document.getElementById('btn-gate-icon');
        const pillText = document.getElementById('screen-share-btn-text');

        if (screenBadge) {
            if (isScreenOk) {
                screenBadge.className = 'badge bg-success';
                screenBadge.innerHTML = '<i class="fas fa-check-circle me-1"></i> Active (Entire Screen)';
            } else {
                screenBadge.className = 'badge bg-danger';
                screenBadge.innerHTML = '<i class="fas fa-times-circle me-1"></i> Not Shared (Mandatory)';
            }
        }

        if (fsBadge) {
            if (isFS) {
                fsBadge.className = 'badge bg-success';
                fsBadge.innerHTML = '<i class="fas fa-check-circle me-1"></i> Active';
            } else {
                fsBadge.className = 'badge bg-danger';
                fsBadge.innerHTML = '<i class="fas fa-times-circle me-1"></i> Not Fullscreen';
            }
        }

        if (btnText && btnIcon) {
            if (!isScreenOk) {
                btnText.textContent = 'Share Entire Screen & Start Exam';
                btnIcon.className = 'fas fa-desktop me-2';
            } else if (!isFS) {
                btnText.textContent = 'Enter Fullscreen Mode to Continue';
                btnIcon.className = 'fas fa-expand me-2';
            } else {
                btnText.textContent = 'Resume Examination';
                btnIcon.className = 'fas fa-play me-2';
            }
        }

        if (pillText) {
            pillText.textContent = isScreenOk ? 'Screen Live' : 'Screen Offline';
        }
    }

    showGateOverlay() {
        const overlay = document.getElementById('security-gate-overlay') || document.getElementById('fullscreen-overlay');
        if (overlay) {
            overlay.style.display = 'flex';
        }
    }

    hideGateOverlay() {
        const overlay = document.getElementById('security-gate-overlay') || document.getElementById('fullscreen-overlay');
        if (overlay) {
            overlay.style.display = 'none';
        }
    }

    showGateWarning(msg) {
        const alertEl = document.getElementById('gate-warning-alert');
        const textEl = document.getElementById('gate-warning-text');
        if (alertEl && textEl) {
            textEl.textContent = msg;
            alertEl.style.display = 'block';
        }
    }

    hideGateWarning() {
        const alertEl = document.getElementById('gate-warning-alert');
        if (alertEl) {
            alertEl.style.display = 'none';
        }
    }

    async requestFullscreen() {
        const docEl = document.documentElement;
        try {
            if (docEl.requestFullscreen) {
                await docEl.requestFullscreen();
            } else if (docEl.webkitRequestFullscreen) {
                await docEl.webkitRequestFullscreen();
            } else if (docEl.msRequestFullscreen) {
                await docEl.msRequestFullscreen();
            }
        } catch (e) {
            console.warn('[Fullscreen Request Failed]:', e);
        }
    }

    handleStartCommand() {
        if (this.isElectron) return;
        if (this.isEntireScreenActive()) {
            this.startSendingFrames();
        } else {
            this.showGateOverlay();
            this.showGateWarning('The proctor requested live inspection. Please share your Entire Screen to continue.');
        }
    }

    handleStopCommand() {
        if (this.isElectron) return;
        this.stopSendingFrames();
    }

    startSendingFrames() {
        if (this.isStreaming) return;
        if (!this.isEntireScreenActive()) return;

        this.isStreaming = true;
        const intervalMs = Math.round(1000 / this.fps);
        this.streamInterval = setInterval(() => {
            this.captureAndSendFrame();
        }, intervalMs);

        this.captureAndSendFrame();
        console.log('[WebRTC Screen Capture] HD live streaming started at', this.fps, 'FPS, maxWidth:', this.maxWidth);
    }

    stopSendingFrames() {
        if (this.streamInterval) {
            clearInterval(this.streamInterval);
            this.streamInterval = null;
        }
        this.isStreaming = false;
        console.log('[WebRTC Screen Capture] HD live streaming paused');
    }

    captureAndSendFrame() {
        if (!this.isStreaming || !this.isEntireScreenActive()) return;
        if (!this.video.videoWidth || !this.video.videoHeight) return;

        try {
            const vw = this.video.videoWidth;
            const vh = this.video.videoHeight;
            const targetW = Math.min(vw, this.maxWidth);
            const targetH = Math.round((vh / vw) * targetW);

            if (this.canvas.width !== targetW || this.canvas.height !== targetH) {
                this.canvas.width = targetW;
                this.canvas.height = targetH;
            }

            this.ctx.drawImage(this.video, 0, 0, targetW, targetH);
            const dataUrl = this.canvas.toDataURL('image/jpeg', this.quality);
            const base64Data = dataUrl.replace(/^data:image\/jpeg;base64,/, '');

            if (typeof window.__sendStreamFrame === 'function') {
                window.__sendStreamFrame(base64Data);
            }
        } catch (err) {
            console.warn('[WebRTC Screen Capture] Frame capture error:', err);
        }
    }

    cleanup() {
        this.stopSendingFrames();
        if (this.stream) {
            this.stream.getTracks().forEach(track => {
                try { track.stop(); } catch (e) {}
            });
            this.stream = null;
        }
        if (this.video) {
            this.video.srcObject = null;
        }
    }
}

window.BrowserScreenCapture = BrowserScreenCapture;
