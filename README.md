# Rotam

> Sınavına giden en kısa rota.

Sınava hazırlanan öğrenciler için kişisel dijital koç (şimdilik YKS: TYT + AYT + YDT). Öğrenciye her gün "bugün şuna çalış" der; kalan süreye, konu seviyesine ve günlük vakte göre plan yapar, çalıştıkça planı kendiliğinden düzeltir.

Proje planı ve geliştirme kuralları: [CLAUDE.md](CLAUDE.md).

**Teknoloji:** Django 5.2 (sunucu tarafı şablonlar, vanilla JS, elle yazılmış SVG grafikler) · PostgreSQL (Supabase) · Vercel. Zamanlanmış iş yok; günlük işlemler kullanıcı siteye girince tembel çalışır.

## Yerel kurulum

Python 3.12 gerekir.

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows (Git Bash: source .venv/Scripts/activate)
pip install -r requirements.txt
cp .env.example .env          # DJANGO_SECRET_KEY değerini değiştir
python manage.py migrate
python manage.py seed_exam_data data/yks_2027.json
python manage.py createsuperuser
python manage.py runserver
```

`DATABASE_URL` boşsa yerelde SQLite (`db.sqlite3`) kullanılır. Admin paneli: `/yonetim/`.

## Testler ve kontroller

```bash
python manage.py test
python manage.py check
python manage.py check_exam_data      # konu verisinin tutarlılığı
```

`check --deploy` üretim ayarlarıyla (yani `DEBUG=False`) çalıştırılmalıdır; yerel `.env` içindeki `DEBUG=True` zaten `W018` gibi uyarılar verir:

```bash
DEBUG=False DJANGO_SECRET_KEY=<50+ karakterlik rastgele değer> ALLOWED_HOSTS=.vercel.app python manage.py check --deploy
```

Beklenen çıktı: `System check identified no issues`. (`DEBUG=False` ile test paketini çalıştırma; `ALLOWED_HOSTS` ve HTTPS yönlendirmesi test istemcisini engeller.)

## Deploy (Vercel + Supabase)

- Veritabanı: Supabase PostgreSQL. Uygulama çalışırken **transaction pooler**, migration için **session pooler** bağlantı dizesi kullanılır (Supabase Dashboard → Connect). Bağlantı dizesinin sonuna `?sslmode=require` eklenir.
- Migration ve veri yükleme yerelden çalıştırılır, Vercel build'inde çalışmaz:

  ```bash
  DATABASE_URL="<session pooler bağlantı dizesi>" python manage.py migrate
  DATABASE_URL="<session pooler bağlantı dizesi>" python manage.py seed_exam_data data/yks_2027.json
  ```

  `migrate` ayrıca hız sınırı için kullanılan önbellek tablosunu (`rotam_cache`) oluşturur ve `public` şemasındaki **tüm tablolarda RLS'yi** açıp her birine "herkese kapalı" politikası (`rotam_deny_all`) ekler. Django tablo sahibi olarak bağlandığı için bundan etkilenmez. Her yeni tablo ekleyen migration'dan sonra `core.rls.enable_rls` çağıran yeni bir migration eklenir.
- Vercel ortam değişkenleri: `DEBUG=False`, `ALLOWED_HOSTS=.vercel.app`, `CSRF_TRUSTED_ORIGINS=https://<proje-adi>.vercel.app`, `DATABASE_URL` (transaction pooler), `DJANGO_SECRET_KEY` (uzun, rastgele). İsteğe bağlı: `SECURE_SSL_REDIRECT` (varsayılan açık), `SECURE_HSTS_SECONDS` (varsayılan 1 yıl).
- Vercel, `manage.py` dosyasından Django projesini otomatik algılar; `STATIC_ROOT` tanımlı olduğu için `collectstatic` build sırasında kendiliğinden çalışır. `vercel.json` gerekmez.
- Deploy sonrası Supabase → Advisors → Security Advisor'da uyarı kalmamalı; ardından siteye girip bir görevi işaretleyerek uygulamanın yazabildiğini doğrula.

## Güvenlik notları

- Her sorgu `request.user` ile filtrelenir; başkasının verisine ait ID istenirse 404 döner.
- Giriş ve kayıt hız sınırı: aynı adresten 15 dakikada 10 başarısız giriş, saatte 10 kayıt denemesi (Django `DatabaseCache`). Adres, Vercel'in kendi yazdığı `X-Forwarded-For` başlığından alınır. Hesap silme ekranındaki parola denemeleri de aynı sınıra tabidir.
- Kayıt formunda gizli bir tuzak alanı (honeypot) vardır.
- Hesap silme (`/ayarlar/hesap-sil/`) parola ister ve tüm verileri kalıcı olarak siler.

## Veri güncelleme

Sınav verisi (`data/yks_2027.json`) slug'a göre upsert edilir; kullanıcı verisine dokunmaz.

1. ÖSYM takvimi / kılavuz açıklandığında JSON'u (tarihler, soru sayıları, konu ağırlıkları) güncelle ya da `/yonetim/` üzerinden düzenle. Kesinleşen değerlerin `is_estimated` işaretini kaldır, `data/DOGRULANACAKLAR.md` listesini güncelle.
2. `python manage.py check_exam_data` ile tutarlılığı doğrula.
3. `DATABASE_URL="<session pooler>" python manage.py seed_exam_data data/yks_2027.json` ile Supabase'e yükle.

Yeni bir sınav (KPSS, ALES, …) için yeni bir `data/*.json` dosyası hazırlanıp aynı komutla yüklenir.
