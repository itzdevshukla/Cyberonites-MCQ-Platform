/**
 * Client-side Timer (synced with server)
 * Visual countdown only — server is the source of truth.
 * Last 60 seconds: flash animation, color change, beep sound.
 */
class QuizTimer {
    constructor(initialSeconds, onTick, onExpire) {
        this.remaining = initialSeconds;
        this.onTick = onTick;
        this.onExpire = onExpire;
        this.interval = null;
        this.isPaused = false;
        this.hasPlayedWarning = false;
        this.audioContext = null;
    }

    start() {
        if (this.interval) clearInterval(this.interval);
        
        // Immediate initial tick
        if (this.onTick) this.onTick(this.remaining);

        this.interval = setInterval(() => {
            if (this.isPaused) return;
            
            if (this.remaining <= 0) {
                this.remaining = 0;
                this.stop();
                if (this.onExpire) this.onExpire();
                return;
            }

            this.remaining--;
            
            // Last 60 seconds warning effects
            if (this.remaining <= 60 && this.remaining > 0) {
                this._triggerWarning();
            }

            if (this.onTick) this.onTick(this.remaining);
        }, 1000);
    }

    stop() {
        if (this.interval) {
            clearInterval(this.interval);
            this.interval = null;
        }
    }

    pause() {
        this.isPaused = true;
    }

    resume() {
        this.isPaused = false;
    }

    sync(serverSeconds) {
        // Sync with server time
        this.remaining = serverSeconds;
        if (this.onTick) this.onTick(this.remaining);
        if (this.remaining > 0 && !this.interval && !this.isPaused) {
            this.start();
        }
    }



    _triggerWarning() {
        const timerEl = document.getElementById('quiz-timer');
        if (!timerEl) return;

        // Flash animation
        timerEl.classList.add('timer-warning');

        // Color pulse every 10 seconds in last minute
        if (this.remaining <= 10) {
            timerEl.classList.add('timer-critical');
        }

        // Play beep at key moments
        if ([60, 30, 10, 5, 4, 3, 2, 1].includes(this.remaining)) {
            this._playBeep(this.remaining <= 10 ? 800 : 600);
        }
    }

    _playBeep(frequency = 600) {
        try {
            if (!this.audioContext) {
                this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            }
            const oscillator = this.audioContext.createOscillator();
            const gainNode = this.audioContext.createGain();
            
            oscillator.connect(gainNode);
            gainNode.connect(this.audioContext.destination);
            
            oscillator.frequency.value = frequency;
            oscillator.type = 'sine';
            gainNode.gain.value = 0.1;
            
            oscillator.start();
            oscillator.stop(this.audioContext.currentTime + 0.15);
        } catch (e) {
            // Audio not available — fail silently
        }
    }
}
