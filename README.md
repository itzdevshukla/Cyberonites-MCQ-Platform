# Cyberonites Online Examination & Real-Time Proctoring Platform

A high-concurrency, security-hardened online MCQ examination platform with real-time live proctoring, asymmetric cryptographic attestation, strict attempt lifecycle state machine, and persistent forensic audit logging.

---

## ⚡ Quick Start: Running on Any Laptop (Local Development)

You **do not** need PostgreSQL or Redis installed locally to run and test this platform. Local development mode uses **SQLite** and an ultra-fast in-memory cache/channels layer out of the box!

### 📋 Prerequisites
* **Python 3.10+** ([Download Python](https://www.python.org/downloads/) — *make sure to check "Add Python to PATH"*)
* **Git** ([Download Git](https://git-scm.com/))
* **Node.js 18+** *(Only required if running the Electron Secure Desktop Browser)*

---

### 🚀 Step-by-Step Setup

#### 1. Clone the Repository
```bash
git clone https://github.com/itzdevshukla/Cyberonites-MCQ-Platform.git
cd Cyberonites-MCQ-Platform
```

#### 2. Create & Activate a Python Virtual Environment
* **Windows (Command Prompt / PowerShell):**
  ```powershell
  python -m venv venv
  venv\Scripts\activate
  ```
* **macOS / Linux:**
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```

#### 3. Install Required Dependencies
```bash
pip install -r requirements.txt
```

#### 4. Setup Environment File (`.env`)
Create your local environment file from the template:
* **Windows:**
  ```powershell
  copy .env.example .env
  ```
* **macOS / Linux:**
  ```bash
  cp .env.example .env
  ```

> **Note:** For local development, ensure these two lines are present in `.env`:
> ```ini
> DEBUG=True
> DJANGO_SETTINGS_MODULE=quiz_platform.settings.development
> ```
> *(Local mode automatically uses SQLite and in-memory caching).*

#### 5. Apply Database Migrations
```bash
python manage.py migrate
```

#### 6. Create Admin / Superuser Account
```bash
python manage.py createsuperuser
```
*(Enter your desired username, email, and password).*

#### 7. Start the Development Server
```bash
python manage.py runserver
```

Now open your web browser:
* **Platform Home / Login:** [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
* **Admin Dashboard:** [http://127.0.0.1:8000/dashboard/](http://127.0.0.1:8000/dashboard/)
* **Participant Lobby:** [http://127.0.0.1:8000/quiz/lobby/](http://127.0.0.1:8000/quiz/lobby/)
* **Security Audit Trail:** [http://127.0.0.1:8000/dashboard/audit-logs/](http://127.0.0.1:8000/dashboard/audit-logs/)

---

## 🖥️ Running the Electron Secure Desktop Browser (Optional)

To test the proctored desktop exam client:

1. Open a new terminal window and navigate to the `secure-app` directory:
   ```bash
   cd secure-app
   ```
2. Install npm dependencies:
   ```bash
   npm install
   ```
3. Launch the secure desktop app:
   ```bash
   npm start
   ```
The app will generate an ephemeral Ed25519 cryptographic key pair in memory and connect to `http://localhost:8000/quiz/`.

---

## 🧪 Running Automated Tests

Run the full security and regression test suite:
```bash
python manage.py test core quiz dashboard accounts leaderboard imports
```

---

## ☁️ Production Deployment (AWS EC2 Ubuntu)

For production deployment with PostgreSQL 16, Redis, Daphne ASGI, and Nginx:
1. Provision an Ubuntu 22.04 / 24.04 LTS EC2 instance.
2. Clone this repository into `/var/www/cyberonites`.
3. Configure your production `.env` with strong passwords and domain names.
4. Run the automated deployment script:
   ```bash
   chmod +x aws_setup.sh
   sudo ./aws_setup.sh
   ```
5. Install free SSL via Certbot:
   ```bash
   sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
   ```
