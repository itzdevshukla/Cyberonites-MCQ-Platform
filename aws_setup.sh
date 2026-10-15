#!/usr/bin/env bash
# AWS EC2 Ubuntu Production Setup for Cyberonites MCQ Platform
# Supports: Ubuntu 22.04 / 24.04 LTS with PostgreSQL 16, Redis, Daphne ASGI & Nginx
set -e

export DEBIAN_FRONTEND=noninteractive

echo "============================================================"
echo "🚀 Starting AWS EC2 Production Setup for Cyberonites MCQ..."
echo "============================================================"

# 1. Install Required System Packages
echo "📦 1/8: Installing system packages (Python, Nginx, PostgreSQL, Redis, Certbot)..."
sudo apt update
sudo apt install -y python3-pip python3-venv python3-full nginx postgresql postgresql-contrib redis-server certbot python3-certbot-nginx

# 2. Start & Enable Core Infrastructure Services
echo "🔄 2/8: Starting & enabling Redis and PostgreSQL..."
sudo systemctl enable redis-server
sudo systemctl restart redis-server
sudo systemctl enable postgresql
sudo systemctl restart postgresql

# 3. Prepare Application Directory
echo "📁 3/8: Setting up /var/www/cyberonites..."
sudo mkdir -p /var/www/cyberonites
sudo cp -a . /var/www/cyberonites/

# Ensure directories and ownership for current user
sudo mkdir -p /var/www/cyberonites/media /var/www/cyberonites/staticfiles
sudo chown -R $USER:$USER /var/www/cyberonites

# Setup .env from .env.example if .env does not exist yet
if [ ! -f /var/www/cyberonites/.env ]; then
    if [ -f /var/www/cyberonites/.env.example ]; then
        echo "📋 Creating /var/www/cyberonites/.env from .env.example..."
        cp /var/www/cyberonites/.env.example /var/www/cyberonites/.env
    else
        echo "⚠️ Warning: Neither .env nor .env.example found. Creating minimal .env..."
        touch /var/www/cyberonites/.env
    fi
fi

# Auto-detect Public IP on AWS EC2 and add to .env
PUBLIC_IP=$(curl -s --connect-timeout 2 http://checkip.amazonaws.com || true)
if [ -n "$PUBLIC_IP" ]; then
    echo "🌐 Detected Public IP: $PUBLIC_IP"
    sed -i "s/your-ec2-ip/$PUBLIC_IP/g" /var/www/cyberonites/.env
fi

# Set secure permissions on .env (owner only read/write)
chmod 600 /var/www/cyberonites/.env
chmod -R 775 /var/www/cyberonites/media

# 4. Load Environment Variables from /var/www/cyberonites/.env
echo "🔐 4/8: Loading database and application credentials from .env..."
set -a
[ -f /var/www/cyberonites/.env ] && . /var/www/cyberonites/.env || true
set +a

# Defaults if not provided in .env
DB_NAME="${POSTGRES_DB:-cyberonites_db}"
DB_USER="${POSTGRES_USER:-cyberonites_user}"
if [ -z "$POSTGRES_PASSWORD" ]; then
    DB_PASS=$(openssl rand -hex 16)
    echo "POSTGRES_PASSWORD=${DB_PASS}" >> /var/www/cyberonites/.env
    echo "🔑 Generated random database password and saved to .env"
else
    DB_PASS="$POSTGRES_PASSWORD"
fi
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"

# 5. Configure PostgreSQL Database & User
echo "🐘 5/8: Configuring PostgreSQL Database ($DB_NAME) and User ($DB_USER)..."
sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME};" 2>/dev/null || true
sudo -u postgres psql -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASS}';" 2>/dev/null || sudo -u postgres psql -c "ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASS}';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};"
sudo -u postgres psql -c "ALTER USER ${DB_USER} CREATEDB;"
sudo -u postgres psql -d ${DB_NAME} -c "GRANT ALL ON SCHEMA public TO ${DB_USER};"
sudo -u postgres psql -d ${DB_NAME} -c "ALTER SCHEMA public OWNER TO ${DB_USER};"

# 6. Setup Python Virtual Environment & Install Dependencies
echo "🐍 6/8: Setting up Python venv and installing requirements..."
cd /var/www/cyberonites
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Run Migrations & Collect Static
echo "⚙️ Running database migrations and collecting static files..."
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-quiz_platform.settings.production}"
python manage.py migrate
python manage.py collectstatic --noinput

# Create Initial Superuser (if not exists)
ADMIN_USER_EMAIL="${ADMIN_EMAIL:-admin@cyberonites.com}"
if [ -z "$ADMIN_PASSWORD" ]; then
    ADMIN_USER_PASS=$(openssl rand -hex 16)
    echo "ADMIN_PASSWORD=${ADMIN_USER_PASS}" >> /var/www/cyberonites/.env
    echo "🔑 Generated random initial admin password and saved to .env: ${ADMIN_USER_PASS}"
else
    ADMIN_USER_PASS="$ADMIN_PASSWORD"
fi

python manage.py shell -c "
from accounts.models import Participant
import os
email = os.environ.get('ADMIN_USER_EMAIL', 'admin@cyberonites.com')
password = os.environ.get('ADMIN_USER_PASS', '')
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

# 7. Configure Systemd Service for Daphne ASGI 4-Worker Cluster
echo "🔧 7/8: Configuring 4-worker Daphne ASGI cluster (/etc/systemd/system/cyberonites@.service)..."
sudo tee /etc/systemd/system/cyberonites@.service > /dev/null <<EOF
[Unit]
Description=QArena Daphne ASGI Worker on port %i
After=network.target postgresql.service redis-server.service

[Service]
User=$USER
WorkingDirectory=/var/www/cyberonites
EnvironmentFile=/var/www/cyberonites/.env
Environment="PATH=/var/www/cyberonites/venv/bin"
Environment="DJANGO_SETTINGS_MODULE=quiz_platform.settings.production"
ExecStart=/var/www/cyberonites/venv/bin/daphne -b 127.0.0.1 -p %i quiz_platform.asgi:application
Restart=always
RestartSec=3
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
# Disable legacy single worker if active
sudo systemctl stop cyberonites 2>/dev/null || true
sudo systemctl disable cyberonites 2>/dev/null || true

# Enable and start 4 cluster workers
for port in 8000 8001 8002 8003; do
    sudo systemctl enable "cyberonites@$port"
    sudo systemctl restart "cyberonites@$port"
done


# 8. Configure Nginx Reverse Proxy & WebSocket Upgrades
echo "🌐 8/8: Configuring Nginx reverse proxy (/etc/nginx/sites-available/cyberonites)..."
sudo cp nginx_cyberonites.conf /etc/nginx/sites-available/cyberonites
sudo ln -sf /etc/nginx/sites-available/cyberonites /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

echo "============================================================"
echo "🎉 AWS EC2 Production Setup Completed Successfully!"
echo "Site is live on port 80 via Nginx!"
echo ""
echo "👉 NEXT STEP FOR HTTPS / SSL (Let's Encrypt Certbot):"
echo "   sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com"
echo "============================================================"
