/**
 * Live Leaderboard with rank change animations.
 */
class LiveLeaderboard {
    constructor(quizId, containerId) {
        this.quizId = quizId;
        this.container = document.getElementById(containerId);
        this.previousRanks = {};

        // Try WebSocket, fallback to polling
        this.ws = new WebSocketManager(`/ws/leaderboard/${quizId}/`, {
            leaderboard_update: (data) => this.render(data.entries),
        });

        // Polling fallback every 5s
        this.pollInterval = setInterval(() => this.poll(), 5000);
    }

    async poll() {
        try {
            const data = await apiFetch(`/leaderboard/${this.quizId}/data/`);
            this.render(data.entries);
        } catch (e) { /* silent */ }
    }

    render(entries) {
        if (!this.container || !entries) return;

        let html = '';
        entries.forEach((entry, i) => {
            const prevRank = this.previousRanks[entry.participant_id];
            let changeClass = '';
            let changeIcon = '';

            if (prevRank !== undefined) {
                if (prevRank > entry.rank) {
                    changeClass = 'rank-up';
                    changeIcon = '<i class="fas fa-arrow-up text-success"></i>';
                } else if (prevRank < entry.rank) {
                    changeClass = 'rank-down';
                    changeIcon = '<i class="fas fa-arrow-down text-danger"></i>';
                }
            }

            this.previousRanks[entry.participant_id] = entry.rank;

            const medalClass = entry.rank <= 3 ? `medal-${entry.rank}` : '';
            const rankDisplay = entry.rank <= 3 
                ? ['🥇', '🥈', '🥉'][entry.rank - 1] 
                : `#${entry.rank}`;

            html += `
                <tr class="leaderboard-row ${changeClass} ${medalClass}" data-id="${entry.participant_id}">
                    <td class="rank-cell">
                        <span class="rank-number">${rankDisplay}</span>
                        ${changeIcon}
                    </td>
                    <td class="name-cell">
                        <div class="participant-name">${entry.name}</div>
                        <div class="participant-college">${entry.college}</div>
                    </td>
                    <td class="score-cell">
                        <span class="score-value">${entry.score}</span>
                    </td>
                    <td class="accuracy-cell">${entry.accuracy}%</td>
                    <td class="time-cell">${formatTime(entry.time_taken)}</td>
                    <td class="attempted-cell">${entry.questions_attempted}</td>
                </tr>
            `;
        });

        const tbody = this.container.querySelector('tbody');
        if (tbody) {
            tbody.innerHTML = html;
        }

        // Update total count
        const countEl = document.getElementById('lb-total-count');
        if (countEl) countEl.textContent = entries.length;
    }

    destroy() {
        if (this.ws) this.ws.close();
        if (this.pollInterval) clearInterval(this.pollInterval);
    }
}
