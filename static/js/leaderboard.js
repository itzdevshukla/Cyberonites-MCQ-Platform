/**
 * Professional Live Leaderboard
 * Real-time WebSocket synchronization, dynamic Top 3 podium updates,
 * instant search, strict XSS protection, and ZERO polling while WebSocket is connected.
 */

function escapeHTML(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function formatDuration(seconds) {
    if (!seconds || seconds <= 0) return '00:00';
    const s = Math.round(Number(seconds));
    const hrs = Math.floor(s / 3600);
    const mins = Math.floor((s % 3600) / 60);
    const secs = s % 60;
    if (hrs > 0) {
        return `${hrs}h ${mins}m ${secs}s`;
    }
    return `${mins}m ${secs < 10 ? '0' : ''}${secs}s`;
}

class LiveLeaderboard {
    constructor(quizId, currentUserId = 0) {
        this.quizId = quizId;
        this.tbody = document.getElementById('leaderboard-tbody');
        this.currentUserId = parseInt(currentUserId, 10) || 0;

        this.entries = [];
        this.searchQuery = '';
        this.pollInterval = null;

        this.initControls();
        this.initWebSocket();
    }

    initControls() {
        const searchInput = document.getElementById('lb-search-input');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this.searchQuery = (e.target.value || '').trim().toLowerCase();
                this.renderTable();
            });
        }
    }

    initWebSocket() {
        const statusBadge = document.getElementById('lb-connection-status');

        this.ws = new WebSocketManager(`/ws/leaderboard/${this.quizId}/`, {
            leaderboard_update: (data) => {
                this.handleUpdate(data);
            },
            onConnect: () => {
                // Connected via WebSocket: STOP any polling immediately
                if (this.pollInterval) {
                    clearInterval(this.pollInterval);
                    this.pollInterval = null;
                }
                if (statusBadge) {
                    statusBadge.innerHTML = '<i class="fas fa-bolt me-1 text-success"></i> Live';
                    statusBadge.style.color = 'var(--emerald)';
                }
            }
        });

        // Fallback polling ONLY if WebSocket fails
        if (this.ws && this.ws.ws) {
            this.ws.ws.addEventListener('close', () => {
                if (statusBadge) {
                    statusBadge.innerHTML = '<i class="fas fa-spinner fa-spin me-1 text-warning"></i> Reconnecting';
                    statusBadge.style.color = 'var(--amber)';
                }
                this.startFallbackPolling();
            });
        }
    }

    startFallbackPolling() {
        if (this.pollInterval) return;
        this.pollInterval = setInterval(async () => {
            if (this.ws && this.ws.isConnected) {
                clearInterval(this.pollInterval);
                this.pollInterval = null;
                return;
            }
            try {
                const data = await apiFetch(`/leaderboard/${this.quizId}/data/`);
                if (data) this.handleUpdate(data);
            } catch (e) {
                /* silent fallback */
            }
        }, 8000);
    }

    handleUpdate(data) {
        if (!data || !data.entries) return;

        this.entries = data.entries;

        // Update counts
        if (data.total_joined !== undefined) {
            const joinedEl = document.getElementById('stat-total-joined');
            if (joinedEl) joinedEl.textContent = data.total_joined;
        }
        if (data.total_submitted !== undefined) {
            const subEl = document.getElementById('stat-total-submitted');
            if (subEl) subEl.textContent = data.total_submitted;
        }
        const countEl = document.getElementById('lb-total-count');
        if (countEl) countEl.textContent = this.entries.length;

        // Dynamically re-render Podium and Table
        this.renderPodium(this.entries);
        this.renderTable();
    }

    renderPodium(entries) {
        const slot1 = document.getElementById('pro-podium-slot-1');
        const slot2 = document.getElementById('pro-podium-slot-2');
        const slot3 = document.getElementById('pro-podium-slot-3');

        // 1st Place (Champion)
        if (slot1) {
            const e1 = entries[0];
            if (e1) {
                const initial = escapeHTML((e1.name || '?').charAt(0).toUpperCase());
                const safeName = escapeHTML(e1.name);
                const safeCollege = escapeHTML(e1.college || 'Cyber Academy');
                const timeStr = formatDuration(e1.time_taken);

                slot1.innerHTML = `
                    <div class="pro-podium-card">
                        <span class="pro-podium-badge"><i class="fas fa-crown text-warning me-1"></i> Champion #1</span>
                        <div class="pro-podium-avatar">${initial}</div>
                        <div class="pro-podium-name text-gradient" title="${safeName}">${safeName}</div>
                        <div class="pro-podium-college" title="${safeCollege}">${safeCollege}</div>
                        <div class="pro-podium-score">${e1.score}</div>
                        <div class="pro-podium-stats">
                            <span><i class="fas fa-bullseye text-success me-1"></i>${e1.accuracy}%</span>
                            <span><i class="fas fa-clock text-secondary me-1"></i>${timeStr}</span>
                        </div>
                    </div>
                `;
            } else {
                slot1.innerHTML = `
                    <div class="pro-podium-card pro-podium-empty">
                        <span class="pro-podium-badge opacity-50"><i class="fas fa-crown text-warning me-1"></i> Champion #1</span>
                        <div class="pro-podium-avatar opacity-25" style="background: rgba(255,255,255,0.08); color: #fff;">?</div>
                        <div class="pro-podium-name text-muted">Awaiting Champion</div>
                        <div class="pro-podium-college text-secondary">Rank #1 Pending</div>
                        <div class="pro-podium-score text-muted opacity-50">—</div>
                    </div>
                `;
            }
        }

        // 2nd Place (Runner-Up)
        if (slot2) {
            const e2 = entries[1];
            if (e2) {
                const initial = escapeHTML((e2.name || '?').charAt(0).toUpperCase());
                const safeName = escapeHTML(e2.name);
                const safeCollege = escapeHTML(e2.college || 'Cyber Academy');
                const timeStr = formatDuration(e2.time_taken);

                slot2.innerHTML = `
                    <div class="pro-podium-card">
                        <span class="pro-podium-badge"><i class="fas fa-medal me-1"></i> 2nd Place</span>
                        <div class="pro-podium-avatar">${initial}</div>
                        <div class="pro-podium-name" title="${safeName}">${safeName}</div>
                        <div class="pro-podium-college" title="${safeCollege}">${safeCollege}</div>
                        <div class="pro-podium-score">${e2.score}</div>
                        <div class="pro-podium-stats">
                            <span><i class="fas fa-bullseye text-info me-1"></i>${e2.accuracy}%</span>
                            <span><i class="fas fa-clock text-secondary me-1"></i>${timeStr}</span>
                        </div>
                    </div>
                `;
            } else {
                slot2.innerHTML = `
                    <div class="pro-podium-card pro-podium-empty">
                        <span class="pro-podium-badge opacity-50"><i class="fas fa-medal me-1"></i> 2nd Place</span>
                        <div class="pro-podium-avatar opacity-25" style="background: rgba(255,255,255,0.08); color: #fff;">?</div>
                        <div class="pro-podium-name text-muted">Awaiting Runner-Up</div>
                        <div class="pro-podium-college text-secondary">Rank #2 Pending</div>
                        <div class="pro-podium-score text-muted opacity-50">—</div>
                    </div>
                `;
            }
        }

        // 3rd Place (Bronze)
        if (slot3) {
            const e3 = entries[2];
            if (e3) {
                const initial = escapeHTML((e3.name || '?').charAt(0).toUpperCase());
                const safeName = escapeHTML(e3.name);
                const safeCollege = escapeHTML(e3.college || 'Cyber Academy');
                const timeStr = formatDuration(e3.time_taken);

                slot3.innerHTML = `
                    <div class="pro-podium-card">
                        <span class="pro-podium-badge"><i class="fas fa-award me-1"></i> 3rd Place</span>
                        <div class="pro-podium-avatar">${initial}</div>
                        <div class="pro-podium-name" title="${safeName}">${safeName}</div>
                        <div class="pro-podium-college" title="${safeCollege}">${safeCollege}</div>
                        <div class="pro-podium-score">${e3.score}</div>
                        <div class="pro-podium-stats">
                            <span><i class="fas fa-bullseye text-warning me-1"></i>${e3.accuracy}%</span>
                            <span><i class="fas fa-clock text-secondary me-1"></i>${timeStr}</span>
                        </div>
                    </div>
                `;
            } else {
                slot3.innerHTML = `
                    <div class="pro-podium-card pro-podium-empty">
                        <span class="pro-podium-badge opacity-50"><i class="fas fa-award me-1"></i> 3rd Place</span>
                        <div class="pro-podium-avatar opacity-25" style="background: rgba(255,255,255,0.08); color: #fff;">?</div>
                        <div class="pro-podium-name text-muted">Awaiting 3rd Place</div>
                        <div class="pro-podium-college text-secondary">Rank #3 Pending</div>
                        <div class="pro-podium-score text-muted opacity-50">—</div>
                    </div>
                `;
            }
        }
    }

    renderTable() {
        if (!this.tbody) return;

        let filtered = this.entries;
        if (this.searchQuery) {
            filtered = filtered.filter(e => {
                const n = (e.name || '').toLowerCase();
                const c = (e.college || '').toLowerCase();
                return n.includes(this.searchQuery) || c.includes(this.searchQuery);
            });
        }

        const visibleCountEl = document.getElementById('lb-visible-count');
        if (visibleCountEl) visibleCountEl.textContent = filtered.length;

        if (filtered.length === 0) {
            if (this.entries.length === 0) {
                this.tbody.innerHTML = `
                    <tr id="empty-leaderboard-row">
                        <td colspan="6" class="text-center py-5 text-muted">
                            <i class="fas fa-hourglass-half fa-2x mb-2 d-block opacity-50"></i>
                            No submissions yet. Rankings will appear as participants submit.
                        </td>
                    </tr>
                `;
            } else {
                this.tbody.innerHTML = `
                    <tr>
                        <td colspan="6" class="text-center py-4 text-muted">
                            No participants match "${escapeHTML(this.searchQuery)}".
                        </td>
                    </tr>
                `;
            }
            return;
        }

        let html = '';
        filtered.forEach(entry => {
            const isYou = this.currentUserId > 0 && entry.participant_id === this.currentUserId;
            const youClass = isYou ? 'lb-row-you' : '';
            const youBadge = isYou ? '<span class="badge bg-primary text-dark ms-1" style="font-size: 0.65rem;">YOU</span>' : '';

            let rankHtml = `#${entry.rank}`;
            let rankColor = 'text-secondary';
            if (entry.rank === 1) {
                rankHtml = '🥇 1';
                rankColor = 'text-warning fw-bold';
            } else if (entry.rank === 2) {
                rankHtml = '🥈 2';
                rankColor = 'text-light fw-bold';
            } else if (entry.rank === 3) {
                rankHtml = '🥉 3';
                rankColor = 'text-warning fw-bold opacity-75';
            }

            let accColor = 'text-warning';
            if (entry.accuracy >= 80) accColor = 'text-success';
            else if (entry.accuracy >= 50) accColor = 'text-info';

            const safeName = escapeHTML(entry.name);
            const safeCollege = escapeHTML(entry.college || '—');
            const initial = escapeHTML((entry.name || '?').charAt(0).toUpperCase());
            const timeStr = formatDuration(entry.time_taken);

            html += `
                <tr class="${youClass}" data-id="${entry.participant_id}">
                    <td>
                        <span class="${rankColor}">${rankHtml}</span>
                    </td>
                    <td>
                        <div class="d-flex align-items-center gap-2">
                            <div class="avatar-sm rounded-circle bg-primary text-dark fw-bold d-flex align-items-center justify-content-center" style="width: 32px; height: 32px; font-size: 0.85rem;">
                                ${initial}
                            </div>
                            <div>
                                <span class="fw-bold text-light">${safeName}</span>
                                ${youBadge}
                            </div>
                        </div>
                    </td>
                    <td class="text-secondary small">${safeCollege}</td>
                    <td>
                        <strong class="text-gradient" style="font-size: 1.05rem;">${entry.score}</strong>
                    </td>
                    <td>
                        <span class="${accColor} fw-semibold">${entry.accuracy}%</span>
                    </td>
                    <td class="text-secondary small">${timeStr}</td>
                </tr>
            `;
        });

        this.tbody.innerHTML = html;
    }

    destroy() {
        if (this.ws && typeof this.ws.close === 'function') this.ws.close();
        if (this.pollInterval) clearInterval(this.pollInterval);
    }
}
