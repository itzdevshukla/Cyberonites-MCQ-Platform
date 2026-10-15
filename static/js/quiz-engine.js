/**
 * Quiz Engine
 * Handles: question navigation, auto-save, question palette, progress bar.
 * All answers saved to server via AJAX. Never stores correct answers client-side.
 */
class QuizEngine {
    constructor(quizId, totalQuestions, allowBackNavigation = true, options = {}) {
        this.quizId = quizId;
        this.totalQuestions = totalQuestions;
        this.allowBackNavigation = allowBackNavigation;
        this.options = options;
        this.enableQuestionTimer = options.enableQuestionTimer || false;
        this.defaultQuestionSeconds = options.defaultQuestionSeconds || 20;

        this.currentIndex = 0;
        this.answers = {};         // { questionId: { optionId, isReview } }
        this.questionCache = {};   // { index: questionData }
        this.isSaving = false;
        this.currentQuestionTimer = null;
        this.questionRemainingSeconds = 0;
        this.questionLimitSeconds = 0;
        this.expiredQuestions = new Set();
        this.currentQuestionData = null;

        this._init();
    }


    async _init() {
        await this.loadQuestion(0);
        this._buildPalette();
        this._updateProgress();
        this._bindNavigation();

        // Sync answer state from server
        await this._syncState();

        // Periodic server sync every 30s
        setInterval(() => this._syncState(), 30000);
    }

    // ==================== Question Loading ====================

    async loadQuestion(index) {
        if (index < 0) return;
        const container = document.getElementById('question-container');
        if (!container) return;

        if (this.totalQuestions === 0) {
            container.classList.remove('loading');
            container.innerHTML = `
                <div class="text-center py-5">
                    <i class="fas fa-clipboard-list fa-4x text-secondary mb-3"></i>
                    <h4 class="text-gradient fw-bold">No Questions Available</h4>
                    <p class="text-secondary small">No questions have been added to this quiz yet. Please contact your instructor or administrator.</p>
                    <a href="/quiz/" class="btn btn-cyber btn-cyber-outline mt-3"><i class="fas fa-arrow-left"></i> Return to Lobby</a>
                </div>
            `;
            return;
        }

        if (this.totalQuestions > 0 && index >= this.totalQuestions) return;

        if (window.antiCheat) {
            window.antiCheat.isNavigating = true;
            setTimeout(() => { if (window.antiCheat) window.antiCheat.isNavigating = false; }, 1000);
        }

        this.currentIndex = index;
        this._clearQuestionTimer();
        container.classList.add('loading');

        try {
            let data;
            // When question timer is active, always fetch from server to get accurate remaining time and expiration state
            if (this.questionCache[index] && !this.enableQuestionTimer) {
                data = this.questionCache[index];
            } else {
                data = await apiFetch(`/quiz/${this.quizId}/question/${index}/`);
                this.questionCache[index] = data;
            }

            this.currentQuestionData = data;
            if (data.enable_question_timer) {
                this.enableQuestionTimer = true;
            }
            if (data.is_question_expired) {
                this.expiredQuestions.add(data.question_id);
            }

            if (data && data.total_questions) {
                if (this.totalQuestions !== data.total_questions) {
                    this.totalQuestions = data.total_questions;
                    this._buildPalette();
                }
            }

            this._renderQuestion(data);
            this._updatePalette();
            this._updateProgress();
            this._updateNavButtons();
        } catch (error) {
            console.error('Failed to load question:', error);
            container.innerHTML = `
                <div class="text-center py-4">
                    <i class="fas fa-exclamation-triangle fa-2x text-warning mb-2"></i>
                    <p class="text-secondary small mb-2">${error.message || 'Failed to load question'}</p>
                    <button class="btn btn-cyber btn-cyber-primary btn-sm" onclick="quizEngine.loadQuestion(${index})">
                        <i class="fas fa-redo"></i> Retry Loading
                    </button>
                </div>
            `;
        } finally {
            container.classList.remove('loading');
        }
    }


    _renderQuestion(data) {
        if (data.question_index !== undefined) {
            this.currentIndex = data.question_index;
        }

        const container = document.getElementById('question-container');
        
        const isExpired = !!(data.is_question_expired || this.expiredQuestions.has(data.question_id));
        if (isExpired) {
            this.expiredQuestions.add(data.question_id);
        }

        const savedAnswer = this.answers[data.question_id];
        const selectedOptionId = savedAnswer ? savedAnswer.optionId : data.selected_option_id;
        const isReview = savedAnswer ? savedAnswer.isReview : data.is_marked_for_review;

        let optionsHtml = '';
        data.options.forEach((opt, i) => {
            const isSelected = opt.id === selectedOptionId;
            const letter = String.fromCharCode(65 + i); // A, B, C, D
            const clickHandler = isExpired ? '' : `onclick="quizEngine.selectOption(${data.question_id}, ${opt.id}, this)"`;
            const disabledCls = isExpired ? 'locked-expired' : '';

            optionsHtml += `
                <div class="option-card ${isSelected ? 'selected' : ''} ${disabledCls}" 
                     data-option-id="${opt.id}"
                     ${clickHandler}>
                    <span class="option-letter">${letter}</span>
                    <span class="option-text">${opt.text}</span>
                    ${isSelected ? '<i class="fas fa-check-circle option-check"></i>' : ''}
                    ${isExpired && isSelected ? '<i class="fas fa-lock ms-auto text-muted small" title="Locked answer"></i>' : ''}
                </div>
            `;
        });

        // Question countdown timer visual progress bar inside card
        const timerTrackHtml = this.enableQuestionTimer ? `
            <div class="question-timer-track" id="question-timer-track">
                <div class="question-timer-bar ${isExpired ? 'bar-critical' : 'bar-normal'}" id="question-timer-bar" style="width: ${isExpired ? '0%' : '100%'};"></div>
            </div>
        ` : '';

        // Expired alert banner
        const expiredBannerHtml = isExpired ? `
            <div class="alert alert-secondary py-2 px-3 small d-flex align-items-center gap-2 mb-3" style="background: rgba(255, 71, 87, 0.12); border: 1.5px solid rgba(255, 71, 87, 0.4); color: #ff6b81; border-radius: 10px;">
                <i class="fas fa-lock fa-lg"></i>
                <div>
                    <strong>Time limit expired:</strong> The time for this question has ended. Answers are locked.
                </div>
            </div>
        ` : '';

        // Question header timer badge
        const timerBadgeHtml = this.enableQuestionTimer ? `
            <span class="badge ${isExpired ? 'bg-secondary' : 'bg-info text-dark'}" id="q-meta-timer">
                <i class="fas fa-hourglass-half me-1"></i><span id="q-meta-timer-text">${isExpired ? 'Expired' : `${Math.ceil(data.remaining_question_seconds || data.question_timer_seconds || 20)}s`}</span>
            </span>
        ` : '';

        container.innerHTML = `
            ${timerTrackHtml}
            ${expiredBannerHtml}
            <div class="question-header">
                <div class="question-meta">
                    <span class="question-number">Question ${this.currentIndex + 1}/${this.totalQuestions}</span>
                    <span class="badge bg-${this._difficultyColor(data.difficulty)}">${data.difficulty}</span>
                    <span class="badge bg-secondary">${data.topic}</span>
                    ${timerBadgeHtml}
                </div>
                <div class="question-marks">
                    <span class="marks-positive">+${data.marks}</span>
                    ${data.negative_marks > 0 ? `<span class="marks-negative">-${data.negative_marks}</span>` : ''}
                </div>
            </div>
            <div class="question-text">${data.text}</div>
            <div class="options-grid">${optionsHtml}</div>
            <div class="question-actions">
                <button class="btn btn-outline-warning btn-review ${isReview ? 'active' : ''}"
                        id="btn-review"
                        ${isExpired ? 'disabled' : ''}
                        onclick="quizEngine.toggleReview(${data.question_id})">
                    <i class="fas fa-bookmark"></i> ${isReview ? 'Marked for Review' : 'Review Later'}
                </button>
                <button class="btn btn-outline-danger btn-clear"
                        ${isExpired ? 'disabled' : ''}
                        onclick="quizEngine.clearAnswer(${data.question_id})">
                    <i class="fas fa-eraser"></i> Clear Answer
                </button>
            </div>
        `;

        // Animate in
        container.querySelector('.question-text')?.classList.add('fade-in');

        // Start countdown timer if enabled
        if (this.enableQuestionTimer) {
            if (isExpired) {
                this._updateQuestionTimerUI(0, data.question_timer_seconds || 20);
            } else {
                this._startQuestionTimer(data);
            }
        }
    }

    // ==================== Question-Based Timer Management ====================

    isCurrentQuestionExpired() {
        if (!this.enableQuestionTimer || !this.currentQuestionData) return false;
        return this.expiredQuestions.has(this.currentQuestionData.question_id);
    }

    _clearQuestionTimer() {
        if (this.currentQuestionTimer) {
            clearInterval(this.currentQuestionTimer);
            this.currentQuestionTimer = null;
        }
    }

    _startQuestionTimer(data) {
        this._clearQuestionTimer();

        const limit = data.question_timer_seconds || this.defaultQuestionSeconds || 20;
        let remaining = (data.remaining_question_seconds !== undefined && data.remaining_question_seconds !== null)
            ? data.remaining_question_seconds
            : limit;

        this.questionLimitSeconds = limit;
        this.questionRemainingSeconds = remaining;

        this._updateQuestionTimerUI(remaining, limit);

        if (remaining <= 0) {
            this._onQuestionTimeExpired(data.question_id);
            return;
        }

        const startTimestamp = Date.now();
        const initialRemaining = remaining;

        this.currentQuestionTimer = setInterval(() => {
            const elapsedSec = (Date.now() - startTimestamp) / 1000;
            const currentRemaining = Math.max(0, initialRemaining - elapsedSec);
            this.questionRemainingSeconds = currentRemaining;

            this._updateQuestionTimerUI(currentRemaining, limit);

            if (currentRemaining <= 0) {
                this._clearQuestionTimer();
                this._onQuestionTimeExpired(data.question_id);
            }
        }, 100);
    }

    _updateQuestionTimerUI(remaining, limit) {
        const displayVal = Math.ceil(remaining);
        const pct = Math.max(0, Math.min(100, (remaining / limit) * 100));

        const pill = document.getElementById('question-timer-pill');
        const pillDisplay = document.getElementById('question-timer-display');
        if (pillDisplay) {
            pillDisplay.textContent = remaining <= 0 ? '0s' : `${displayVal}s`;
        }

        const bar = document.getElementById('question-timer-bar');
        if (bar) {
            bar.style.width = `${pct}%`;
        }

        const metaVal = document.getElementById('q-meta-timer-text');
        if (metaVal) {
            metaVal.textContent = remaining <= 0 ? 'Expired' : `${displayVal}s`;
        }

        let stateClass = 'normal';
        if (remaining <= 0) {
            stateClass = 'expired';
        } else if (remaining <= 5 || pct <= 25) {
            stateClass = 'critical';
        } else if (remaining <= 10 || pct <= 50) {
            stateClass = 'warning';
        }

        if (pill) {
            pill.className = `question-timer-pill timer-${stateClass}`;
        }
        if (bar) {
            bar.className = `question-timer-bar bar-${stateClass === 'expired' ? 'critical' : stateClass}`;
        }
    }

    _onQuestionTimeExpired(questionId) {
        this.expiredQuestions.add(questionId);

        // Lock options on screen immediately
        document.querySelectorAll('.option-card').forEach(el => {
            el.classList.add('locked-expired');
            el.style.pointerEvents = 'none';
        });
        document.getElementById('btn-review')?.setAttribute('disabled', 'true');
        document.querySelector('.btn-clear')?.setAttribute('disabled', 'true');

        const pill = document.getElementById('question-timer-pill');
        const pillDisplay = document.getElementById('question-timer-display');
        if (pill) pill.className = 'question-timer-pill timer-expired';
        if (pillDisplay) pillDisplay.textContent = 'Expired';

        const metaVal = document.getElementById('q-meta-timer-text');
        if (metaVal) metaVal.textContent = 'Expired';

        const bar = document.getElementById('question-timer-bar');
        if (bar) {
            bar.style.width = '0%';
            bar.className = 'question-timer-bar bar-critical';
        }

        this._updatePalette();

        showToast(`⏱️ Time expired for Question ${this.currentIndex + 1}!`, 'warning', 2500);

        // Auto-advance to next question after 750ms
        setTimeout(() => {
            if (this.currentIndex < this.totalQuestions - 1) {
                this.loadQuestion(this.currentIndex + 1);
            } else {
                showToast('🏁 You have reached the end of the test! Please submit your examination.', 'info', 6000);
            }
        }, 750);
    }

    // ==================== Answer Management ====================

    async selectOption(questionId, optionId, element) {
        if (this.isCurrentQuestionExpired()) {
            showToast('⏱️ Time expired for this question. Answers are locked.', 'warning');
            return;
        }

        // Visual feedback
        document.querySelectorAll('.option-card').forEach(el => {
            el.classList.remove('selected');
            el.querySelector('.option-check')?.remove();
        });
        element.classList.add('selected');
        element.innerHTML += '<i class="fas fa-check-circle option-check"></i>';

        // Store locally
        const isReview = this.answers[questionId]?.isReview || false;
        this.answers[questionId] = { optionId, isReview };

        // Auto-save to server
        await this._saveAnswer(questionId, optionId, isReview);
        this._updatePalette();
    }

    async clearAnswer(questionId) {
        if (this.isCurrentQuestionExpired()) {
            showToast('⏱️ Time expired for this question. Answers are locked.', 'warning');
            return;
        }

        document.querySelectorAll('.option-card').forEach(el => {
            el.classList.remove('selected');
            el.querySelector('.option-check')?.remove();
        });

        const isReview = this.answers[questionId]?.isReview || false;
        this.answers[questionId] = { optionId: null, isReview };

        await this._saveAnswer(questionId, null, isReview);
        this._updatePalette();
    }

    async toggleReview(questionId) {
        if (this.isCurrentQuestionExpired()) {
            showToast('⏱️ Time expired for this question.', 'warning');
            return;
        }

        const current = this.answers[questionId];
        const isReview = !(current?.isReview || false);
        
        if (current) {
            current.isReview = isReview;
        } else {
            this.answers[questionId] = { optionId: null, isReview };
        }

        const btn = document.getElementById('btn-review');
        if (btn) {
            btn.classList.toggle('active', isReview);
            btn.innerHTML = `<i class="fas fa-bookmark"></i> ${isReview ? 'Marked for Review' : 'Review Later'}`;
        }

        await this._saveAnswer(questionId, current?.optionId || null, isReview);
        this._updatePalette();
    }

    async _saveAnswer(questionId, optionId, isReview) {
        // If a save is already inflight, record the latest pending answer to prevent dropped clicks
        if (this.isSaving) {
            this.pendingSave = { questionId, optionId, isReview };
            return;
        }
        this.isSaving = true;

        try {
            await apiFetch(`/quiz/${this.quizId}/save-answer/`, {
                method: 'POST',
                body: JSON.stringify({
                    question_id: questionId,
                    selected_option_id: optionId,
                    is_marked_for_review: isReview,
                }),
            });
        } catch (error) {
            console.error('Failed to save answer:', error);
            if (error.data && error.data.question_expired) {
                showToast(`⏱️ ${error.data.error || 'Question time expired. Answer not accepted.'}`, 'error', 5000);
                this.expiredQuestions.add(questionId);
                this._updatePalette();
                return;
            }
            showToast('Network issue saving answer. Retrying automatically...', 'warning');
            if (!this.pendingSave) {
                this.pendingSave = { questionId, optionId, isReview };
            }
        } finally {
            this.isSaving = false;
            // If another answer was selected while saving, immediately process the latest pending save
            if (this.pendingSave) {
                const next = this.pendingSave;
                this.pendingSave = null;
                await this._saveAnswer(next.questionId, next.optionId, next.isReview);
            }
        }
    }

    // ==================== Navigation ====================

    _bindNavigation() {
        document.getElementById('btn-prev')?.addEventListener('click', () => this.prev());
        document.getElementById('btn-next')?.addEventListener('click', () => this.next());
        document.getElementById('btn-submit')?.addEventListener('click', () => this.submit());

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowLeft') this.prev();
            if (e.key === 'ArrowRight') this.next();
        });
    }

    prev() {
        if (!this.allowBackNavigation) {
            showToast('⚠️ Navigating to previous questions is disabled by organiser.', 'warning');
            return;
        }
        if (this.currentIndex > 0) {
            this.loadQuestion(this.currentIndex - 1);
        }
    }

    next() {
        if (this.currentIndex < this.totalQuestions - 1) {
            this.loadQuestion(this.currentIndex + 1);
        }
    }

    jumpTo(index) {
        if (!this.allowBackNavigation && index < this.currentIndex) {
            showToast('⚠️ Navigating back to previous questions is disabled by organiser.', 'warning');
            return;
        }
        this.loadQuestion(index);
        document.getElementById('question-palette')?.classList.remove('show');
    }

    // ==================== Question Palette ====================

    _buildPalette() {
        const palette = document.getElementById('palette-grid');
        if (!palette) return;

        let html = '';
        for (let i = 0; i < this.totalQuestions; i++) {
            html += `<button class="palette-btn not-visited" data-index="${i}" 
                            id="palette-btn-${i}"
                            onclick="quizEngine.jumpTo(${i})">${i + 1}</button>`;
        }
        palette.innerHTML = html;
    }

    _updatePalette() {
        const buttons = document.querySelectorAll('#palette-grid .palette-btn');
        buttons.forEach((btn, i) => {

            btn.classList.remove('current', 'answered', 'review', 'not-visited', 'expired');

            const question = this.questionCache[i];
            if (question) {
                const answer = this.answers[question.question_id];
                const isExp = this.expiredQuestions && this.expiredQuestions.has(question.question_id);
                if (answer?.isReview) {
                    btn.classList.add('review');
                } else if (answer?.optionId) {
                    btn.classList.add('answered');
                } else if (isExp) {
                    btn.classList.add('expired');
                } else {
                    btn.classList.add('not-visited');
                }
            } else {
                btn.classList.add('not-visited');
            }

            // Current index MUST be applied last so active question highlight takes precedence!
            if (i === this.currentIndex) {
                btn.classList.add('current');
            }

            // Disable previous question buttons if back navigation is disallowed
            if (!this.allowBackNavigation && i < this.currentIndex) {
                btn.style.opacity = '0.35';
                btn.style.cursor = 'not-allowed';
            } else {
                btn.style.opacity = '1';
                btn.style.cursor = 'pointer';
            }
        });

        // Update counters
        this._updateCounters();
    }


    _updateCounters() {
        const answered = Object.values(this.answers).filter(a => a && a.optionId).length;
        const review = Object.values(this.answers).filter(a => a && a.isReview).length;
        const remaining = Math.max(0, this.totalQuestions - answered);

        const el = (id, val) => {
            const e = document.getElementById(id);
            if (e) e.textContent = val;
        };
        el('count-answered', answered);
        el('count-review', review);
        el('count-not-visited', remaining);
        el('count-total', this.totalQuestions);
    }

    // ==================== Progress Bar ====================

    _updateProgress() {
        const bar = document.getElementById('progress-bar');
        if (!bar) return;
        const progress = ((this.currentIndex + 1) / this.totalQuestions) * 100;
        bar.style.width = `${progress}%`;
        bar.setAttribute('aria-valuenow', progress);
    }

    _updateNavButtons() {
        const prevBtn = document.getElementById('btn-prev');
        const nextBtn = document.getElementById('btn-next');
        const submitBtn = document.getElementById('btn-submit');

        if (prevBtn) {
            if (!this.allowBackNavigation) {
                prevBtn.style.display = 'none'; // Hide Previous button if disallowed
            } else {
                prevBtn.style.display = 'inline-flex';
                prevBtn.disabled = this.currentIndex === 0;
            }
        }

        const isLastQuestion = (this.totalQuestions > 0 && this.currentIndex === this.totalQuestions - 1);

        if (nextBtn) {
            nextBtn.disabled = isLastQuestion;
        }

        if (submitBtn) {
            submitBtn.style.display = isLastQuestion ? 'inline-flex' : 'none';
        }
    }


    // ==================== Submit ====================

    submit() {
        // Count answered & review
        const answeredCount = Object.values(this.answers).filter(a => a && a.optionId).length;
        const reviewCount = Object.values(this.answers).filter(a => a && a.isReview).length;
        const unanswered = Math.max(0, this.totalQuestions - answeredCount);

        const modalEl = document.getElementById('cyber-submit-modal');
        if (!modalEl) {
            this.confirmSubmit();
            return;
        }

        // Populate live stats into modal
        const totalEl = document.getElementById('modal-submit-total');
        const ansEl = document.getElementById('modal-submit-answered');
        const unansEl = document.getElementById('modal-submit-unanswered');
        const revEl = document.getElementById('modal-submit-review');
        const warnEl = document.getElementById('modal-unanswered-warning');

        if (totalEl) totalEl.textContent = this.totalQuestions;
        if (ansEl) ansEl.textContent = answeredCount;
        if (unansEl) unansEl.textContent = unanswered;
        if (revEl) revEl.textContent = reviewCount;
        if (warnEl) warnEl.style.display = unanswered > 0 ? 'flex' : 'none';

        if (window.bootstrap && window.bootstrap.Modal) {
            const modalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
            modalInstance.show();
        } else {
            this.confirmSubmit();
        }
    }

    async confirmSubmit() {
        // Deactivate anti-cheat permanently for submission phase
        if (window.antiCheat) {
            window.antiCheat.isActive = false;
            window.antiCheat.isSubmitting = true;
        }

        const btn = document.getElementById('btn-modal-confirm-submit');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i> Submitting...';
        }

        try {
            const response = await apiFetch(`/quiz/${this.quizId}/submit/`, {
                method: 'POST',
                body: JSON.stringify({}),
            });

            showToast('🎉 Examination submitted successfully!', 'success');
            
            const targetUrl = (response && response.redirect) ? response.redirect : `/dashboard/result/${this.quizId}/`;
            setTimeout(() => {
                window.location.href = targetUrl;
            }, 600);
        } catch (error) {
            showToast('Failed to submit examination. Please try again.', 'danger');
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-check-circle me-1"></i> Confirm & Submit';
            }
            if (window.antiCheat) {
                window.antiCheat.isActive = true;
                window.antiCheat.isSubmitting = false;
            }
        }
    }

    // Force submit (called by timer/anti-cheat)
    async forceSubmit() {
        if (window.antiCheat) {
            window.antiCheat.isActive = false;
            window.antiCheat.isSubmitting = true;
        }
        try {
            await apiFetch(`/quiz/${this.quizId}/submit/`, {
                method: 'POST',
                body: JSON.stringify({}),
            });
        } catch (e) { /* silently fail */ }
        window.location.href = `/dashboard/result/${this.quizId}/`;
    }

    // ==================== Server Sync ====================

    async _syncState() {
        try {
            const data = await apiFetch(`/quiz/${this.quizId}/status/`);
            
            if (data.total_questions && data.total_questions !== this.totalQuestions) {
                this.totalQuestions = data.total_questions;
                this._buildPalette();
                if (this.currentIndex >= this.totalQuestions) {
                    this.currentIndex = Math.max(0, this.totalQuestions - 1);
                }
                this.loadQuestion(this.currentIndex);
            }

            // Update answer states from server
            if (data.answer_summary) {
                data.answer_summary.forEach(a => {
                    if (!this.answers[a.question_id]) {
                        this.answers[a.question_id] = {
                            optionId: a.selected_option_id,
                            isReview: a.is_marked_for_review,
                        };
                    }
                });
                this._updatePalette();
            }

            // Sync server-authoritative expired questions
            if (data.expired_question_ids && Array.isArray(data.expired_question_ids)) {
                let hasNewExpired = false;
                data.expired_question_ids.forEach(qid => {
                    if (!this.expiredQuestions.has(qid)) {
                        this.expiredQuestions.add(qid);
                        hasNewExpired = true;
                    }
                });
                if (hasNewExpired) {
                    this._updatePalette();
                    if (this.currentQuestionData && this.expiredQuestions.has(this.currentQuestionData.question_id)) {
                        document.querySelectorAll('.option-card').forEach(el => {
                            el.classList.add('locked-expired');
                            el.style.pointerEvents = 'none';
                        });
                        document.getElementById('btn-review')?.setAttribute('disabled', 'true');
                        document.querySelector('.btn-clear')?.setAttribute('disabled', 'true');
                    }
                }
            }

            // Check if already submitted
            if (data.is_submitted) {
                window.location.href = `/dashboard/result/${this.quizId}/`;
            }

            // Sync timer
            if (window.quizTimer && data.remaining_seconds !== undefined) {
                window.quizTimer.sync(data.remaining_seconds);
            }
        } catch (error) {
            // Silent fail — will retry on next interval
        }
    }


    // ==================== Helpers ====================

    _difficultyColor(difficulty) {
        switch (difficulty) {
            case 'EASY': return 'success';
            case 'MEDIUM': return 'warning';
            case 'HARD': return 'danger';
            default: return 'secondary';
        }
    }
}
