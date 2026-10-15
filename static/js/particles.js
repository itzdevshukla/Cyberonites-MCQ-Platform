/**
 * Qarena — Clean 2D Background Architecture
 * Replaced 3D particle canvas with a zero-overhead, clean 2D technical background.
 */
document.addEventListener('DOMContentLoaded', () => {
    const existingCanvas = document.getElementById('cyber-canvas');
    if (existingCanvas) {
        existingCanvas.remove();
    }
});
