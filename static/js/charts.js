/**
 * Chart.js result visualizations.
 */
function renderResultCharts(data) {
    // Score Distribution Donut
    const scoreCtx = document.getElementById('score-chart');
    if (scoreCtx) {
        new Chart(scoreCtx, {
            type: 'doughnut',
            data: {
                labels: ['Correct', 'Incorrect', 'Skipped'],
                datasets: [{
                    data: [data.correct, data.wrong, data.skipped],
                    backgroundColor: [
                        'rgba(0, 255, 136, 0.8)',
                        'rgba(255, 71, 87, 0.8)',
                        'rgba(108, 99, 255, 0.4)',
                    ],
                    borderColor: [
                        'rgba(0, 255, 136, 1)',
                        'rgba(255, 71, 87, 1)',
                        'rgba(108, 99, 255, 0.6)',
                    ],
                    borderWidth: 2,
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { color: '#e0e0e0', font: { size: 13 } }
                    }
                },
                cutout: '65%',
            }
        });
    }

    // Performance Radar
    const radarCtx = document.getElementById('performance-chart');
    if (radarCtx) {
        new Chart(radarCtx, {
            type: 'radar',
            data: {
                labels: ['Accuracy', 'Speed', 'Completion', 'Score', 'Consistency'],
                datasets: [{
                    label: 'Your Performance',
                    data: [
                        data.accuracy,
                        Math.max(0, 100 - (data.timeTaken / data.totalTime * 100)),
                        ((data.correct + data.wrong) / data.total * 100),
                        (data.score / data.maxScore * 100),
                        data.accuracy > 0 ? Math.min(100, data.accuracy * 1.1) : 0,
                    ],
                    backgroundColor: 'rgba(108, 99, 255, 0.2)',
                    borderColor: 'rgba(108, 99, 255, 1)',
                    pointBackgroundColor: 'rgba(0, 255, 136, 1)',
                    pointBorderColor: '#fff',
                    borderWidth: 2,
                }]
            },
            options: {
                responsive: true,
                scales: {
                    r: {
                        beginAtZero: true,
                        max: 100,
                        ticks: { color: '#aaa', stepSize: 20 },
                        grid: { color: 'rgba(255,255,255,0.1)' },
                        pointLabels: { color: '#e0e0e0', font: { size: 12 } },
                    }
                },
                plugins: {
                    legend: {
                        labels: { color: '#e0e0e0' }
                    }
                }
            }
        });
    }
}
