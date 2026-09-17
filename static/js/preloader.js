/**
 * Qarena Cinematic Fullscreen Loader
 * Cycles 3 high-resolution background images smoothly,
 * with a clean, minimal edge-to-edge bottom progress line (corner to corner),
 * and zero clutter in the center.
 */
(function() {
    var STORAGE_KEY = 'qarena_intro_shown';

    function initPreloader() {
        var preloader = document.getElementById('qarena-intro-preloader');
        if (!preloader) return;

        // Check query param (?replay_intro=1 or ?intro=1) to allow testing preview
        var allowReplay = false;
        try {
            var urlParams = new URLSearchParams(window.location.search);
            if (urlParams.has('replay_intro') || urlParams.has('intro')) {
                allowReplay = true;
                sessionStorage.removeItem(STORAGE_KEY);
            }
        } catch (e) {}

        // If already shown in this session, remove immediately and do NOT show on refresh
        try {
            if (!allowReplay && sessionStorage.getItem(STORAGE_KEY)) {
                if (preloader.parentNode) {
                    preloader.parentNode.removeChild(preloader);
                }
                document.body.classList.remove('intro-active');
                return;
            }
            // Mark as shown immediately so any refresh or fast navigation won't re-trigger it
            sessionStorage.setItem(STORAGE_KEY, 'true');
        } catch (e) {
            // Storage access fallback
        }

        // Display preloader for the first visit
        preloader.style.display = 'flex';
        document.body.classList.add('intro-active');

        var bgLayers = [
            preloader.querySelector('.intro-bg-1'),
            preloader.querySelector('.intro-bg-2'),
            preloader.querySelector('.intro-bg-3')
        ];
        var progressBar = document.getElementById('intro-progress-bar');

        var startTime = null;
        var totalDuration = 3000; // 3.0 seconds smooth cycle
        var completed = false;

        function updateBackground(index) {
            for (var i = 0; i < bgLayers.length; i++) {
                if (bgLayers[i]) {
                    if (i === index) {
                        bgLayers[i].classList.add('active');
                    } else {
                        bgLayers[i].classList.remove('active');
                    }
                }
            }
        }

        function finishIntro() {
            if (completed) return;
            completed = true;

            if (progressBar) progressBar.style.width = '100%';

            preloader.classList.add('preloader-fade-out');
            setTimeout(function() {
                if (preloader.parentNode) {
                    preloader.parentNode.removeChild(preloader);
                }
                document.body.classList.remove('intro-active');
            }, 600);
        }

        function step(timestamp) {
            if (completed) return;
            if (!startTime) startTime = timestamp;
            var elapsed = timestamp - startTime;
            var progress = Math.min(100, (elapsed / totalDuration) * 100);

            if (progressBar) progressBar.style.width = progress + '%';

            // Cycle 3 background images:
            // 0% - 33%: Image 1
            // 34% - 66%: Image 2
            // 67% - 100%: Image 3
            if (progress < 34) {
                updateBackground(0);
            } else if (progress < 67) {
                updateBackground(1);
            } else {
                updateBackground(2);
            }

            if (elapsed < totalDuration) {
                requestAnimationFrame(step);
            } else {
                finishIntro();
            }
        }

        requestAnimationFrame(step);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initPreloader);
    } else {
        initPreloader();
    }
})();
