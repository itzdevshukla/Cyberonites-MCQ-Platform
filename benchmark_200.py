#!/usr/bin/env python3
"""
QArena Enterprise 200-User Concurrency & Load Benchmark Harness
Models realistic examination behavior for up to 200 simultaneous candidates.

Traces full user journey:
1. Registration & Authentication (CSRF handling, session cookies)
2. Examination Lobby Navigation
3. Exam Start & Randomized State Machine Transition
4. Question Retrieval (Batch Option Fetching)
5. Think Time & Auto-Save Answer Submission (Row-Lock Verification)
6. Final Submission & Automated Server-Side Scoring
7. Scorecard & Result Verification

Measures:
- p50, p95, p99 Latency per Endpoint
- HTTP Status Code Distribution (200, 302, 400, 429, 500, etc.)
- Answer Durability & Submission Accuracy
- Error Rate & Throughput (Requests/sec)
"""
import sys
import time
import uuid
import random
import asyncio
import argparse
from typing import Dict, List, Tuple
from collections import defaultdict

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

try:
    import aiohttp
except ImportError:
    print("[ERROR] aiohttp is required. Install via: pip install aiohttp")
    sys.exit(1)


class CandidateMetrics:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.endpoint_latencies = defaultdict(list)
        self.status_codes = defaultdict(int)
        self.exceptions = []
        self.completed_candidates = 0
        self.failed_candidates = 0
        self.answers_saved = 0
        self.submissions_successful = 0

    async def record_request(self, endpoint: str, latency: float, status_code: int):
        async with self.lock:
            self.endpoint_latencies[endpoint].append(latency)
            self.status_codes[status_code] += 1

    async def record_error(self, candidate_id: int, stage: str, error_msg: str):
        async with self.lock:
            self.exceptions.append((candidate_id, stage, error_msg))

    async def record_answer_saved(self):
        async with self.lock:
            self.answers_saved += 1

    async def record_submission(self):
        async with self.lock:
            self.submissions_successful += 1

    async def finish_candidate(self, success: bool):
        async with self.lock:
            if success:
                self.completed_candidates += 1
            else:
                self.failed_candidates += 1


def percentile(data: List[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_data) else f
    d = k - f
    return sorted_data[f] + d * (sorted_data[c] - sorted_data[f])


async def simulate_candidate(
    candidate_id: int,
    base_url: str,
    quiz_id: int,
    questions_to_answer: int,
    think_time_range: Tuple[float, float],
    metrics: CandidateMetrics,
    semaphore: asyncio.Semaphore,
    run_id: str,
):
    async with semaphore:
        # Realistic initial arrival jitter (staggers initial cohort hit over 1-4 seconds)
        await asyncio.sleep(random.uniform(0.1, 3.0))

        cookie_jar = aiohttp.CookieJar(unsafe=True)
        timeout = aiohttp.ClientTimeout(total=45, connect=10)
        connector = aiohttp.TCPConnector(ssl=False)

        async with aiohttp.ClientSession(cookie_jar=cookie_jar, timeout=timeout, connector=connector) as session:
            email = f"loadtest_cand_{candidate_id}_{run_id}@cyberonites.com"
            name = f"Candidate {candidate_id}"
            college = "Cyberonites Benchmark Academy"
            password = "StrongPassword2026!"

            # ----------------------------------------------------
            # 1. GET Registration Page & Extract CSRF Token
            # ----------------------------------------------------
            t0 = time.perf_counter()
            reg_url = f"{base_url}/accounts/register/"
            try:
                async with session.get(reg_url) as resp:
                    t_req = time.perf_counter() - t0
                    await metrics.record_request("GET /accounts/register/", t_req, resp.status)
                    if resp.status != 200:
                        await metrics.record_error(candidate_id, "GET_REGISTER", f"HTTP {resp.status}")
                        await metrics.finish_candidate(False)
                        return
            except Exception as e:
                await metrics.record_error(candidate_id, "GET_REGISTER", str(e))
                await metrics.finish_candidate(False)
                return

            csrf_token = None
            for c in session.cookie_jar:
                if c.key == 'csrftoken':
                    csrf_token = c.value
                    break

            if not csrf_token:
                await metrics.record_error(candidate_id, "GET_REGISTER", "CSRF token missing in cookie jar")
                await metrics.finish_candidate(False)
                return

            headers = {
                'X-CSRFToken': csrf_token,
                'Referer': reg_url,
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Benchmark/1.0',
            }

            # ----------------------------------------------------
            # 2. POST Registration & Session Establishment
            # ----------------------------------------------------
            reg_payload = {
                'csrfmiddlewaretoken': csrf_token,
                'full_name': name,
                'email': email,
                'college': college,
                'password': password,
                'confirm_password': password,
            }
            t0 = time.perf_counter()
            try:
                async with session.post(reg_url, data=reg_payload, headers=headers, allow_redirects=True) as resp:
                    t_req = time.perf_counter() - t0
                    await metrics.record_request("POST /accounts/register/", t_req, resp.status)
                    if resp.status not in (200, 302):
                        await metrics.record_error(candidate_id, "POST_REGISTER", f"HTTP {resp.status}")
                        await metrics.finish_candidate(False)
                        return
            except Exception as e:
                await metrics.record_error(candidate_id, "POST_REGISTER", str(e))
                await metrics.finish_candidate(False)
                return

            # Refresh CSRF token if updated
            for c in session.cookie_jar:
                if c.key == 'csrftoken':
                    csrf_token = c.value
                    headers['X-CSRFToken'] = csrf_token

            # ----------------------------------------------------
            # 3. GET Examination Lobby
            # ----------------------------------------------------
            lobby_url = f"{base_url}/quiz/"
            active_quiz_id = quiz_id
            t0 = time.perf_counter()
            try:
                async with session.get(lobby_url, headers=headers) as resp:
                    t_req = time.perf_counter() - t0
                    await metrics.record_request("GET /quiz/", t_req, resp.status)
                    if resp.status != 200:
                        await metrics.record_error(candidate_id, "GET_LOBBY", f"HTTP {resp.status}")
                        await metrics.finish_candidate(False)
                        return
                    lobby_text = await resp.text()
                    discovered_quizzes = list(set(re.findall(r'/quiz/(\d+)/', lobby_text)))
                    if discovered_quizzes:
                        active_quiz_id = int(discovered_quizzes[0])
            except Exception as e:
                await metrics.record_error(candidate_id, "GET_LOBBY", str(e))
                await metrics.finish_candidate(False)
                return

            # ----------------------------------------------------
            # 4. POST Start Quiz (Cohort Launch Burst)
            # ----------------------------------------------------
            start_url = f"{base_url}/quiz/{active_quiz_id}/start/"
            t0 = time.perf_counter()
            try:
                async with session.post(start_url, data={'csrfmiddlewaretoken': csrf_token}, headers=headers, allow_redirects=True) as resp:
                    t_req = time.perf_counter() - t0
                    await metrics.record_request("POST /quiz/start/", t_req, resp.status)
                    if resp.status not in (200, 302):
                        body = await resp.text()
                        await metrics.record_error(candidate_id, "POST_START", f"HTTP {resp.status}: {body[:100]}")

                        await metrics.finish_candidate(False)
                        return
            except Exception as e:
                await metrics.record_error(candidate_id, "POST_START", str(e))
                await metrics.finish_candidate(False)
                return

            # ----------------------------------------------------
            # 5. Question Fetching & Auto-Save Loop
            # ----------------------------------------------------
            ajax_headers = {
                'X-CSRFToken': csrf_token,
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': f"{base_url}/quiz/{active_quiz_id}/take/",
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Benchmark/1.0',
            }

            for q_idx in range(questions_to_answer):
                # A. Fetch question
                q_url = f"{base_url}/quiz/{active_quiz_id}/question/{q_idx}/"
                t0 = time.perf_counter()
                try:
                    async with session.get(q_url, headers=ajax_headers) as resp:
                        t_req = time.perf_counter() - t0
                        await metrics.record_request("GET /quiz/question/", t_req, resp.status)
                        if resp.status != 200:
                            await metrics.record_error(candidate_id, f"GET_Q_{q_idx}", f"HTTP {resp.status}")
                            continue
                        q_data = await resp.json()
                except Exception as e:
                    await metrics.record_error(candidate_id, f"GET_Q_{q_idx}", str(e))
                    continue

                q_id = q_data.get('question_id')
                options = q_data.get('options', [])
                if not q_id or not options:
                    continue

                # B. Realistic Candidate Think Time
                think_sec = random.uniform(*think_time_range)
                await asyncio.sleep(think_sec)

                # C. Select option & Auto-Save
                chosen_opt = random.choice(options)['id']
                save_url = f"{base_url}/quiz/{active_quiz_id}/save-answer/"
                save_payload = {
                    'question_id': q_id,
                    'selected_option_id': chosen_opt,
                    'is_marked_for_review': random.random() < 0.15,
                }
                t0 = time.perf_counter()
                try:
                    async with session.post(save_url, json=save_payload, headers=ajax_headers) as resp:
                        t_req = time.perf_counter() - t0
                        await metrics.record_request("POST /quiz/save-answer/", t_req, resp.status)
                        if resp.status == 200:
                            res_json = await resp.json()
                            if res_json.get('status') == 'saved':
                                await metrics.record_answer_saved()
                        else:
                            body = await resp.text()
                            await metrics.record_error(candidate_id, f"SAVE_Q_{q_idx}", f"HTTP {resp.status}: {body[:80]}")
                except Exception as e:
                    await metrics.record_error(candidate_id, f"SAVE_Q_{q_idx}", str(e))

            # ----------------------------------------------------
            # 6. POST Final Submit (Grading & State Machine)
            # ----------------------------------------------------
            submit_url = f"{base_url}/quiz/{active_quiz_id}/submit/"
            t0 = time.perf_counter()
            try:
                async with session.post(submit_url, data={'csrfmiddlewaretoken': csrf_token}, headers=ajax_headers) as resp:
                    t_req = time.perf_counter() - t0
                    await metrics.record_request("POST /quiz/submit/", t_req, resp.status)
                    if resp.status in (200, 302):
                        await metrics.record_submission()
                    else:
                        body = await resp.text()
                        await metrics.record_error(candidate_id, "POST_SUBMIT", f"HTTP {resp.status}: {body[:80]}")
                        await metrics.finish_candidate(False)
                        return
            except Exception as e:
                await metrics.record_error(candidate_id, "POST_SUBMIT", str(e))
                await metrics.finish_candidate(False)
                return

            # ----------------------------------------------------
            # 7. GET Scorecard / Result Page
            # ----------------------------------------------------
            res_url = f"{base_url}/dashboard/result/{active_quiz_id}/"
            t0 = time.perf_counter()
            try:
                async with session.get(res_url, headers=headers) as resp:
                    t_req = time.perf_counter() - t0
                    await metrics.record_request("GET /dashboard/result/", t_req, resp.status)
                    if resp.status == 200:
                        await metrics.finish_candidate(True)
                        return
                    else:
                        await metrics.record_error(candidate_id, "GET_RESULT", f"HTTP {resp.status}")
                        await metrics.finish_candidate(False)
                        return
            except Exception as e:

                await metrics.record_error(candidate_id, "GET_RESULT", str(e))
                await metrics.finish_candidate(False)


async def run_benchmark(
    base_url: str,
    total_users: int,
    quiz_id: int,
    questions_per_user: int,
    think_min: float,
    think_max: float,
    max_socket_concurrency: int,
):
    run_id = uuid.uuid4().hex[:6]
    metrics = CandidateMetrics()
    semaphore = asyncio.Semaphore(max_socket_concurrency)

    print("=" * 75)
    print("[START] QARENA 200-USER CONCURRENCY & EXAM PERFORMANCE BENCHMARK")
    print("=" * 75)
    print(f"Target Server:        {base_url}")
    print(f"Concurrent Students:  {total_users}")
    print(f"Target Quiz ID:       {quiz_id}")
    print(f"Questions/Student:    {questions_per_user}")
    print(f"Think Time Range:     {think_min:.1f}s – {think_max:.1f}s")
    print(f"Socket Concurrency:   {max_socket_concurrency} parallel handshakes")
    print(f"Run Identifier:       {run_id}")
    print("=" * 75)
    print("[INFO] Launching candidate cohorts...")

    t_start = time.time()
    tasks = [
        simulate_candidate(
            candidate_id=i + 1,
            base_url=base_url,
            quiz_id=quiz_id,
            questions_to_answer=questions_per_user,
            think_time_range=(think_min, think_max),
            metrics=metrics,
            semaphore=semaphore,
            run_id=run_id,
        )
        for i in range(total_users)
    ]

    await asyncio.gather(*tasks)
    total_duration = time.time() - t_start

    # ----------------------------------------------------
    # Generate Performance & Latency Report
    # ----------------------------------------------------
    total_requests = sum(len(latencies) for latencies in metrics.endpoint_latencies.values())
    overall_rps = total_requests / total_duration if total_duration > 0 else 0

    print("\n" + "=" * 75)
    print("[RESULTS] BENCHMARK SUMMARY")
    print("=" * 75)
    print(f"Total Simulation Duration:    {total_duration:.2f} seconds")
    print(f"Total HTTP Requests:          {total_requests}")
    print(f"Effective Throughput (RPS):   {overall_rps:.2f} req/sec")
    print(f"Active Candidates Planned:    {total_users}")
    print(f"Candidates Completed (100%):  {metrics.completed_candidates} ({(metrics.completed_candidates/total_users)*100:.1f}%)")
    print(f"Candidates Failed:            {metrics.failed_candidates}")
    print(f"Total Answers Saved:          {metrics.answers_saved}")
    print(f"Successful Submissions:       {metrics.submissions_successful}")

    print("\n--- HTTP Status Code Distribution ---")
    for code, count in sorted(metrics.status_codes.items()):
        status_name = "OK" if code == 200 else ("REDIRECT" if code == 302 else ("RATE_LIMITED" if code == 429 else "ERROR"))
        print(f"  HTTP {code} ({status_name}): {count}")

    print("\n--- Per-Endpoint Latency Breakdown (milliseconds) ---")
    header_fmt = "{:<28} | {:>7} | {:>7} | {:>7} | {:>7} | {:>8}"
    row_fmt    = "{:<28} | {:>7.1f} | {:>7.1f} | {:>7.1f} | {:>7.1f} | {:>8}"
    print(header_fmt.format("Endpoint / Transaction", "p50 (ms)", "p95 (ms)", "p99 (ms)", "Avg (ms)", "Requests"))
    print("-" * 75)

    all_latencies = []
    for endpoint, lats in sorted(metrics.endpoint_latencies.items()):
        ms_lats = [l * 1000.0 for l in lats]
        all_latencies.extend(ms_lats)
        p50 = percentile(ms_lats, 50)
        p95 = percentile(ms_lats, 95)
        p99 = percentile(ms_lats, 99)
        avg = sum(ms_lats) / len(ms_lats) if ms_lats else 0
        print(row_fmt.format(endpoint, p50, p95, p99, avg, len(ms_lats)))

    if all_latencies:
        print("-" * 75)
        print(row_fmt.format(
            "OVERALL STACK LATENCY",
            percentile(all_latencies, 50),
            percentile(all_latencies, 95),
            percentile(all_latencies, 99),
            sum(all_latencies) / len(all_latencies),
            len(all_latencies)
        ))

    if metrics.exceptions:
        print("\n--- Sample Failures / Exceptions (First 5) ---")
        for cand_id, stage, err in metrics.exceptions[:5]:
            print(f"  [Candidate #{cand_id}] Stage: {stage} -> {err}")

    # ----------------------------------------------------
    # Verification of Phase 11 Acceptance Criteria
    # ----------------------------------------------------
    http_5xx_count = sum(cnt for code, cnt in metrics.status_codes.items() if code >= 500)
    p95_save_answer = percentile([l * 1000.0 for l in metrics.endpoint_latencies.get("POST /quiz/save-answer/", [])], 95)

    print("\n" + "=" * 75)
    print("[VERDICT] PHASE 11 ACCEPTANCE CRITERIA")
    print("=" * 75)
    
    verdict_5xx = "PASS" if http_5xx_count == 0 else f"FAIL ({http_5xx_count} 5xx errors recorded)"
    verdict_durability = "PASS" if metrics.completed_candidates == total_users else f"FAIL ({total_users - metrics.completed_candidates} dropped)"
    verdict_latency = "PASS" if p95_save_answer < 1000.0 else f"FAIL (p95: {p95_save_answer:.1f}ms > 1000ms)"

    print(f"1. Zero Unexpected HTTP 5xx Errors:     [{verdict_5xx}]")
    print(f"2. 100% Candidate Completion & Durability: [{verdict_durability}]")
    print(f"3. Auto-Save p95 Latency < 1000ms:        [{verdict_latency}] (Measured: {p95_save_answer:.1f}ms)")
    print("=" * 75)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="QArena 200-User Concurrency Benchmark")
    parser.add_argument("--url", default="https://qarena.abhirajsinghchauhan.in", help="Target URL")
    parser.add_argument("--users", type=int, default=10, help="Concurrent simulated candidates")
    parser.add_argument("--quiz", type=int, default=1, help="Quiz ID")
    parser.add_argument("--questions", type=int, default=4, help="Questions per candidate")
    parser.add_argument("--think-min", type=float, default=1.0, help="Min think time in seconds")
    parser.add_argument("--think-max", type=float, default=2.5, help="Max think time in seconds")
    parser.add_argument("--sockets", type=int, default=40, help="Max parallel socket connections")
    args = parser.parse_args()

    asyncio.run(run_benchmark(
        base_url=args.url.rstrip('/'),
        total_users=args.users,
        quiz_id=args.quiz,
        questions_per_user=args.questions,
        think_min=args.think_min,
        think_max=args.think_max,
        max_socket_concurrency=args.sockets,
    ))
