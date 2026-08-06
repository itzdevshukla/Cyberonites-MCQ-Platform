#!/usr/bin/env bash
# AWS EC2 Ubuntu Automated Production Setup for Cyberonites MCQ Platform
set -e

export DEBIAN_FRONTEND=noninteractive

echo "🚀 Starting AWS EC2 Production Setup..."

# Install Required System Packages
sudo apt update
sudo apt install -y python3-pip python3-venv python3-full nginx postgresql postgresql-contrib redis-server certbot python3-certbot-nginx

# Configure PostgreSQL Database
echo "🐘 Configuring PostgreSQL Database..."
sudo -u postgres psql -c "CREATE DATABASE cyberonites_db;" || true
sudo -u postgres psql -c "CREATE USER cyberonites_user WITH PASSWORD 'CyberonitesSecurePass2026!';" || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE cyberonites_db TO cyberonites_user;" || true
sudo -u postgres psql -c "ALTER USER cyberonites_user CREATEDB;" || true

# Prepare Directory & Copy Files
sudo mkdir -p /var/www/cyberonites
sudo cp -r ./* /var/www/cyberonites/
sudo chown -R $USER:$USER /var/www/cyberonites

# Python Virtual Environment & Requirements
cd /var/www/cyberonites
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Run Migrations & Collect Static
export DJANGO_SETTINGS_MODULE=quiz_platform.settings.production
export POSTGRES_DB=cyberonites_db
export POSTGRES_USER=cyberonites_user
export POSTGRES_PASSWORD=CyberonitesSecurePass2026!
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432

python manage.py migrate
python manage.py collectstatic --noinput

# Create Superuser if not exists
python manage.py shell -c "
from accounts.models import Participant;
import os;
email = os.environ.get('ADMIN_EMAIL', 'admin@cyberonites.com');
password = os.environ.get('ADMIN_PASSWORD', 'admin123');
if not Participant.objects.filter(email=email).exists():
    Participant.objects.create_superuser(
        username='admin',
        email=email,
        password=password,
        full_name='Cyberonites Admin',
        college='Cyberonites Platform'
    );
    print('Superuser created.');
"

# Configure Systemd Service for Daphne ASGI
sudo tee /etc/systemd/system/cyberonites.service > /dev/null <<EOF
[Unit]
Description=Cyberonites MCQ Platform Daphne ASGI Server
After=network.target postgresql.service redis.service

[Service]
User=$USER
WorkingDirectory=/var/www/cyberonites
Environment="PATH=/var/www/cyberonites/venv/bin"
Environment="DJANGO_SETTINGS_MODULE=quiz_platform.settings.production"
Environment="POSTGRES_DB=cyberonites_db"
Environment="POSTGRES_USER=cyberonites_user"
Environment="POSTGRES_PASSWORD=CyberonitesSecurePass2026!"
Environment="POSTGRES_HOST=localhost"
Environment="POSTGRES_PORT=5432"
ExecStart=/var/www/cyberonites/venv/bin/daphne -b 127.0.0.1 -p 8000 quiz_platform.asgi:application
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# Start and enable systemd service
sudo systemctl daemon-reload
sudo systemctl enable cyberonites
sudo systemctl restart cyberonites

# Nginx Configuration
sudo cp nginx_cyberonites.conf /etc/nginx/sites-available/cyberonites
sudo ln -sf /etc/nginx/sites-available/cyberonites /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

echo "✅ AWS EC2 Setup Completed Successfully! Site is live!"
