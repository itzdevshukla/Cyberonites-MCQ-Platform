#!/usr/bin/env bash
# Render Build Script
# Exit on error
set -o errexit

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Collect static files
python manage.py collectstatic --noinput

# Create data directory for SQLite on Render persistent disk
mkdir -p data

# Run migrations
python manage.py migrate

# Create superuser if not exists
python manage.py shell -c "
from accounts.models import Participant;
import os;
email = os.environ.get('ADMIN_EMAIL', 'admin@quizplatform.com');
if not Participant.objects.filter(email=email).exists():
    Participant.objects.create_superuser(
        username='admin',
        email=email,
        password=os.environ.get('ADMIN_PASSWORD', 'admin123'),
        full_name='Admin',
        college='Platform Admin'
    );
    print(f'Superuser {email} created.');
else:
    print(f'Superuser {email} already exists.');
"
