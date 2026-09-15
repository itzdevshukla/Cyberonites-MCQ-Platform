#!/usr/bin/env bash
# AWS EC2 Ubuntu Automated Production Setup for Cyberonites MCQ Platform
# Supports: Ubuntu 22.04 / 24.04 LTS with PostgreSQL, Redis, Daphne ASGI & Nginx
set -e

export DEBIAN_FRONTEND=noninteractive

echo "🚀 Starting AWS EC2 Production Setup for Cyberonites MCQ Platform..."

# 1. Install Required System Packages
echo "📦 Installing system dependencies (Python, Nginx, PostgreSQL, Redis, Certbot)..."
sudo apt update
sudo apt install -y python3-pip python3-venv python3-full nginx postgresql postgresql-contrib redis-server certbot python3-certbot-nginx

# 2. Start & Enable Core Services
echo "🔄 Starting Redis & PostgreSQL services..."
sudo systemctl enable redis-server
sudo systemctl restart redis-server
sudo systemctl enable postgresql
sudo systemctl restart postgresql

# 3. Configure PostgreSQL Database & Dedicated User
echo "🐘 Configuring PostgreSQL Database & User..."
sudo -u postgres psql -c "CREATE DATABASE cyberonites_db;" || true
sudo -u postgres psql -c "CREATE USER cyberonites_user WITH PASSWORD 'CyberonitesSecurePass2026!';" || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE cyberonites_db TO cyberonites_user;" || true
sudo -u postgres psql -c "ALTER USER cyberonites_user CREATEDB;" || true
sudo -u postgres psql -d cyberonites_db -c "GRANT ALL ON SCHEMA public TO cyberonites_user;" || true
sudo -u postgres psql -d cyberonites_db -c "ALTER SCHEMA public OWNER TO cyberonites_user;" || true

# 4. Prepare Application Directory
echo "📁 Setting up /var/www/cyberonites..."
sudo mkdir -p /var/www/cyberonites
sudo cp -a . /var/www/cyberonites/
if [ ! -f /var/www/cyberonites/.env ] && [ -f /var/www/cyberonites/.env.example ]; then
    echo "📋 Creating initial .env from .env.example..."
    sudo cp /var/www/cyberonites/.env.example /var/www/cyberonites/.env
fi
sudo mkdir -p /var/www/cyberonites/media /var/www/cyberonites/staticfiles
sudo chown -R $USER:$USER /var/www/cyberonites
chmod -R 775 /var/www/cyberonites/media

# 5. Setup Python Virtual Environment & Install Requirements
cd /var/www/cyberonites
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 6. Database Migrations & Static Files Collection
echo "⚙️ Running database migrations and collecting static files..."
export DJANGO_SETTINGS_MODULE=quiz_platform.settings.production
export POSTGRES_DB=cyberonites_db
export POSTGRES_USER=cyberonites_user
export POSTGRES_PASSWORD=CyberonitesSecurePass2026!
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export REDIS_URL=redis://127.0.0.1:6379/1

python manage.py migrate
python manage.py collectstatic --noinput

# 7. Create Superuser (if none exists)
python manage.py shell -c "
from accounts.models import Participant
import os
email = os.environ.get('ADMIN_EMAIL', 'admin@cyberonites.com')
password = os.environ.get('ADMIN_PASSWORD', 'CyberAdmin2026!')
if not Participant.objects.filter(email=email).exists():
    Participant.objects.create_superuser(
        username='admin',
        email=email,
        password=password,
        full_name='Cyberonites Admin',
        college='Cyberonites Platform'
    )
    print(f'✅ Superuser {email} created successfully.')
else:
    print(f'ℹ️ Superuser {email} already exists.')
"

# 8. Configure Systemd Service for Daphne ASGI Server
echo "🔧 Configuring systemd service (/etc/systemd/system/cyberonites.service)..."
sudo tee /etc/systemd/system/cyberonites.service > /dev/null <<EOF
[Unit]
Description=Cyberonites MCQ Platform Daphne ASGI Server
After=network.target postgresql.service redis-server.service

[Service]
User=$USER
WorkingDirectory=/var/www/cyberonites
EnvironmentFile=-/var/www/cyberonites/.env
Environment="PATH=/var/www/cyberonites/venv/bin"
Environment="DJANGO_SETTINGS_MODULE=quiz_platform.settings.production"
Environment="POSTGRES_DB=cyberonites_db"
Environment="POSTGRES_USER=cyberonites_user"
Environment="POSTGRES_PASSWORD=CyberonitesSecurePass2026!"
Environment="POSTGRES_HOST=localhost"
Environment="POSTGRES_PORT=5432"
Environment="REDIS_URL=redis://127.0.0.1:6379/1"
ExecStart=/var/www/cyberonites/venv/bin/daphne -b 127.0.0.1 -p 8000 quiz_platform.asgi:application
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# 9. Start & Enable Daphne Systemd Service
sudo systemctl daemon-reload
sudo systemctl enable cyberonites
sudo systemctl restart cyberonites

# 10. Configure Nginx Reverse Proxy & WebSocket Upgrades
echo "🌐 Configuring Nginx (/etc/nginx/sites-available/cyberonites)..."
sudo cp nginx_cyberonites.conf /etc/nginx/sites-available/cyberonites
sudo ln -sf /etc/nginx/sites-available/cyberonites /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

echo "============================================================"
echo "🎉 AWS EC2 Production Setup Completed Successfully!"
echo "Server is live on Nginx port 80!"
echo ""
echo "👉 NEXT STEP FOR FREE SSL/HTTPS (Certbot):"
echo "   sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com"
echo "============================================================"
