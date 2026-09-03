#!/usr/bin/env bash
# Render build step for the web service. Workers/beat use a plain
# `pip install -r requirements/prod.txt` instead -- migrations should run
# from exactly one place per deploy, not once per service.
set -o errexit

pip install -r requirements/prod.txt
python manage.py collectstatic --noinput
python manage.py migrate
