# Rotam

> Sınavına giden en kısa rota.

Sınava hazırlanan öğrenciler için kişisel dijital koç. Proje planı ve geliştirme kuralları: [CLAUDE.md](CLAUDE.md).

## Yerel kurulum

Python 3.12 gerekir.

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows (Git Bash: source .venv/Scripts/activate)
pip install -r requirements.txt
cp .env.example .env          # DJANGO_SECRET_KEY değerini değiştir
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

`DATABASE_URL` boşsa yerelde SQLite (`db.sqlite3`) kullanılır.

## Testler

```bash
python manage.py test
python manage.py check
```

## Deploy (Vercel + Supabase)

- Veritabanı: Supabase PostgreSQL. Uygulama çalışırken **transaction pooler**, migration için **session pooler** bağlantı dizesi kullanılır (Supabase Dashboard → Connect).
- Migration yerelden çalıştırılır, Vercel build'inde çalışmaz:

  ```bash
  DATABASE_URL="<session pooler bağlantı dizesi>" python manage.py migrate
  ```

- Vercel ortam değişkenleri: `DEBUG=False`, `ALLOWED_HOSTS=.vercel.app`, `CSRF_TRUSTED_ORIGINS=https://<proje-adi>.vercel.app`, `DATABASE_URL`, `DJANGO_SECRET_KEY`.
- Vercel, `manage.py` dosyasından Django projesini otomatik algılar; `STATIC_ROOT` tanımlı olduğu için `collectstatic` build sırasında kendiliğinden çalışır.
