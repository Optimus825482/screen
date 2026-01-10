#!/bin/bash
set -e

echo "=========================================="
echo "ScreenShare Pro - Starting All Services"
echo "=========================================="

# Initialize PostgreSQL if needed
if [ ! -f "$PGDATA/PG_VERSION" ]; then
    echo "[1/4] Initializing PostgreSQL database..."
    gosu postgres /usr/lib/postgresql/15/bin/initdb -D "$PGDATA" --encoding=UTF8 --locale=C
    
    # Configure PostgreSQL for local connections
    echo "host all all 127.0.0.1/32 md5" >> "$PGDATA/pg_hba.conf"
    echo "local all all trust" >> "$PGDATA/pg_hba.conf"
    
    # Start PostgreSQL temporarily to create database and user
    gosu postgres /usr/lib/postgresql/15/bin/pg_ctl -D "$PGDATA" -w start
    
    # Create database and set password
    gosu postgres psql -c "ALTER USER postgres PASSWORD '$POSTGRES_PASSWORD';"
    gosu postgres psql -c "CREATE DATABASE $POSTGRES_DB;" || true
    
    # Stop PostgreSQL (supervisor will start it)
    gosu postgres /usr/lib/postgresql/15/bin/pg_ctl -D "$PGDATA" -w stop
    
    echo "[1/4] PostgreSQL initialized successfully"
else
    echo "[1/4] PostgreSQL data directory exists, skipping init"
fi

# Ensure Redis directory permissions
echo "[2/4] Setting up Redis..."
chown -R redis:redis /var/lib/redis
chmod 755 /var/lib/redis

# Ensure log directories
echo "[3/4] Setting up log directories..."
mkdir -p /app/logs
chmod -R 755 /app/logs /var/log/supervisor /var/log/postgresql /var/log/redis

echo "[4/4] Starting Supervisor..."
echo "=========================================="
echo "Services: PostgreSQL, Redis, FastAPI App"
echo "App URL: http://0.0.0.0:8005"
echo "=========================================="

exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
