FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY static /usr/share/nginx/html/static

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
