/**
 * Browser-based Screen Capture (WebRTC Fallback)
 * Provides real-time display capture & streaming for candidates using standard web browsers
 * (Chrome, Edge, Firefox, Safari) where the Electron desktop wrapper is not active.
 */
class BrowserScreenCapture {
    constructor(options = {}) {
        this.quizWs = options.quizWs || null;
        this.stream = null;
        this.isStreaming = false;
        this.streamInterval = null;
        this.fps = options.fps || 3; // ~3 FPS for low latency and minimal network overhead
        this.maxWidth = options.maxWidth || 768; // Matching Electron capture width
        this.quality = options.quality || 0.45; // Low-overhead JPEG quality
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

        this._createPromptModal();
        this._bindEvents();
    }

    _bindEvents() {
        // Clean up tracks when navigating away or submitting exam
        window.addEventListener('beforeunload', () => this.cleanup());
        window.addEventListener('pagehide', () => this.cleanup());
    }

    _createPromptModal() {
        if (this.isElectron || document.getElementById('browser-screen-prompt-modal')) return;

        const modalHtml = `
        <div class="modal fade" id="browser-screen-prompt-modal" tabindex="-1" aria-labelledby="browserScreenPromptLabel" aria-hidden="true" data-bs-backdrop="static" data-bs-keyboard="false" style="z-index: 1000000;">
            <div class="modal-dialog modal-dialog-centered" style="max-width: 490px;">
                <div class="modal-content spider-card p-4 text-center" style="background: linear-gradient(145deg, #0e131d 0%, #07090e 100%); border: 1.5px solid rgba(0, 242, 254, 0.45); border-radius: 18px; box-shadow: 0 20px 60px rgba(0,0,0,0.85), 0 0 30px rgba(0, 242, 254, 0.2);">
                    <div class="mb-3">
                        <div class="d-inline-flex align-items-center justify-content-center rounded-circle" style="width: 68px; height: 68px; background: rgba(0, 242, 254, 0.12); border: 1.5px solid rgba(0, 242, 254, 0.45); box-shadow: 0 0 25px rgba(0, 242, 254, 0.25);">
                            <i class="fas fa-desktop fa-2x text-gradient"></i>
                        </div>
                    </div>
                    <h4 class="modal-title fw-bold text-light mb-2" id="browserScreenPromptLabel">Proctor Live Screen Request</h4>
                    <p class="text-secondary small mb-3">
                        The examination administrator has requested a real-time live inspection of your display. Please share your <strong>Entire Screen</strong> to proceed.
                    </p>
                    <div class="alert alert-info py-2 px-3 small text-start mb-3" style="background: rgba(0, 242, 254, 0.08); border-color: rgba(0, 242, 254, 0.25); color: #00f2fe; font-size: 0.82rem;">
                        <i class="fas fa-info-circle me-1"></i> When the browser prompt opens, choose the <strong>"Entire Screen"</strong> tab and click <strong>Share</strong>.
                    </div>
                    <div class="d-flex gap-2">
                        <button type="button" class="btn btn-cyber btn-cyber-primary w-100 py-2 fs-6 fw-bold pulse-glow" id="btn-browser-allow-screen">
                            <i class="fas fa-video me-2"></i> Share Entire Screen Now
                        </button>
                    </div>
                </div>
            </div>
        </div>`;

        const wrapper = document.createElement('div');
        wrapper.innerHTML = modalHtml;
        document.body.appendChild(wrapper.firstElementChild);

        const btnAllow = document.getElementById('btn-browser-allow-screen');
        if (btnAllow) {
            btnAllow.addEventListener('click', async () => {
                const modalEl = document.getElementById('browser-screen-prompt-modal');
                if (modalEl && window.bootstrap && bootstrap.Modal) {
                    const inst = bootstrap.Modal.getInstance(modalEl);
                    if (inst) inst.hide();
                }
                const success = await this.requestDisplayStream();
                if (success && window.__wantsLiveStream) {
                    this.startSendingFrames();
                }
            });
        }
    }

    showPromptModal() {
        if (this.isElectron) return;
        const modalEl = document.getElementById('browser-screen-prompt-modal');
        if (modalEl && window.bootstrap && bootstrap.Modal) {
            const inst = bootstrap.Modal.getOrCreateInstance(modalEl);
            inst.show();
        }
    }

    hidePromptModal() {
        const modalEl = document.getElementById('browser-screen-prompt-modal');
        if (modalEl && window.bootstrap && bootstrap.Modal) {
            const inst = bootstrap.Modal.getInstance(modalEl);
            if (inst) inst.hide();
        }
    }

    /**
     * Request screen capture stream from browser (navigator.mediaDevices.getDisplayMedia).
     * Must be invoked during a user gesture or pre-flight check.
     */
    async requestDisplayStream() {
        if (this.isElectron) return false;
        if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
            if (typeof showToast === 'function') {
                showToast('⚠️ Your browser does not support WebRTC Screen Capture.', 'warning');
            }
            return false;
        }

        try {
            this.stream = await navigator.mediaDevices.getDisplayMedia({
                video: {
                    displaySurface: 'monitor',
                    cursor: 'always',
                    frameRate: { max: 15 }
                },
                audio: false
            });

            this.video.srcObject = this.stream;
            await this.video.play().catch(() => {});

            const videoTrack = this.stream.getVideoTracks()[0];
            if (videoTrack) {
                videoTrack.onended = () => {
                    this.handleStreamEnded();
                };
            }

            this.updateUiStatus(true);
            if (typeof showToast === 'function') {
                showToast('🖥️ Screen proctoring stream connected', 'success', 3000);
            }
            return true;
        } catch (err) {
            console.warn('[WebRTC Screen Capture] User rejected or failed to acquire display media:', err);
            this.updateUiStatus(false);
            if (typeof showToast === 'function') {
                showToast('⚠️ Screen sharing is required for live proctoring.', 'warning');
            }
            return false;
        }
    }

    /**
     * Called when WebSocket receives START stream command from admin
     */
    async handleStartCommand() {
        if (this.isElectron) return;

        if (this.stream && this.stream.active) {
            this.startSendingFrames();
        } else {
            // Stream not active yet. Try requesting (if allowed by transient user activation) or show prompt modal
            try {
                const acquired = await this.requestDisplayStream();
                if (acquired) {
                    this.startSendingFrames();
                } else {
                    this.showPromptModal();
                }
            } catch (e) {
                this.showPromptModal();
            }
        }
    }

    /**
     * Called when WebSocket receives STOP stream command from admin
     */
    handleStopCommand() {
        if (this.isElectron) return;
        this.stopSendingFrames();
    }

    /**
     * Starts interval capturing frames and sending them via WebSocket
     */
    startSendingFrames() {
        if (this.isStreaming) return;
        if (!this.stream || !this.stream.active) {
            this.showPromptModal();
            return;
        }

        this.isStreaming = true;
        this.hidePromptModal();

        const intervalMs = Math.round(1000 / this.fps); // ~333ms for 3 FPS
        this.streamInterval = setInterval(() => {
            this.captureAndSendFrame();
        }, intervalMs);

        // Immediate first frame
        this.captureAndSendFrame();
        console.log('[WebRTC Screen Capture] Live streaming loop started at', this.fps, 'FPS');
    }

    /**
     * Stops sending frames (standby mode)
     */
    stopSendingFrames() {
        if (this.streamInterval) {
            clearInterval(this.streamInterval);
            this.streamInterval = null;
        }
        this.isStreaming = false;
        console.log('[WebRTC Screen Capture] Live streaming loop paused');
    }

    /**
     * Grabs current video frame, renders to canvas, converts to base64 JPEG, and sends over WS
     */
    captureAndSendFrame() {
        if (!this.isStreaming || !this.stream || !this.stream.active) return;
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

    handleStreamEnded() {
        this.stopSendingFrames();
        this.stream = null;
        this.updateUiStatus(false);
        if (typeof showToast === 'function') {
            showToast('⚠️ Screen sharing was disconnected by user.', 'danger', 6000);
        }
        if (window.antiCheat && typeof window.antiCheat._report === 'function') {
            window.antiCheat._report('WINDOW_BLUR', 'Screen sharing terminated during exam');
        }
    }

    updateUiStatus(isActive) {
        const btnText = document.getElementById('screen-share-btn-text');
        const btnIcon = document.getElementById('screen-share-btn-icon');
        const btnToggle = document.getElementById('btn-screen-share-toggle');
        if (btnText && btnIcon) {
            if (isActive) {
                btnText.textContent = 'Screen Live';
                btnIcon.className = 'fas fa-video text-success';
                if (btnToggle) btnToggle.className = 'btn btn-sm btn-cyber btn-cyber-primary';
            } else {
                btnText.textContent = 'Share Screen';
                btnIcon.className = 'fas fa-desktop text-info';
                if (btnToggle) btnToggle.className = 'btn btn-sm btn-cyber btn-cyber-outline';
            }
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
        this.updateUiStatus(false);
    }
}

window.BrowserScreenCapture = BrowserScreenCapture;

