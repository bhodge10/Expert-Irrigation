#!/bin/sh
# Container startup: migrate, make sure someone can sign in, then serve.
#
# The admin bootstrap lives here because Render's free tier has no shell, so
# the documented path in docs/adding-a-user.md — run `manage.py adduser` in a
# Render shell — isn't available. Once this is on a paid instance, prefer that
# and drop the ADMIN_* variables.
set -e

cd /app/backend

echo "==> Running migrations"
alembic upgrade head

# Idempotent: manage.py declines to touch a user that already exists, and that
# refusal is not a startup failure, hence the `|| true`.
if [ -n "$ADMIN_EMAIL" ] && [ -n "$ADMIN_PASSWORD" ]; then
    echo "==> Ensuring admin user $ADMIN_EMAIL"
    python manage.py adduser \
        --email "$ADMIN_EMAIL" \
        --password "$ADMIN_PASSWORD" \
        --name "${ADMIN_NAME:-Admin}" \
        --initials "${ADMIN_INITIALS:-A}" \
        --color "${ADMIN_COLOR:-#1F7A47}" \
        --role "${ADMIN_ROLE:-Owner}" || true
else
    # Deliberately loud. An empty user table looks identical to a wrong
    # password from the login screen, and that is a miserable thing to debug.
    echo "==> WARNING: ADMIN_EMAIL / ADMIN_PASSWORD not set."
    echo "==> No account will exist and every login attempt will be rejected."
fi

echo "==> Starting uvicorn on port ${PORT:-10000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}"
