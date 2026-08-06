import asyncio
import aiohttp
import time
import random
import argparse

# Target URL default
BASE_URL = "http://localhost:8000"

# ==================== Locust GUI Support ====================
try:
    import sys
    if 'locust' in sys.argv[0]:
        from locust import HttpUser, task, between
        class StudentUser(HttpUser):
            wait_time = between(3, 8)

            def on_start(self):
                res = self.client.get("/accounts/register/")
                csrf = self.client.cookies.get('csrftoken', '')

                student_id = random.randint(10000, 999999)
                self.email = f"locust_student_{student_id}@cyberonites.com"
                self.password = "password123"

                payload = {
                    'csrfmiddlewaretoken': csrf,
                    'full_name': f"Locust Student {student_id}",
                    'email': self.email,
                    'college': 'Locust Test College',
                    'password': self.password,
                    'confirm_password': self.password,
                }
                headers = {
                    'X-CSRFToken': csrf,
                    'Referer': f"{self.host}/accounts/register/"
                }
                self.client.post("/accounts/register/", data=payload, headers=headers)

            @task(3)
            def fetch_question(self):
                q_num = random.randint(0, 4)
                self.client.get(f"/quiz/5/question/{q_num}/")

            @task(2)
            def submit_answer(self):
                csrf = self.client.cookies.get('csrftoken', '')
                headers = {
                    'X-CSRFToken': csrf,
                    'X-Requested-With': 'XMLHttpRequest',
                    'Referer': f"{self.host}/quiz/5/"
                }
                self.client.post("/quiz/5/save-answer/", json={
                    'question_id': random.randint(1, 10),
                    'option_id': random.randint(1, 40),
                    'is_marked_for_review': False
                }, headers=headers)
except Exception:
    pass

async def simulate_student(session, student_id, target_url, quiz_id=1):
    # Stagger launch slightly to simulate real students (and pass single-IP DDoS filters)
    await asyncio.sleep(random.uniform(0.05, 1.5))

    email = f"loadtest_student_{student_id}_{random.randint(100, 999)}@cyberonites.com"
    name = f"Test Student {student_id}"
    college = "Cyberonites Test College"
    password = "password123"

    start_time = time.time()
    try:
        # 1. GET registration page to receive CSRF cookie
        async with session.get(f"{target_url}/accounts/register/") as resp:
            if resp.status != 200:
                return False, time.time() - start_time, f"GET Register page failed: {resp.status}"

        # Extract CSRF token from session cookies
        csrf_token = ''
        for cookie in session.cookie_jar:
            if cookie.key == 'csrftoken':
                csrf_token = cookie.value
                break

        reg_data = {
            'csrfmiddlewaretoken': csrf_token,
            'full_name': name,
            'email': email,
            'college': college,
            'password': password,
            'confirm_password': password,
        }
        headers = {
            'X-CSRFToken': csrf_token,
            'Referer': f"{target_url}/accounts/register/"
        }

        # 2. POST Registration
        async with session.post(f"{target_url}/accounts/register/", data=reg_data, headers=headers, allow_redirects=True) as resp:
            if resp.status not in (200, 302):
                return False, time.time() - start_time, f"Register failed: {resp.status}"

        # 3. Join Quiz / Start Quiz
        async with session.post(f"{target_url}/quiz/{quiz_id}/start/", data={'csrfmiddlewaretoken': csrf_token}, headers=headers, allow_redirects=True) as resp:
            if resp.status not in (200, 302):
                return False, time.time() - start_time, f"Quiz start failed: {resp.status}"

        # 4. Load Questions & Submit Answers (Simulate 3 questions)
        for q_index in range(3):
            await asyncio.sleep(random.uniform(0.5, 1.5))
            async with session.get(f"{target_url}/quiz/{quiz_id}/question/{q_index}/") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    options = data.get('options', [])
                    if options:
                        chosen_opt = random.choice(options)['id']
                        q_id = data['question_id']
                        ans_payload = {
                            'question_id': q_id,
                            'option_id': chosen_opt,
                            'is_marked_for_review': False
                        }
                        ans_headers = {
                            'X-CSRFToken': csrf_token,
                            'X-Requested-With': 'XMLHttpRequest',
                            'Referer': f"{target_url}/quiz/{quiz_id}/"
                        }
                        await session.post(f"{target_url}/quiz/{quiz_id}/save-answer/", json=ans_payload, headers=ans_headers)

        # 5. Submit Quiz
        async with session.post(f"{target_url}/quiz/{quiz_id}/submit/", data={'csrfmiddlewaretoken': csrf_token}, headers=headers, allow_redirects=True) as resp:
            if resp.status in (200, 302):
                return True, time.time() - start_time, "Success"
            return False, time.time() - start_time, f"Submit status: {resp.status}"

    except Exception as e:
        return False, time.time() - start_time, str(e)

async def run_load_test(target_url, total_users, quiz_id):
    print("=" * 65)
    print("CYBERONITES AUTOMATED LOAD TEST")
    print(f"Target Server: {target_url}")
    print(f"Simulating:    {total_users} Concurrent Students")
    print(f"Quiz ID:       {quiz_id}")
    print("=" * 65)

    # Limit concurrent socket handshakes to 30 to prevent Windows Winsock semaphore exhaustion
    connector = aiohttp.TCPConnector(limit=30, limit_per_host=30, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            simulate_student(session, i + 1, target_url, quiz_id)
            for i in range(total_users)
        ]

        t0 = time.time()
        results = await asyncio.gather(*tasks)
        total_time = time.time() - t0

    successes = [r for r in results if r[0]]
    failures = [r for r in results if not r[0]]
    latencies = [r[1] for r in results]

    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    rps = total_users / total_time if total_time > 0 else 0

    print("\n" + "=" * 65)
    print("LOAD TEST RESULTS SUMMARY")
    print("=" * 65)
    print(f"Total Virtual Students:  {total_users}")
    print(f"Successful Completions: {len(successes)} ({len(successes)/total_users*100:.1f}%)")
    print(f"Failed Sessions:        {len(failures)}")
    print(f"Total Benchmark Time:   {total_time:.2f} seconds")
    print(f"Average Student Duration:{avg_latency:.2f} seconds")
    print(f"Throughput (RPS):       {rps:.2f} req/sec")
    print("=" * 65)

    if failures:
        print("\nFailure Sample Error Messages:")
        for f in failures[:5]:
            print(f" - Error: {f[2]}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Automated Load Test for Cyberonites Quiz Platform")
    parser.add_argument("--url", default=BASE_URL, help="Target URL (e.g. https://your-app.onrender.com)")
    parser.add_argument("--users", type=int, default=50, help="Number of concurrent virtual students")
    parser.add_argument("--quiz", type=int, default=1, help="Quiz ID to test against")
    args = parser.parse_args()

    asyncio.run(run_load_test(args.url.rstrip('/'), args.users, args.quiz))
