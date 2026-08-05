/**
 * Quiz Engine
 * Handles: question navigation, auto-save, question palette, progress bar.
 * All answers saved to server via AJAX. Never stores correct answers client-side.
 */
class QuizEngine {
    constructor(quizId, totalQuestions, allowBackNavigation = true) {
        this.quizId = quizId;
        this.totalQuestions = totalQuestions;
        this.allowBackNavigation = allowBackNavigation;
        this.currentIndex = 0;
        this.answers = {};         // { questionId: { optionId, isReview } }
        this.questionCache = {};   // { index: questionData }
        this.isSaving = false;

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
        if (this.totalQuestions > 0 && index >= this.totalQuestions) return;

        if (window.antiCheat) {
            window.antiCheat.isNavigating = true;
            setTimeout(() => { if (window.antiCheat) window.antiCheat.isNavigating = false; }, 1000);
        }

        this.currentIndex = index;
        const container = document.getElementById('question-container');
        if (!container) return;
        container.classList.add('loading');

        try {
            let data;
            if (this.questionCache[index]) {
                data = this.questionCache[index];
            } else {
                data = await apiFetch(`/quiz/${this.quizId}/question/${index}/`);
                this.questionCache[index] = data;
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
        
        const savedAnswer = this.answers[data.question_id];
        const selectedOptionId = savedAnswer ? savedAnswer.optionId : data.selected_option_id;
        const isReview = savedAnswer ? savedAnswer.isReview : data.is_marked_for_review;

        let optionsHtml = '';
        data.options.forEach((opt, i) => {
            const isSelected = opt.id === selectedOptionId;
            const letter = String.fromCharCode(65 + i); // A, B, C, D
            optionsHtml += `
                <div class="option-card ${isSelected ? 'selected' : ''}" 
                     data-option-id="${opt.id}"
                     onclick="quizEngine.selectOption(${data.question_id}, ${opt.id}, this)">
                    <span class="option-letter">${letter}</span>
                    <span class="option-text">${opt.text}</span>
                    ${isSelected ? '<i class="fas fa-check-circle option-check"></i>' : ''}
                </div>
            `;
        });

        container.innerHTML = `
            <div class="question-header">
                <div class="question-meta">
                    <span class="question-number">Question ${this.currentIndex + 1}/${this.totalQuestions}</span>
                    <span class="badge bg-${this._difficultyColor(data.difficulty)}">${data.difficulty}</span>
                    <span class="badge bg-secondary">${data.topic}</span>
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
                        onclick="quizEngine.toggleReview(${data.question_id})">
                    <i class="fas fa-bookmark"></i> ${isReview ? 'Marked for Review' : 'Review Later'}
                </button>
                <button class="btn btn-outline-danger btn-clear"
                        onclick="quizEngine.clearAnswer(${data.question_id})">
                    <i class="fas fa-eraser"></i> Clear Answer
                </button>
            </div>
        `;

        // Animate in
        container.querySelector('.question-text').classList.add('fade-in');
    }

    // ==================== Answer Management ====================

    async selectOption(questionId, optionId, element) {
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
        if (this.isSaving) return;
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
            showToast('Failed to save answer. Retrying...', 'warning');
        } finally {
            this.isSaving = false;
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

            btn.classList.remove('current', 'answered', 'review', 'not-visited');

            const question = this.questionCache[i];
            if (question) {
                const answer = this.answers[question.question_id];
                if (answer?.isReview) {
                    btn.classList.add('review');
                } else if (answer?.optionId) {
                    btn.classList.add('answered');
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

    async submit() {
        // Temporarily pause anti-cheat during native confirm dialog
        if (window.antiCheat) window.antiCheat.isSystemDialog = true;

        // Count unanswered
        let answeredCount = Object.values(this.answers).filter(a => a && a.optionId).length;
        let unanswered = this.totalQuestions - answeredCount;

        let confirmed = false;
        if (unanswered > 0) {
            confirmed = confirm(
                `You have ${unanswered} unanswered question(s). Are you sure you want to submit?`
            );
        } else {
            confirmed = confirm('Are you sure you want to submit the quiz?');
        }

        if (window.antiCheat) {
            setTimeout(() => { window.antiCheat.isSystemDialog = false; }, 1000);
        }

        if (!confirmed) return;

        // Deactivate anti-cheat permanently for submission phase
        if (window.antiCheat) {
            window.antiCheat.isActive = false;
            window.antiCheat.isSubmitting = true;
        }

        try {
            const response = await apiFetch(`/quiz/${this.quizId}/submit/`, {
                method: 'POST',
                body: JSON.stringify({}),
            });

            showToast('Quiz submitted successfully! 🎉', 'success');
            
            setTimeout(() => {
                window.location.href = response.redirect || `/dashboard/result/${this.quizId}/`;
            }, 1500);
        } catch (error) {
            showToast('Failed to submit. Please try again.', 'error');
            if (window.antiCheat) window.antiCheat.isActive = true;
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
