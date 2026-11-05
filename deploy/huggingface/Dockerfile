# Hugging Face Docker Space for PackWise.
# The Space does not build the app. It runs the image published to Docker Hub by CI.
# deploy.py rewrites the FROM line to pin the exact image built and tested for a commit.
FROM docker.io/sanjaymarathi/packwise:latest

# Hugging Face routes the Space's HTTPS traffic to this port (app_port in README.md).
ENV PORT=7860
# TLS is terminated at Hugging Face's edge, which forwards X-Forwarded-Proto: https (verified:
# Django sends HSTS on live responses). Django's own HTTPS redirect therefore stays on (the
# production default), as defence in depth behind the edge's HTTP->HTTPS redirect.
# The Space page on huggingface.co shows the app in an iframe. Every other origin stays blocked.
ENV DJANGO_FRAME_ANCESTORS=https://huggingface.co
# No pre-deploy hook on Spaces: migrate (and load the idempotent demo catalogue) at start-up.
ENV RUN_MIGRATIONS=true
ENV SEED_DEMO_DATA=true
ENV WEB_CONCURRENCY=2
ENV LOG_FORMAT=json

# Secrets are set in the Space settings (never here): DJANGO_SECRET_KEY, DATABASE_URL.

EXPOSE 7860
