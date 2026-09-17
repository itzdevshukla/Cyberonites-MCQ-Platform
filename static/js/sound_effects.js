/**
 * Qarena Spider-Man Web Shoot Audio Manager
 * Plays authentic web-shoot sound effect on interactive clicks.
 */
(function() {
    var AUDIO_SRC = '/static/audio/web_shoot.mp3';
    
    // Pre-allocated audio pool for instant zero-latency concurrent playback
    var POOL_SIZE = 6;
    var audioPool = [];
    var poolIndex = 0;

    try {
        for (var i = 0; i < POOL_SIZE; i++) {
            var sound = new Audio(AUDIO_SRC);
            sound.preload = 'auto';
            sound.volume = 0.65;
            audioPool.push(sound);
        }
    } catch (e) {
        console.warn('Web shoot audio pool initialization skipped:', e);
    }

    function playWebShoot() {
        if (!audioPool.length) return;
        try {
            var sound = audioPool[poolIndex];
            poolIndex = (poolIndex + 1) % POOL_SIZE;
            sound.currentTime = 0;
            var promise = sound.play();
            if (promise !== undefined) {
                promise.catch(function() {
                    // Browser prevented audio before interaction
                });
            }
        } catch (err) {}
    }

    // Global click listener using capture phase for immediate responsiveness
    document.addEventListener('click', function(e) {
        if (!e.target) return;
        var interactive = e.target.closest(
            'button, a, .btn, input[type="submit"], input[type="button"], input[type="radio"], input[type="checkbox"], ' +
            '[role="button"], .option-label, .option-card, .nav-link, .dropdown-item, .footer-social-btn, .page-link, ' +
            '.btn-cyber, .auth-btn, .hero-telemetry-pill, summary'
        );

        if (interactive) {
            playWebShoot();
        }
    }, true);

    // Expose helper globally
    window.playWebShootSound = playWebShoot;
})();
