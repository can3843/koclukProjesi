# Rotam — Proje Planı ve Claude Code Talimatları

> Bu dosya projenin **tek doğru kaynağıdır**. Repo kök dizininde `CLAUDE.md` adıyla durur; Claude Code her oturumda bunu otomatik okur.
> Kullanıcı hangi fazı isterse **yalnızca o faz** uygulanır.
> Slogan: **"Sınavına giden en kısa rota."**

---

## 0. Claude Code için çalışma kuralları

1. **Sadece istenen fazı uygula.** Sonraki fazların işine başlama, "hazır yapmışken" özellik ekleme.
2. **Bağımlılık listesi sabittir** (bkz. §2.4). Listede olmayan bir paket gerekiyorsa önce kullanıcıya sor ve gerekçesini yaz. Grafikler dahil hiçbir JS kütüphanesi kullanılmaz.
3. **Dil kuralı:** Kod, değişken, fonksiyon, model, commit mesajı ve yorumlar **İngilizce**; kullanıcıya görünen tüm metinler **Türkçe**.
4. **Platform yapılandırmasını ezberden yazma.** Vercel ve Supabase sık değişiyor. `vercel.json`, veritabanı bağlantısı veya deploy ayarı yazmadan önce §12'deki güncel resmi dokümanlara bak.
5. **Veri uydurma yasağı.** Sınav tarihleri, soru sayıları ve konu bazlı veriler (§5) resmi bir kaynağa dayanmıyorsa **"tahmini"** olarak işaretlenir ve `data/DOGRULANACAKLAR.md` listesine eklenir. Hiçbir sayı kesinmiş gibi sunulmaz.
6. **Plan motoru saf Python'dur** (§6). Veritabanına, Django'ya, saate erişmez; girdi alır, çıktı verir. Tüm ayarlanabilir sayılar tek dosyada (`planner/engine/config.py`) durur.
7. **Gizlilik:** Her sorgu `request.user` ile filtrelenir. Başka kullanıcının verisine ait bir ID istenirse **404** döner.
8. **Gizli bilgi commit edilmez.** `.env` her zaman `.gitignore` içinde; örnek değerler `.env.example`'da.
9. **Her fazın sonunda:**
   - `python manage.py test` çalıştır, hepsi geçmeli.
   - `python manage.py check` hatasız olmalı.
   - Bu dosyadaki **§15 Durum** bölümünü güncelle.
   - Kullanıcıya kısa özet ver: ne yapıldı, nasıl denenir, kullanıcının yapması gereken bir şey var mı (ör. Supabase'e migration, Vercel ortam değişkeni).
10. **Basit tut.** Bu bir prototip. Soyutlama katmanı, servis sınıfı hiyerarşisi, gereksiz desen yok. Django geleneklerini kullan.

---

## 1. Proje özeti

**Rotam**, sınava hazırlanan öğrencilere kişisel bir dijital koç gibi davranan bir web uygulamasıdır. Öğrenciye her gün **"bugün şuna çalış, şunu yap"** der ve sınava kalan süreye göre plan yapar.

**Sorun:** Özel koçluk pahalı. İnternetteki hazır programlar herkese aynı planı veriyor; 6 ay kalan biriyle 2 ay kalan birine, sıfırdan başlayanla yarıda olana aynı şeyi söylüyor.

**Çözüm:** Rotam her öğrencinin
- sınava **kalan süresine**,
- konu konu **seviyesine**,
- günlük **çalışabileceği vakte**

göre kişisel plan yapar. Vakit yetmiyorsa bunu dürüstçe söyler, en fazla neti getirecek konuları seçer ve geri kalanını bıraktırır. Öğrenci çalıştıkça, çalışamadıkça ve deneme çözdükçe planı kendiliğinden düzeltir.

**İlk sürüm kapsamı:** Yalnızca **YKS** (TYT + AYT + YDT; SAY / EA / SÖZ / DİL alanları). KPSS, ALES, DGS, YDS sonraki fazlarda eklenecek; veri modeli baştan çok sınavlı kurulur (§5).

**Temel ilkeler**
- **Dürüst koç:** Puan sözü yok; tahminler her zaman **aralık** olarak ve "tahmini" etiketiyle gösterilir.
- **Suçlamayan dil:** Çalışılamayan gün "başarısızlık" değil, planın yeniden dağıtıldığı bir olaydır.
- **Sağlıklı sınırlar:** Günlük çalışma süresi makul aralıkta tutulur, haftada bir dinlenme günü önerilir (§7.2).
- **Kişisel veri kişiye özel:** Hiçbir kullanıcı başka kullanıcının hiçbir verisini göremez. Sosyal özellik yok.
- **Kararı öğrenci verir:** Sistem bir konuyu plandan çıkarmayı yalnızca **önerir**; kapsam daraltma öğrenci onaylamadan uygulanmaz.

**Hedef kitle:** 16–25 yaş, çoğunlukla telefondan giren, sınav stresi yaşayan öğrenciler.

---

## 2. Teknoloji kararları

### 2.1 Neden Django?

Vercel'in Python runtime'ı FastAPI ve Django'yu resmi olarak destekliyor; Django projeleri `manage.py` dosyasından otomatik algılanıyor ve `STATIC_ROOT` tanımlıysa `collectstatic` build sırasında otomatik çalışıp statik dosyalar CDN'den sunuluyor. Bu projede kullanıcı hesapları, oturum, CSRF, ORM + migration, şablonlar, form doğrulama ve **konu veritabanını yönetmek için admin paneli** gerekiyor; Django bunların hepsini hazır getiriyor. **Karar: Django.**

### 2.2 Mimari

- **Sunucu tarafı render** edilen Django şablonları.
- **Vanilla JavaScript** ile kademeli iyileştirme: görev işaretleme, sekme geçişleri, grafikler JS ile akıcı; JS kapalıysa formlar normal POST ile çalışır.
- Frontend framework, build adımı, bundler, grafik kütüphanesi **yok**. Grafikler elle yazılmış **SVG** ile çizilir.
- Supabase **yalnızca PostgreSQL** olarak kullanılır. Supabase Auth/Storage/Realtime kullanılmaz.
- **Zamanlanmış iş (cron) yok.** Günlük görev üretimi, kaçırılan görevlerin işlenmesi ve haftalık değerlendirme, kullanıcı siteye girdiğinde **tembel (lazy)** olarak yapılır (§6.9). Bu, serverless ortamda en basit ve en sağlam yoldur.

### 2.3 Sürümler

- Python **3.12** (`.python-version` ile sabitlenir)
- Django **5.2 LTS**
- PostgreSQL (Supabase)

### 2.4 Bağımlılıklar (`requirements.txt`)

```
Django>=5.2,<5.3
psycopg[binary]>=3.2
dj-database-url>=2.2
python-dotenv>=1.0
```

Başka paket eklenmez. Testler Django'nun kendi test çatısıyla yazılır.

---

## 3. Kullanıcı yolculuğu (özet)

1. **Karşılama sayfası** (`/`): Rotam'ın ne yaptığını anlatır, "Hemen başla" → kayıt.
2. **Kayıt** (ad, e-posta, parola) → otomatik giriş → **Tanışma**.
3. **Tanışma** (5 adım, §7): sınav ve alan → günlük vakit → verimli saat ve dinlenme günü → konu seviyeleri → deneme netleri ve hedef (opsiyonel).
4. **Gerçekçilik raporu**: "Bu kadar vaktin var, bu kadar gerekiyor; şu konulara odaklan, şunları bırak; tahmini net aralığın şu."
5. **Bugün ekranı** (`/bugun/`): her gün net görevler. İşaretle, doğru-yanlış gir.
6. Plan **kendini düzeltir**: kaçırılan görevler yayılır, tekrarlar zamanında gelir, faz değişince strateji değişir, denemeler zayıf konuları öne çeker.
7. **Haftalık değerlendirme** ve **ilerleme paneli** öğrenciyi motive eder.

---

## 4. Özellikler ve iş kuralları

### 4.1 Üyelik

- **Kayıt alanları:** ad (zorunlu, 2–30 karakter), e-posta, parola, parola tekrar.
- **Giriş:** e-posta + parola. E-posta küçük harfe normalize edilir, büyük/küçük harf duyarsız benzersizdir.
- **Parola:** Django'nun varsayılan doğrulayıcıları (en az 8 karakter vb.), Türkçe hata mesajları.
- Kayıttan sonra otomatik giriş ve tanışmaya yönlendirme.
- Tanışmayı tamamlamamış kullanıcı, uygulama sayfalarına girmeye çalışırsa kaldığı tanışma adımına yönlendirilir.
- Çıkış yalnızca **POST** ile.
- E-posta doğrulama ve parola sıfırlama **ilk sürümde yok** (e-posta servisi gerektirir; §14).
- Faz 6'da **hesabı ve tüm verileri silme** seçeneği eklenir.

### 4.2 Sınav, alan ve tarih

- Kullanıcı bir **sınav** (ilk sürümde yalnızca "YKS 2027") ve **alan** seçer: SAY, EA, SÖZ, DİL.
- Alan, hangi testlerin plana dahil olacağını belirler (§5.3).
- Sınav tarihleri `ExamSession` kayıtlarında tutulur. Plan hesaplarında **ilk oturumun (TYT) tarihi** sınav günü kabul edilir.
- Tarih tahminiyse (`date_is_estimated=True`) arayüzde sınav geri sayımının yanında **"tahmini tarih"** rozeti görünür.

### 4.3 Konu seviyeleri

Her konu için üç seviye:

| Kod | Arayüzde | Anlamı |
|---|---|---|
| 0 | Hiç bilmiyorum | Konu sıfırdan öğrenilecek |
| 1 | Biraz biliyorum | Konu tekrar edilip pekiştirilecek |
| 2 | İyiyim | Sadece soru pratiği ve tekrar |

Varsayılan seviye **0**. Kullanıcı ayarlardan seviyeleri sonradan değiştirebilir; bu yeniden planlamayı tetikler.

### 4.4 Görev türleri

| Tür (`kind`) | Arayüz örneği | Not |
|---|---|---|
| `learn` | Matematik – Problemler: 45 dk konu çalışması | Konu anlatımı / not çıkarma |
| `practice` | Matematik – Problemler: 30 soru | Soru sayısı = dakika ÷ dersin soru başına dakikası |
| `review` | Tekrar: Oran-Orantı – 15 soru | Aralıklı tekrar (§6.7) |
| `mock` | TYT Denemesi – 165 dk, gerçek sınav gibi süre tut | Deneme |
| `mock_review` | Deneme analizi: yanlışlarını incele – 60 dk | Denemeden sonra |

Görev durumları: `pending` (bekliyor), `done` (yapıldı), `skipped` (kullanıcı atladı), `missed` (günü geçti, yapılmadı).

### 4.5 Görev tamamlama

- Kullanıcı görevi işaretler. `practice` ve `review` görevlerinde **doğru / yanlış / boş** sayıları opsiyonel olarak girilir (toplam, hedef soru sayısının 2 katını geçemez).
- Girilen sonuçlar konunun doğruluk oranını günceller (§6.8).
- Kullanıcı bir görevi **atlayabilir** (ör. "bugün yapamayacağım"); atlanan görevin süresi konuya geri döner ve ileriki günlere dağıtılır.
- Yapılan görev geri alınabilir (aynı gün içinde).

### 4.6 Denemeler

- Kullanıcı deneme sonucunu girer: oturum (TYT/AYT/YDT), tarih, **ders ders** doğru/yanlış/boş.
- Net = doğru − yanlış ÷ 4. Toplamlar dersin soru sayısını geçemez.
- Deneme girildikten sonra opsiyonel olarak **"bu denemede zorlandığın konuları işaretle"** adımı: işaretlenen konular plana daha fazla ağırlıkla döner (§6.8).
- Planlanan `mock` görevi ile girilen deneme sonucu ilişkilendirilebilir (aynı gün ve oturumsa otomatik).

### 4.7 Haftalık değerlendirme

- Her hafta **pazartesi** başlar. Kullanıcı yeni haftada siteye ilk girdiğinde, geçen haftanın değerlendirmesi oluşturulur ve `/bugun/` üstünde bir kart olarak gösterilir.
- İçerik: planın yüzde kaçı yapıldı, toplam çalışma süresi, çözülen soru ve doğruluk, çalışma serisi, deneme netlerindeki değişim, gelecek haftanın odak dersleri ve kurala dayalı kısa bir koç mesajı (§8.6).

### 4.8 İlerleme paneli

- Konu tamamlama haritası (ders ders, renkli durum kutucukları).
- Deneme netleri grafiği (oturum ve ders bazında, SVG çizgi grafik).
- Çalışma serisi ve son 8 haftanın haftalık çalışma süreleri (SVG çubuk grafik).
- **"Bu gidişle sınav günü tahmini netin"** göstergesi (aralık + "tahmini" etiketi).

---

## 5. Veri modeli

Django uygulamaları: `accounts`, `catalog` (sınav verisi), `planner` (öğrenci, plan, görev, deneme, motor), `core` (karşılama sayfası, ortak şablonlar, RLS migration'ı).

**Özel kullanıcı modeli ilk migration'dan önce tanımlanır.**

### 5.1 `accounts.User` (`AbstractUser`'dan)

| Alan | Not |
|---|---|
| `email` | `EmailField`, büyük/küçük harf duyarsız benzersiz (`UniqueConstraint(Lower("email"))`) |
| `first_name` | Kayıttaki "ad"; zorunlu |
| `username` | Kaldırılır (`username = None`) |

- `USERNAME_FIELD = "email"`, `REQUIRED_FIELDS = ["first_name"]`, e-posta ile çalışan özel `UserManager`.
- `AUTH_USER_MODEL = "accounts.User"`.

### 5.2 `catalog` — sınav verisi

Hiyerarşi: **Exam → ExamSession → ExamTest → Subject → Topic**, ayrıca **Track** (alan).

**`Exam`**
| Alan | Not |
|---|---|
| `slug` | ör. `yks-2027` |
| `name` | "YKS 2027" |
| `is_active` | Kayıtta seçilebilir mi |

**`ExamSession`** (oturum)
| Alan | Not |
|---|---|
| `exam` | FK |
| `code` | `TYT`, `AYT`, `YDT` |
| `name` | "Temel Yeterlilik Testi" |
| `date` | `DateField` |
| `date_is_estimated` | `BooleanField` |
| `duration_minutes` | ör. 165 |
| `order` | |

**`ExamTest`** (resmi test; soru sayısı resmi kaynaktan)
| Alan | Not |
|---|---|
| `session` | FK |
| `slug`, `name` | ör. `tyt-fen`, "Fen Bilimleri Testi" |
| `question_count` | ör. 20 |
| `order` | |

**`Subject`** (ders; deneme sonuçları bu seviyede girilir)
| Alan | Not |
|---|---|
| `test` | FK |
| `slug`, `name` | ör. `tyt-fizik`, "Fizik" |
| `question_count` | ör. 7 |
| `question_count_is_estimated` | Resmi ayrım yoksa `True` (ör. TYT Matematik/Geometri ayrımı) |
| `minutes_per_question` | Pratik görevinde soru sayısını hesaplamak için (ör. Türkçe 1.2, Matematik 2.0); tahmini |
| `group` | `quant` (sayısal), `verbal` (sözel), `science` (fen), `social` (sosyal), `language` (dil) — derslerin karıştırılmasında kullanılır |
| `color` | Arayüz rengi (hex) |
| `order` | |

**`Topic`** (konu; sistemin kalbi)
| Alan | Not |
|---|---|
| `subject` | FK, `related_name="topics"` |
| `slug`, `name` | |
| `order` | Müfredattaki doğal sıra |
| `avg_questions` | `DecimalField(4,2)` — son yıllarda ortalama soru sayısı |
| `learn_hours` | `DecimalField(5,1)` — sıfırdan öğrenip temel soru çözebilmek için tahmini saat |
| `difficulty` | 1 kolay, 2 orta, 3 zor |
| `is_estimated` | Sayılar resmi/derlenmiş bir kaynağa dayanmıyorsa `True` |
| `source_note` | Verinin nereden geldiği (serbest metin) |
| `prerequisites` | `ManyToManyField("self", symmetrical=False, related_name="unlocks", blank=True)` |
| `is_active` | |

- **Verimlilik puanı** (hesaplanır, saklanmaz): `avg_questions / learn_hours`.
- Doğrulama kuralları (`check_exam_data` komutu, §5.5):
  - Bir dersin konularının `avg_questions` toplamı dersin `question_count`'una **eşit** olmalı (±0.5 tolerans; değilse uyarı).
  - Bir testin derslerinin `question_count` toplamı testin `question_count`'una eşit olmalı.
  - Ön koşul grafiğinde **döngü olmamalı**; bir konu kendi ön koşulu olamaz; ön koşullar aynı sınav içinde olmalı.
  - `learn_hours > 0`, `avg_questions >= 0`.

**`Track`** (alan)
| Alan | Not |
|---|---|
| `exam` | FK |
| `code` | `SAY`, `EA`, `SOZ`, `DIL` |
| `name` | "Sayısal" vb. |
| `tests` | `ManyToManyField(ExamTest)` — plana dahil testler |

### 5.3 YKS başlangıç verisi

> **Uyarı:** Aşağıdaki yapı **2026 YKS** düzenine göredir. 2027 YKS kılavuzu yayımlandığında doğrulanmalıdır. ÖSYM'nin 2027 takvimini Kasım 2026 ortasında açıklaması bekleniyor; o zamana kadar tarihler **tahmini** işaretlenir.

**Oturumlar**
| Kod | Ad | Tarih (tahmini) | Süre |
|---|---|---|---|
| TYT | Temel Yeterlilik Testi | 2027-06-19 | 165 dk |
| AYT | Alan Yeterlilik Testleri | 2027-06-20 | 180 dk |
| YDT | Yabancı Dil Testi | 2027-06-20 | 120 dk |

**Testler ve dersler** (`*` = ders ayrımı tahmini)

TYT (120 soru):
- Türkçe Testi (40): Türkçe 40
- Temel Matematik Testi (40): Matematik 30\*, Geometri 10\*
- Sosyal Bilimler Testi (20): Tarih 5, Coğrafya 5, Felsefe 5, Din Kültürü ve Ahlak Bilgisi 5
- Fen Bilimleri Testi (20): Fizik 7, Kimya 7, Biyoloji 6

AYT (160 soru):
- Matematik Testi (40): Matematik 30\*, Geometri 10\*
- Fen Bilimleri Testi (40): Fizik 14, Kimya 13, Biyoloji 13
- Türk Dili ve Edebiyatı–Sosyal Bilimler-1 Testi (40): Türk Dili ve Edebiyatı 24, Tarih-1 10, Coğrafya-1 6
- Sosyal Bilimler-2 Testi (40): Tarih-2 11, Coğrafya-2 11, Felsefe Grubu 12, Din Kültürü ve Ahlak Bilgisi 6

YDT (80 soru):
- Yabancı Dil Testi (80): İngilizce 80 (ilk sürümde yalnızca İngilizce)

**Alanlar**
| Alan | Testler |
|---|---|
| SAY | TYT'nin tamamı + AYT Matematik + AYT Fen Bilimleri |
| EA | TYT'nin tamamı + AYT Matematik + AYT TDE–Sosyal-1 |
| SÖZ | TYT'nin tamamı + AYT TDE–Sosyal-1 + AYT Sosyal-2 |
| DİL | TYT'nin tamamı + YDT |

**Puan hesaplanmaz.** Katsayılar her yıl değiştiği için uygulama yalnızca **net** gösterir. Hedef ve tahminler net üzerinden konuşulur.

### 5.4 Konu verisinin hazırlanması

- Tüm sınav verisi tek bir JSON dosyasında durur: `data/yks_2027.json`.
- Konu listeleri **MEB/ÖSYM'nin yayımladığı güncel konu ve kazanım listelerinden** çıkarılır. Kullanılan kaynaklar `source_note` alanına ve `data/KAYNAKLAR.md` dosyasına yazılır.
- `avg_questions` ve `learn_hours` değerleri için güvenilir bir derleme yoksa makul tahminler girilir, **`is_estimated: true`** yapılır ve `data/DOGRULANACAKLAR.md` dosyasına ders ders listelenir. Her dersin konu toplamı dersin soru sayısına eşitlenir.
- Ön koşullar yalnızca **bariz** olanlar için girilir (ör. "Üslü Sayılar" → "Köklü Sayılar"; "Türev" → "İntegral"). Emin olunmayan ön koşul girilmez.

Örnek JSON biçimi:
```json
{
  "exam": {"slug": "yks-2027", "name": "YKS 2027"},
  "sessions": [
    {"code": "TYT", "name": "Temel Yeterlilik Testi", "date": "2027-06-19",
     "date_is_estimated": true, "duration_minutes": 165, "order": 1}
  ],
  "tests": [
    {"session": "TYT", "slug": "tyt-temel-matematik", "name": "Temel Matematik Testi",
     "question_count": 40, "order": 2}
  ],
  "subjects": [
    {"test": "tyt-temel-matematik", "slug": "tyt-matematik", "name": "Matematik",
     "question_count": 30, "question_count_is_estimated": true,
     "minutes_per_question": 2.0, "group": "quant", "color": "#5B5BD6", "order": 1}
  ],
  "topics": [
    {"subject": "tyt-matematik", "slug": "tyt-mat-uslu-sayilar", "name": "Üslü Sayılar",
     "order": 5, "avg_questions": 1.0, "learn_hours": 6, "difficulty": 1,
     "is_estimated": true, "source_note": "Tahmini – doğrulanacak", "prerequisites": []}
  ],
  "tracks": [
    {"code": "SAY", "name": "Sayısal",
     "tests": ["tyt-turkce", "tyt-temel-matematik", "tyt-sosyal", "tyt-fen", "ayt-matematik", "ayt-fen"]}
  ]
}
```

### 5.5 Yönetim komutları

- `python manage.py seed_exam_data data/yks_2027.json` — veriyi **slug'a göre upsert** eder (tekrar çalıştırılabilir; mevcut kullanıcı verisini bozmaz). Önce `check_exam_data` kurallarını çalıştırır, hata varsa durur.
- `python manage.py check_exam_data` — §5.2'deki doğrulama kurallarını çalıştırır, uyarıları ve tahmini işaretli kayıt sayısını raporlar.

### 5.6 `planner` — öğrenci tarafı

**`StudentProfile`** (`OneToOne` → User)
| Alan | Not |
|---|---|
| `exam`, `track` | FK |
| `weekday_minutes` | 30–600, 30'un katı |
| `weekend_minutes` | 30–660, 30'un katı |
| `rest_weekday` | `null` veya 0–6 (pazartesi=0); o gün kapasite 0 |
| `peak_time` | `morning`, `noon`, `evening`, `night` |
| `target_department` | opsiyonel metin (≤100) |
| `target_tyt_net`, `target_ayt_net` | opsiyonel ondalık |
| `onboarding_step` | 1–5 |
| `onboarding_completed_at` | |
| `last_daily_sync` | `DateField`, tembel günlük işlemler için (§6.9) |

**`TopicProgress`** (kullanıcı × konu; `UniqueConstraint(user, topic)`)
| Alan | Not |
|---|---|
| `user`, `topic` | |
| `initial_level` | 0/1/2 (tanışmada girilen) |
| `level` | 0/1/2 (güncel) |
| `state` | `not_started`, `in_progress`, `learned`, `excluded` |
| `remaining_learn_minutes` | |
| `remaining_practice_minutes` | |
| `learned_on` | |
| `boost` | `FloatField(default=1.0)` — deneme zayıflıkları için çarpan (1.0–2.0) |
| `questions_solved`, `questions_correct`, `questions_wrong` | Toplamlar |
| `user_override` | `null`, `force_include`, `force_exclude` (Faz 6) |

**`Plan`** (her yeniden planlamada yeni kayıt; tek bir aktif plan)
| Alan | Not |
|---|---|
| `user` | |
| `created_at` | |
| `reason` | `onboarding`, `phase_change`, `settings_change`, `rescope`, `levels_changed`, `manual` |
| `phase_code` | P6, P4, P3, P2, P1, P0 (§6.4) |
| `days_left` | |
| `budget` | JSON: toplam, yeni konu, pratik, tekrar dakikaları |
| `required_minutes` | Eksik konuların toplam ihtiyacı |
| `coverage_ratio` | Seçilen konuların kapsadığı soru oranı |
| `projection` | JSON: oturum/test bazında tahmini net aralıkları (§6.6) |
| `is_active` | |

**`PlanTopic`**
| Alan | Not |
|---|---|
| `plan`, `topic` | |
| `included` | |
| `sequence` | Çalışılma sırası (dahil olanlar için) |
| `priority`, `gain`, `need_minutes` | Motor çıktıları |
| `reason_code` | `selected`, `already_good`, `no_time`, `big_topic_late`, `user_excluded`, `prerequisite` |

**`Task`**
| Alan | Not |
|---|---|
| `user`, `plan` | |
| `date` | |
| `kind` | §4.4 |
| `topic` | null olabilir (mock) |
| `subject` | null olabilir |
| `session` | yalnızca `mock`/`mock_review` için |
| `title` | Türkçe görev metni |
| `minutes` | |
| `question_target` | `practice`/`review` için |
| `order` | Gün içi sıra |
| `is_peak` | Verimli saatte yapılması önerilen görev |
| `status` | §4.4 |
| `correct`, `wrong`, `blank` | null olabilir |
| `completed_at` | |
| `review_item` | FK null — tekrar görevi ise |

- `Index(fields=["user", "date"])`.

**`ReviewItem`** (aralıklı tekrar kuyruğu)
| Alan | Not |
|---|---|
| `user`, `topic` | |
| `due_date` | |
| `interval_index` | 0, 1, 2 → 1, 7, 30 gün |
| `is_active` | Son tekrar tamamlanınca `False` |

**`MockExam`**
| Alan | Not |
|---|---|
| `user`, `session` | |
| `taken_on` | |
| `task` | FK null — planlanan deneme göreviyse |
| `weak_topics` | `ManyToManyField(Topic, blank=True)` |

**`MockScore`** (`UniqueConstraint(mock, subject)`)
| Alan | Not |
|---|---|
| `mock`, `subject` | |
| `correct`, `wrong`, `blank` | Toplam ≤ dersin soru sayısı |

- `net` özelliği: `correct - wrong / 4`.

**`WeeklyReview`** (`UniqueConstraint(user, week_start)`)
| Alan | Not |
|---|---|
| `user`, `week_start` | Pazartesi |
| `stats` | JSON |
| `message` | Koç mesajı |
| `seen_at` | |

---

## 6. Plan motoru

### 6.1 Genel yapı

```
planner/
├── engine/
│   ├── __init__.py
│   ├── config.py        # tüm ayarlanabilir sabitler
│   ├── types.py         # dataclass'lar (girdi/çıktı)
│   ├── phases.py        # kalan güne göre faz
│   ├── capacity.py      # gün gün kapasite ve bütçe
│   ├── needs.py         # konu ihtiyacı ve kazancı
│   ├── selection.py     # kapsam seçimi
│   ├── projection.py    # tahmini net aralığı
│   ├── scheduler.py     # günlere görev dağıtımı
│   ├── reviews.py       # aralıklı tekrar
│   └── adaptation.py    # tempo, kaçırılanlar, deneme etkisi
├── services.py          # DB <-> motor köprüsü (tek giriş noktaları)
```

- `engine/` içindeki hiçbir dosya Django import etmez. Bugünün tarihi her zaman **parametre** olarak verilir.
- Motor **deterministiktir**: aynı girdi her zaman aynı çıktıyı verir (rastgelelik yok). Eşitlik durumlarında sıralama `subject.order`, sonra `topic.order` ile çözülür.
- `services.py` giriş noktaları:
  - `build_plan(user, today, reason)` → yeni `Plan` + `PlanTopic`'ler, eski planı pasifleştirir, gelecekteki bekleyen görevleri siler, pencereyi yeniden üretir.
  - `ensure_daily_state(user, today)` → tembel günlük işlemler (§6.9).
  - `complete_task(task, correct, wrong, blank)`, `skip_task(task)`, `undo_task(task)`.
  - `record_mock(user, data)`.

### 6.2 Sabitler (`config.py`)

Tüm değerler başlangıç tahminidir; kod içinde başka yerde sihirli sayı kullanılmaz.

```python
BUFFER_RATIO = 0.15            # beklenmedik günler için kapasiteden düşülen pay

# Seviyeye göre ihtiyaç: learn_hours * 60 * NEED_FACTOR
NEED_FACTOR = {0: 1.00, 1: 0.55, 2: 0.20}
# İhtiyacın ne kadarı konu çalışması (learn), gerisi soru pratiği (practice)
LEARN_SHARE = {0: 0.40, 1: 0.20, 2: 0.00}

# Seviyeye göre tahmini başarı oranı (o konudaki soruların yüzde kaçı net olur)
CURRENT_RATE = {0: 0.10, 1: 0.40, 2: 0.75}
TARGET_RATE = 0.80             # konu planlandığı gibi bitirilirse beklenen oran
MAX_RATE = 0.92

BIG_TOPIC_HOURS = 6            # bundan uzun konular "büyük konu"

LEARN_BLOCK_MIN = 45
PRACTICE_BLOCK_MIN = 40
REVIEW_TASK_MIN = 20
MIN_BLOCK_MIN = 20             # bundan kısa artık süre görev yapılmaz
MOCK_ANALYSIS_MIN = 60

MAX_ACTIVE_TOPICS = 3          # aynı anda yürütülen konu sayısı
MAX_SAME_SUBJECT_BLOCKS_PER_DAY = 2

REVIEW_INTERVALS_DAYS = [1, 7, 30]
REVIEW_FAIL_ACCURACY = 0.60    # altında tekrar kısa aralıkla yinelenir
REVIEW_RETRY_DAYS = 3

PRACTICE_WEAK_ACCURACY = 0.50  # altında konuya ek pratik bloğu eklenir
EXTRA_PRACTICE_MIN = 40

BOOST_STEP = 0.25              # denemede zayıf işaretlenen konu başına
BOOST_MAX = 2.0
BOOST_DECAY_PER_WEEK = 0.10

PACE_WARNING = 0.75            # son 14 gün tempo oranı bunun altındaysa uyarı
RESCOPE_TOLERANCE = 1.05       # kalan ihtiyaç > kalan bütçe * bu → kapsam önerisi

PROJECTION_LOW = 0.85          # tahmin aralığı alt çarpanı
PROJECTION_HIGH = 1.05
MOCK_CALIBRATION_BOUNDS = (0.70, 1.30)

WINDOW_DAYS = 7                # detaylı görev üretilen gün sayısı (bugün dahil)
LAST_DAY_MAX_MIN = 60          # sınavdan önceki gün en fazla
FINAL_WEEK_CAPACITY_FACTOR = 0.60
```

### 6.3 Gün gün kapasite (`capacity.py`)

Bugünden (dahil) sınav gününden bir önceki güne kadar her gün için:

1. Ham kapasite = hafta içi ise `weekday_minutes`, cumartesi/pazar ise `weekend_minutes`.
2. `rest_weekday` ise kapasite **0**.
3. Gün P0 fazındaysa (§6.4) kapasite × `FINAL_WEEK_CAPACITY_FACTOR`; sınavdan önceki gün en fazla `LAST_DAY_MAX_MIN`.
4. Net kapasite = ham × (1 − `BUFFER_RATIO`), en yakın 5 dakikaya yuvarlanır.
5. O güne **deneme** planlandıysa (§6.4 deneme takvimi), deneme süresi + analiz süresi düşülür (analiz sığmazsa ertesi güne kayar).
6. Kalan süre, günün fazının paylarına göre **yeni konu / pratik / tekrar** bütçelerine bölünür.

Toplam bütçeler bu günlerin toplamıdır. Bütçe ayrıca **"her konuya açık yeni konu bütçesi"** (P6, P4, P3 günleri) ve **"yalnızca küçük konulara açık yeni konu bütçesi"** (P2 günleri) olarak ikiye ayrılır.

### 6.4 Fazlar ve strateji kuralları (`phases.py`)

Faz, **o günden sınava kalan gün sayısına** göre belirlenir. Böylece 3 ay kala başlayan biri doğrudan P3'ten başlar; 6 aylık planın sıkıştırılmış hali uygulanmaz.

| Kod | Kalan gün | Ad (arayüz) | Yeni konu | Soru pratiği | Tekrar | Deneme sıklığı | Özel kurallar |
|---|---|---|---|---|---|---|---|
| P6 | > 150 | Temel inşa | %65 | %25 | %10 | 14 günde 1 | Önce ön koşulu olmayan, verimli konular |
| P4 | 91–150 | Konu bitirme | %50 | %35 | %15 | 10 günde 1 | Pratik oranı artar |
| P3 | 61–90 | Kapanış | %35 | %45 | %20 | Haftada 1 | Kalan konular kapatılır |
| P2 | 31–60 | Deneme dönemi | %10 | %55 | %35 | Haftada 2 | **Büyük konuya (`learn_hours > BIG_TOPIC_HOURS`) başlanmaz**; yeni konu yalnızca küçük konular |
| P1 | 8–30 | Son ay | %0 | %50 | %50 | Haftada 3 | Yeni konu yok; pratik deneme zayıflıklarına odaklı |
| P0 | 0–7 | Son hafta | %0 | %30 | %70 | En fazla 1, son 3 günde yok | Kapasite %60; son gün ≤ 60 dk hafif tekrar; uyku ve sınav günü hazırlığı kartı |

Yüzdeler, deneme ve analiz süresi düşüldükten sonra kalan günlük süreye uygulanır. Bir gün için tekrar bütçesi kullanılmazsa (vadesi gelmiş tekrar yoksa) pratiğe aktarılır; yeni konu bütçesi kullanılamazsa (başlanabilecek konu yoksa) pratiğe aktarılır.

**Deneme takvimi:**
- Deneme günleri tercihen **cumartesi veya pazar**, aynı haftada ikinci deneme varsa çarşamba. Dinlenme gününe deneme konmaz.
- Oturum sırası alanına göre dönüşümlü: SAY/EA/SÖZ → TYT, AYT, TYT, AYT…; DİL → TYT, YDT…
- P6'da, alanın AYT/YDT konularının %70'inden fazlası seviye 0 ise ilk 30 gün yalnızca TYT denemesi planlanır.
- Deneme süresi oturumun `duration_minutes` değeridir. Günün net kapasitesi deneme süresinden azsa deneme yine o güne konur ve görevde "Bu deneme için o gün biraz daha fazla zaman ayırmaya çalış" notu yer alır; analiz ertesi güne kayar.

**Faz değişimi:** `ensure_daily_state` her gün fazı kontrol eder; aktif planın fazı ile bugünün fazı farklıysa `build_plan(reason="phase_change")` çalışır ve kullanıcıya "Yeni döneme geçtin: Kapanış. Artık daha çok soru çözeceğiz." kartı gösterilir.

### 6.5 Konu ihtiyacı, kazanç ve kapsam seçimi (`needs.py`, `selection.py`)

**Aday konular:** Alanın testlerindeki tüm aktif konular. `state == learned` olanlar aday değildir (tekrar kuyruğundadır). `user_override == force_exclude` olanlar dışarıda kalır (`user_excluded`).

**Her aday konu için:**
- `need = learn_hours × 60 × NEED_FACTOR[level]` (dakika). Konu `in_progress` ise `need = remaining_learn + remaining_practice`.
- `learn_need = need × LEARN_SHARE[level]`, `practice_need = need − learn_need`.
- `gain = avg_questions × (TARGET_RATE − current_rate) × boost`; `current_rate = CURRENT_RATE[level]` (konuda ≥20 soru çözülmüşse ölçülen doğruluk ile ortalaması alınır).
- Seviye 2 konular için `gain` küçük olur; bunlar `already_good` olarak işaretlenir ama pratik bütçesinden küçük tekrar blokları alabilir.

**Paket (bundle):** Bir konu, henüz öğrenilmemiş (seviye < 2 ve `learned` değil) **tüm ön koşullarıyla birlikte** (geçişli) bir paket oluşturur. Paket oranı = paket kazancı ÷ paket ihtiyacı.

**Açgözlü (greedy) seçim:**
1. Bütçeleri al: `new_any`, `new_small`, `practice`. (Tekrar bütçesi seçime katılmaz.)
2. Tüm adaylar için paketleri hesapla, paket oranına göre azalan sırala.
3. En yüksek oranlı paketi dene:
   - Paketteki her konunun `learn_need`'i yeni konu bütçesinden düşülür: büyük konular yalnızca `new_any`'den, küçük konular önce `new_small`'dan sonra `new_any`'den.
   - Paketin `practice_need` toplamı `practice` bütçesinden düşülür.
   - Bütçe yetmiyorsa paket alınmaz; ayrıca P2'de başlayacak gibi görünen büyük bir konu `new_any` yetmediği için alınamıyorsa `big_topic_late` nedeniyle dışarıda kalır.
4. Paket alındıysa konuları `selected` (ön koşul olarak gelenler `prerequisite`) işaretle; kalan adayların paketlerini yeniden hesapla (artık dahil olan ön koşullar paketten düşer).
5. Hiçbir paket sığmayana kadar devam et. Kalanlar `no_time`.
6. `force_include` konular bütçeye bakılmadan en başta dahil edilir.

**Sıralama (`sequence`):** Dahil edilen konular **topolojik sıraya** (ön koşul önce) konur; aynı seviyedekiler arasında önce yüksek oranlı, eşitlikte `subject.order`, `topic.order`.

**Bırakılanlar listesi:** `no_time` ve `big_topic_late` konular raporda "Bunları bırakıyoruz" başlığıyla, her biri için "~X soru için ~Y saat gerekiyor" açıklamasıyla gösterilir.

Vakit fazlasıyla yetiyorsa tüm konular dahil olur; artan bütçe pratiğe ve ek tekrara gider. Raporda "Vaktin yetiyor 🎉, ekstra zamanı soru çözümüne ayırdık" yazar.

### 6.6 Tahmini net aralığı (`projection.py`)

Test bazında (ör. TYT Türkçe, AYT Fen) hesaplanır, oturum toplamı da verilir.

1. **Şu anki tahmin:** Σ `avg_questions × current_rate` (konu bazında).
2. **Sınav günü tahmini:** Dahil edilen konular için `TARGET_RATE` (ölçülen doğruluk varsa `min(MAX_RATE, ölçülen)`), dahil edilmeyenler için `current_rate`.
3. **Tempo düzeltmesi** (plan oluştuktan 14 gün sonra devreye girer): son 14 günün tempo oranı `pace < 1` ise dahil edilen konuların yalnızca `sequence` sırasına göre ilk `pace` kadarlık kısmı (ihtiyaç dakikası üzerinden) tamamlanmış sayılır.
4. **Deneme kalibrasyonu:** Son 2 denemenin ders bazında ortalama neti ÷ o anki ders tahmini = kalibrasyon katsayısı, `MOCK_CALIBRATION_BOUNDS` ile sınırlı. Sınav günü tahmini bu katsayıyla çarpılır.
5. **Aralık:** alt = tahmin × `PROJECTION_LOW`, üst = tahmin × `PROJECTION_HIGH`; üst sınır testin soru sayısını geçemez. Tam sayıya yuvarlanır.
6. **Hedefle karşılaştırma:** Hedef net, aralığın üstündeyse "Hedefin bu planla iddialı" mesajı ve **"Günde 1 saat fazla çalışırsan"** senaryosu (aynı motor, kapasite +60 dk ile) gösterilir. Hedef aralıktaysa "Hedefinle aynı rotadayız", altındaysa "Hedefini aşma ihtimalin var".

Her yerde "tahmini" etiketi ve şu açıklama bulunur: *"Bu bir tahmindir; gerçek sonucun çalışma düzenine, denemelerine ve sınav gününe göre değişir."*

### 6.7 Günlere dağıtım (`scheduler.py`) ve tekrar (`reviews.py`)

Görevler yalnızca **önümüzdeki `WINDOW_DAYS` gün** için ayrıntılı üretilir. Uzun vadeli tablo "Yol haritası" sayfasında konu sırası ve tahmini haftalarla gösterilir.

**Bir gün için doldurma sırası:**

1. **Kapasite** §6.3'e göre hesaplanır; dinlenme günü ise görev yok, "Dinlenme günü 🌿" kartı gösterilir.
2. **Deneme günü** ise `mock` (ve sığarsa `mock_review`) görevi önce eklenir.
3. **Tekrarlar:** Vadesi o gün veya daha önce olan aktif `ReviewItem`'lar, en eski vadeden başlayarak tekrar bütçesine sığdığı kadar `review` görevi olur (`REVIEW_TASK_MIN` dk). Sığmayanlar ertesi güne kalır.
4. **Aktif konular:** En fazla `MAX_ACTIVE_TOPICS` konu aynı anda yürütülür. Boşalan yere `sequence`'teki ilk uygun konu alınır; uygun = ön koşulları `learned` ve **aktif konuların grubundan farklı gruptan** olması tercih edilir (aynı gruptan başka yoksa aynı gruptan alınır).
5. **Yeni konu bütçesi:** Aktif konuların `remaining_learn_minutes`'ından `LEARN_BLOCK_MIN` dakikalık `learn` blokları.
6. **Pratik bütçesi:** Önce öğrenmesi bitmiş aktif konuların `remaining_practice_minutes`'ından `PRACTICE_BLOCK_MIN` dakikalık `practice` blokları; yoksa `boost > 1` olan konular, sonra son öğrenilen konular, sonra seviye 2 konular (küçük pekiştirme blokları).
7. **Karıştırma:** Aynı dersten günde en fazla `MAX_SAME_SUBJECT_BLOCKS_PER_DAY` blok; günde 2'den fazla blok varsa en az 2 farklı ders. Aynı dersin blokları arka arkaya sıralanmaz.
8. **Verimli saat:** `learn` blokları ve zorluk 3 konuların blokları günün başına sıralanır ve `is_peak=True` olur. Arayüzde "☀️ Sabah ilk iş" / "🌙 Akşam verimli saatinde" gibi etiketle gösterilir (kullanıcının `peak_time`'ına göre).
9. `MIN_BLOCK_MIN`'den kısa kalan artık süre görev yapılmaz.

**Pratik görevinde soru sayısı:** `round(minutes / subject.minutes_per_question)`, en yakın 5'e yuvarlanır, en az 10.

**Görev başlıkları (örnek şablonlar):**
- learn: `"{ders} – {konu}: {dk} dk konu çalışması"`
- practice: `"{ders} – {konu}: {n} soru"`
- review: `"Tekrar: {konu} – {n} soru"`
- mock: `"{oturum} Denemesi – {dk} dk, gerçek sınav gibi süre tut"`
- mock_review: `"Deneme analizi: yanlışlarını incele – 60 dk"`

**Konu ilerlemesi:**
- Bir blok `done` olunca ilgili `remaining_*` dakikası düşer; konu `in_progress` olur.
- Her iki kalan sıfırlanınca konu `learned` olur, `learned_on` yazılır ve `ReviewItem(interval_index=0, due_date=bugün + 1)` oluşur.
- **Tekrar sonucu:** Tekrar görevi doğruluk ≥ `REVIEW_FAIL_ACCURACY` (veya sonuç girilmemiş) ise sonraki aralığa geçilir (1 → 7 → 30); son aralık bitince `is_active=False`. Doğruluk düşükse aynı aralık `REVIEW_RETRY_DAYS` gün sonra tekrarlanır.
- Vadesi sınav gününden sonraya düşen tekrar oluşturulmaz.

### 6.8 Uyarlama (`adaptation.py`)

**Kaçırılan görevler:** Tarihi geçmiş ve `pending` kalan görevler `missed` olur. `learn`/`practice` görevlerinin dakikaları konunun `remaining_*` alanlarına geri eklenir (zaten oradan düşülmemişlerdi; yani kuyrukta kalırlar). Tekrarlar vadesi geçmiş olarak kuyrukta kalır. Kaçırılan deneme silinmez, `missed` olur; bir sonraki deneme takvime göre gelir. Sonra pencere yeniden üretilir. **Bugüne yığma yapılmaz;** bugünün kapasitesi aşılmaz. Kullanıcıya bir kez gösterilen kart: *"Dün çalışamadın, sorun değil. Görevlerini önümüzdeki günlere yaydım."*

**Atlanan görev:** `missed` ile aynı mantık, kullanıcının kendi isteği.

**Düşük pratik başarısı:** Bir `practice` görevinde doğruluk < `PRACTICE_WEAK_ACCURACY` ise konuya `EXTRA_PRACTICE_MIN` dakika eklenir.

**Deneme etkisi:** Denemede zayıf işaretlenen her konunun `boost`'u `BOOST_STEP` artar (en fazla `BOOST_MAX`); konu `learned` ise tekrar kuyruğuna `due_date=yarın` ile eklenir; `excluded` ve küçük bir konuysa "Bu konuyu plana eklemek ister misin?" önerisi çıkar. Boost'lar her hafta `BOOST_DECAY_PER_WEEK` azalır (en az 1.0).

**Tempo ve geride kalma:**
- `pace` = son 14 günde `done` görevlerin dakikası ÷ aynı dönemde planlanan (`done + missed + skipped + pending`) görevlerin dakikası.
- `pace < PACE_WARNING` ise `/bugun/` üstünde nazik bir uyarı kartı.
- Kalan dahil konuların ihtiyacı > kalan bütçe × `pace` × `RESCOPE_TOLERANCE` ise **kapsam önerisi**: motor `build_plan`'ı kuru çalıştırır (dry-run, kayıt yok), çıkarılması önerilen konuları listeler. Kullanıcı **"Planı güncelle"** derse `build_plan(reason="rescope")`; "Şimdilik kalsın" derse öneri 7 gün gösterilmez. **Onaysız konu çıkarılmaz.**

### 6.9 Tembel günlük işlemler (`ensure_daily_state`)

Giriş yapmış ve tanışmasını bitirmiş kullanıcı uygulama sayfalarından birini açtığında (bir middleware veya `/bugun/` view'ı başında) çalışır; `last_daily_sync == bugün` ise hiçbir şey yapmaz.

Sıra:
1. Dünden ve öncesinden kalan `pending` görevleri `missed` yap (§6.8).
2. Boost'ları haftalık sönümle (gerekirse).
3. Faz değişmişse `build_plan(reason="phase_change")`.
4. Yeni haftaya girildiyse geçen haftanın `WeeklyReview`'ını oluştur.
5. Pencereyi tamamla: bugünden itibaren `WINDOW_DAYS` gün içinde görevi olmayan günler için görev üret. **Bugünün görevlerinden en az biri `done` ise bugün yeniden üretilmez.** Geleceğe ait `pending` görevler, plan yeniden oluşturulduğunda silinip yeniden üretilir.
6. `last_daily_sync = bugün`.

Tüm işlem tek bir `transaction.atomic()` içinde. Aynı anda iki istek gelirse çift üretimi önlemek için `StudentProfile` satırı `select_for_update()` ile kilitlenir.

### 6.10 Motor testleri (zorunlu senaryolar)

`planner/tests/test_engine.py` içinde, sabit bir test kataloğuyla (gerçek JSON değil, küçük yapay veri) en az şunlar:

1. **Bol vakit:** Tüm konular dahil, `coverage_ratio = 1`, rapor "vaktin yetiyor" der.
2. **6 ay, sıfırdan, günde 3 saat:** Bazı konular `no_time`; dahil hiçbir konu, öğrenilmemiş ön koşulu dışarıdayken dahil değildir.
3. **3 ay kala başlayan:** Faz P3; plan P6 kurallarıyla değil P3 paylarıyla bütçelenir.
4. **45 gün kala, büyük ve seviye 0 konu:** P2 günlerinde `learn` bloğu üretilmez; konu `big_topic_late` olur.
5. **20 gün kala:** Hiç `learn` görevi üretilmez; haftada 3 deneme.
6. **Son hafta:** Kapasite %60; sınavdan önceki gün ≤ 60 dk; son 3 günde deneme yok.
7. **Dinlenme günü:** O gün görev yok.
8. **Karıştırma:** Aynı dersten günde 2'den fazla blok yok; 3+ bloklu günlerde en az 2 farklı ders.
9. **Kaçırılan gün:** Görevler kuyruğa döner, bugünün toplam dakikası kapasiteyi aşmaz.
10. **Tekrar aralıkları:** Öğrenilen konu için tekrarlar 1, 7, 30 gün sonra; başarısız tekrar 3 gün sonra yinelenir; sınav sonrasına tekrar konmaz.
11. **Determinizm:** Aynı girdiyle iki çalıştırma birebir aynı çıktı.
12. **Tahmin:** Aralık üst sınırı test soru sayısını aşmaz; kalibrasyon sınırlar içinde.
13. **Kapsam önerisi:** Düşük tempoda dry-run öneri üretir, veritabanını değiştirmez.

---

## 7. Tanışma (onboarding)

Adım adım, her adım ayrı sayfa (`/baslangic/1/` … `/baslangic/5/`), üstte ilerleme çubuğu, "Geri" ve "Devam" butonları. Her adım kaydedilir; kullanıcı yarıda bırakırsa kaldığı yerden devam eder.

### 7.1 Adım 1 — Sınav ve alan
- Sınav: "YKS 2027" (tek seçenek; tarih ve "tahmini" rozeti görünür). KPSS vb. "Yakında" olarak pasif gösterilir.
- Alan: SAY / EA / SÖZ / DİL kartları, her kartta hangi testleri içerdiği kısa yazılı.

### 7.2 Adım 2 — Günlük vakit
- Hafta içi ve hafta sonu için ayrı **kaydırıcı** (30 dk adım; hafta içi 0,5–10 saat, hafta sonu 0,5–11 saat), yanında büyük yazıyla "Günde 4 saat 30 dakika".
- 9 saatin üstünde nazik uyarı: *"Bu çok yoğun bir tempo. Uzun vadede yorulmamak için biraz daha az planlayıp dinlenmeye de yer açabilirsin."*
- Sınava kadar toplam saat anında gösterilir: *"Sınava kadar yaklaşık 812 saatin var."*

### 7.3 Adım 3 — Verimli saat ve dinlenme günü
- Verimli saat: Sabah / Öğle / Akşam / Gece (ikonlu kartlar).
- Dinlenme günü: Yok / Pazartesi … Pazar. Varsayılan: Pazar değil, **"Yok"**; altında öneri: *"Haftada bir gün dinlenmek, uzun vadede daha çok net getirir."*

### 7.4 Adım 4 — Konu seviyeleri
- Alanın dersleri akordeon listesi; her dersin başlığında "12 / 30 konu işaretlendi" sayacı.
- Her konu satırında üç durumlu segment kontrol: **Bilmiyorum / Biraz / İyiyim** (renkli, büyük dokunma alanı).
- Ders başlığında hızlı butonlar: "Hepsini: Bilmiyorum / Biraz / İyiyim".
- Ders ders kaydedilir (JS ile otomatik; JS yoksa ders başına "Kaydet" butonu).
- Varsayılan: tüm konular "Bilmiyorum". Kullanıcı hiçbir şey değiştirmeden devam edebilir.

### 7.5 Adım 5 — Deneme netleri ve hedef (opsiyonel)
- "Daha önce deneme çözdün mü?" → evetse son TYT (ve alanına göre AYT/YDT) denemesinin **ders ders** doğru/yanlış/boş sayıları. Bu bir `MockExam` olarak kaydedilir.
- Hedef: hedef bölüm (serbest metin), hedef TYT neti, hedef AYT/YDT neti. Hepsi opsiyonel.
- "Planımı oluştur" → `build_plan(reason="onboarding")` → `onboarding_completed_at` yazılır → **Gerçekçilik raporu**.

### 7.6 Gerçekçilik raporu (`/plan/rapor/`)

Tanışma bitince ve her yeniden planlamada erişilebilir. Bölümler:
1. **Zaman:** "Sınava 253 gün var. Toplam yaklaşık 812 saatin var; denemeler, tekrarlar ve beklenmedik günler için pay ayırınca konu ve soru çalışmasına ~560 saat kalıyor."
2. **İhtiyaç:** "Eksik konularını tamamlamak için ~690 saat gerekiyor."
3. **Karar:** Vakit yetiyorsa kutlama; yetmiyorsa "En fazla neti getirecek konuları seçtik."
4. **Tahmini net aralığı:** Test test ve oturum toplamı, "tahmini" etiketiyle.
5. **Hedef karşılaştırması** ve "günde 1 saat fazla" senaryosu (§6.6).
6. **Odaklanacağın ilk konular:** Sıradaki ilk 8 konu.
7. **Bırakılanlar:** "~2 soru için ~40 saat istiyor" açıklamalarıyla.
8. **Şu anki dönemin:** Faz adı ve bu dönemde neye odaklanılacağı (§6.4 tablosundan sade dille).
9. Büyük buton: **"Hadi başlayalım → Bugün"**.

---

## 8. Sayfalar ve URL'ler

| URL | Sayfa | Erişim | Faz |
|---|---|---|---|
| `/` | Karşılama (girişliyse `/bugun/`'e yönlendirir) | Herkes | 1 |
| `/kayit/`, `/giris/` | Kayıt, giriş | Misafir | 1 |
| `/cikis/` | Çıkış (POST) | Üye | 1 |
| `/baslangic/<1-5>/` | Tanışma adımları | Üye | 3 |
| `/plan/rapor/` | Gerçekçilik raporu | Üye | 3 |
| `/plan/` | Yol haritası: dönemler, konu sırası, tahmini haftalar, bırakılanlar | Üye | 3 |
| `/bugun/` | Günün görevleri (ana ekran) | Üye | 4 |
| `/hafta/` | Önümüzdeki 7 günün görevleri | Üye | 4 |
| `/gorev/<id>/tamamla/` | POST: tamamla (+ D/Y/B) | Sahibi | 4 |
| `/gorev/<id>/atla/` | POST | Sahibi | 4 |
| `/gorev/<id>/geri-al/` | POST | Sahibi | 4 |
| `/deneme/` | Deneme listesi | Üye | 5 |
| `/deneme/ekle/` | Deneme sonucu girme (+ zayıf konular adımı) | Üye | 5 |
| `/deneme/<id>/` | Deneme detayı | Sahibi | 5 |
| `/plan/kapsam-onerisi/` | Kapsam daraltma önerisi ve onay (POST) | Üye | 5 |
| `/degerlendirme/` | Haftalık değerlendirmeler | Üye | 5 |
| `/ilerleme/` | İlerleme paneli | Üye | 6 |
| `/ayarlar/` | Vakit, dinlenme günü, verimli saat, alan, konu seviyeleri, konu dahil/çıkar, hesap silme | Üye | 6 |
| `/yonetim/` | Django admin | Superuser | 2 |

### 8.1 Görev uç noktaları (JSON + form)

`POST /gorev/<id>/tamamla/` — gövde: `correct`, `wrong`, `blank` (opsiyonel). CSRF korumalı.
- `Accept: application/json` varsa JSON döner; yoksa işlem yapılır ve `/bugun/`'e yönlendirilir.
- Başarılı yanıt:
```json
{
  "ok": true,
  "task": {"id": 812, "status": "done"},
  "day": {"done_minutes": 135, "planned_minutes": 210, "done_count": 3, "total_count": 5},
  "streak": 6,
  "message": "Harika, 3/5 tamam! 💪"
}
```
- Hatalar: `{"ok": false, "error": "<Türkçe mesaj>"}` — `400` geçersiz sayı, `404` görev yok veya başkasına ait, `409` görev bugünün ya da geçmişin değil (gelecekteki görev tamamlanamaz).

`/atla/` ve `/geri-al/` aynı biçimde. Geri alma yalnızca aynı gün içinde.

### 8.2 Ortak düzen
- **Mobil:** Altta sabit **sekme çubuğu**: Bugün · Plan · Deneme · İlerleme · Profil (ikon + kısa etiket).
- **Masaüstü:** Solda dar kenar menü, içerik ortada en fazla 720px.
- Üstte: logo + **"Sınava 253 gün"** çipi (+ tahminiyse küçük "tahmini" rozeti).
- Django `messages` ile toast bildirimleri.
- Özel `404.html` ve `500.html`.

### 8.3 `/bugun/` ekranı
- **Selamlama:** "Günaydın Elif ☀️" (saate göre).
- **Günün özeti kartı:** SVG ilerleme halkası (yapılan / planlanan dakika), görev sayısı, seri 🔥.
- Gerekirse üstte bilgi kartları (en fazla 2 tanesi aynı anda): faz değişimi, kaçırılan gün, tempo uyarısı, kapsam önerisi, haftalık değerlendirme, sınav tarihi tahmini uyarısı.
- **Görev listesi:** Her görev bir kart: ders renginde sol şerit, başlık, süre, "☀️ verimli saatinde" etiketi, büyük yuvarlak onay kutusu. Pratik/tekrar görevi işaretlenince kartın altında küçük D/Y/B giriş alanı açılır ("Kaydet" veya "Geç").
- Tüm görevler bitince kutlama: hafif konfeti animasyonu + "Bugünü tamamladın! Yarın görüşürüz 👋".
- Dinlenme günü: "Bugün dinlenme günün 🌿 Kendine iyi bak."
- Son hafta: "Sınav günü hazırlık" kartı (kimlik, sınava giriş belgesi, uyku düzeni, sınav sabahı kahvaltı gibi genel hatırlatmalar).

### 8.4 `/plan/` — yol haritası
- Dönem çizelgesi (yatay zaman çizgisi): P6 → … → P0, "Şu an buradasın" işareti.
- Ders ders dahil konular, sırasıyla ve tahmini başlangıç haftasıyla (`sequence` ve bütçeden hesaplanan kaba tahmin).
- Bırakılanlar listesi ve "Bu konuyu yine de ekle" butonu (Faz 6).
- "Raporu gör" linki.

### 8.5 `/ilerleme/`
§4.8'deki göstergeler. Grafikler sunucuda hesaplanan veriden **elle SVG** olarak çizilir (JS gerekmez); dokunulduğunda değer gösteren küçük bir JS iyileştirmesi opsiyonel.

### 8.6 Koç mesajları (kural tabanlı)

Mesajlar `planner/messages.py` içinde şablonlar olarak durur; rastgelelik yerine tarih + kullanıcı ID'sine göre deterministik seçilir (aynı gün aynı mesaj).

Haftalık değerlendirme mesajı, plan tamamlama yüzdesine göre:
- **≥ %90:** "Muhteşem bir hafta! Planının %{p}'ini yaptın. Bu tempoyla rotandasın. 🚀"
- **%70–89:** "Güzel bir hafta geçirdin, planının %{p}'ini yaptın. Küçük bir adım daha, tam yoldayız. 💪"
- **%50–69:** "Bu hafta biraz yoğundu galiba, planının %{p}'ini yapabildin. Sorun değil; gelecek hafta için planı biraz hafiflettim."
- **< %50:** "Zor bir hafta olmuş. Kendine yüklenme; her gün küçük bir adım bile çok şey değiştirir. Hadi bu hafta birlikte yeniden başlayalım. 🌱"

Ek cümleler: en çok gelişen ders ("Paragrafta doğruluğun %8 arttı 👏"), gelecek haftanın odak dersleri (boost'u en yüksek 2–3 ders).

**Ton kuralları:** "Sen" dili, kısa cümleler, suçlama yok ("başaramadın" yerine "yapamadın, sorun değil"), abartılı vaatler yok ("kesin kazanırsın" yok).

---

## 9. Tasarım sistemi

**Hedef his:** Sakin ama enerjik. Uzun saatler bakılacak bir ekran olduğu için göz yormayan; küçük başarıları kutlayan, motive eden.

### 9.1 Renkler

Açık tema varsayılan; **koyu tema** sistem tercihine göre otomatik (`prefers-color-scheme`), ayarlardan elle de seçilebilir (gece çalışan öğrenciler için önemli).

```css
:root {
  --bg: #F6F5FB;
  --surface: #FFFFFF;
  --surface-2: #EFEDF8;
  --border: #E3E0F0;
  --text: #1C1B2E;
  --text-muted: #6B6889;
  --primary: #5B5BD6;        /* indigo – ana renk */
  --primary-soft: #E8E8FB;
  --accent: #FF7A59;         /* mercan – vurgular, kutlama */
  --success: #22A97A;
  --warning: #E89B16;
  --danger: #E5484D;
  --grad-hero: linear-gradient(135deg, #5B5BD6 0%, #8E6CEF 55%, #FF7A59 100%);
  --radius-lg: 20px;
  --radius-md: 14px;
  --radius-pill: 999px;
  --shadow: 0 6px 24px rgba(40, 32, 90, 0.08);
}
[data-theme="dark"] {
  --bg: #121220;
  --surface: #1B1B2D;
  --surface-2: #24243A;
  --border: #2F2F48;
  --text: #F2F1FA;
  --text-muted: #A6A3C3;
  --primary: #8B8BF5;
  --primary-soft: #2A2A4A;
  --shadow: 0 6px 24px rgba(0, 0, 0, 0.35);
}
```

**Ders renkleri** (`Subject.color`, iki temada da okunur ton): Türkçe/Edebiyat mercan `#FF7A59`, Matematik indigo `#5B5BD6`, Geometri mor `#8E6CEF`, Fizik camgöbeği `#14A3C7`, Kimya yeşil `#22A97A`, Biyoloji lime `#7CB518`, Tarih amber `#E89B16`, Coğrafya kahve-turuncu `#C97B3A`, Felsefe grubu pembe `#D6589F`, Din Kültürü gri-mavi `#5C7A99`, İngilizce gök mavisi `#3B82F6`.

### 9.2 Arka plan
- Düz `--bg` zemin; sayfanın üst kısmında çok hafif, bulanık bir `--grad-hero` lekesi (opaklık ~0.12) ile canlılık. Gürültülü desen yok.
- Karşılama sayfasında hero alanı tam `--grad-hero`.

### 9.3 Tipografi
- Font: **Manrope** (Google Fonts, Türkçe karakter desteği), ağırlıklar 400 / 600 / 800.
- Yedek: `system-ui, -apple-system, "Segoe UI", sans-serif`.
- Başlıklar 800, gövde 16px / 1.55 satır yüksekliği, ikincil metin `--text-muted`.
- Rakamlarda `font-variant-numeric: tabular-nums` (sayaçlar ve netler zıplamasın).

### 9.4 Bileşenler
- **Kart:** `--surface`, `--radius-lg`, `--shadow`, 16–20px iç boşluk.
- **Birincil buton:** hap şeklinde, `--primary`, beyaz yazı, en az 48px yükseklik; hover/aktifte hafif koyulaşma.
- **Görev kartı:** ders renginde 4px sol şerit; 28px yuvarlak onay kutusu; işaretlenince kutu `--success` dolar, başlık soluklaşır, kısa "pop" animasyonu.
- **Segment kontrol** (Bilmiyorum / Biraz / İyiyim): seçili segment sırasıyla `--danger`, `--warning`, `--success` tonunun yumuşak hali.
- **İlerleme halkası:** SVG, `stroke-dasharray` ile, `--primary` → `--accent` gradyan.
- **Bilgi kartları:** ikon + kısa metin + tek eylem; renk türe göre (bilgi `--primary-soft`, uyarı `--warning` tonu).
- **Çip:** "Sınava 253 gün", "tahmini" rozeti.
- **Toast:** mobilde altta (sekme çubuğunun üstünde), masaüstünde sağ üstte; 4 sn.
- **Boş durumlar:** büyük emoji + kısa, sıcak metin + tek eylem butonu.
- **Logo:** Basit, özgün bir pusula/rota ikonu (SVG) + "rotam" yazısı (küçük harf, 800 ağırlık).

### 9.5 Düzen ve erişilebilirlik
- **Mobil öncelikli**; 360px genişlikte kusursuz.
- Dokunma hedefleri ≥ 44×44px.
- Kontrast WCAG AA (iki temada da).
- Renk tek bilgi taşıyıcısı değil (segment kontrolde metin, durumlarda ikon da var).
- `:focus-visible` halkası belirgin.
- `prefers-reduced-motion` ile tüm animasyonlar kapanır.
- Formlarda her alanın görünür etiketi, hata mesajı alanın altında.

### 9.6 Ses tonu
Samimi, destekleyici, kısa; "sen" dili. Örnekler:
- Karşılama başlığı: **"Sınavına giden en kısa rota."** Alt metin: "Kalan süreni, seviyeni ve vaktini söyle; her gün ne çalışacağını biz söyleyelim."
- Bugün boşsa: "Bugün için görev yok. Biraz dinlen, yarın devam! 🌿"
- Görev bitti: "Bir tane daha bitti ✅"
- Tanışma sonu: "Rotanı çizdim. Hazırsan başlayalım!"

---

## 10. Proje yapısı

```
rotam/
├── CLAUDE.md
├── README.md
├── manage.py
├── requirements.txt
├── .python-version
├── .env.example
├── .gitignore
├── vercel.json                  # yalnızca gerekirse (§12)
├── data/
│   ├── yks_2027.json
│   ├── KAYNAKLAR.md
│   └── DOGRULANACAKLAR.md
├── config/
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── accounts/                    # User, kayıt, giriş
├── catalog/                     # Exam, Session, Test, Subject, Topic, Track
│   ├── management/commands/seed_exam_data.py
│   ├── management/commands/check_exam_data.py
│   └── validation.py
├── planner/
│   ├── engine/                  # saf Python motor (§6.1)
│   ├── services.py
│   ├── messages.py              # koç mesajı şablonları
│   ├── models.py
│   ├── forms.py
│   ├── views/                   # onboarding.py, today.py, plan.py, mocks.py, progress.py, settings.py
│   ├── middleware.py            # tanışma yönlendirmesi + ensure_daily_state
│   ├── urls.py
│   ├── admin.py
│   └── tests/
│       ├── test_engine.py
│       ├── test_services.py
│       └── test_views.py
├── core/                        # karşılama, RLS migration, ortak şablon etiketleri
├── templates/
│   ├── base.html
│   ├── partials/                # task_card.html, info_card.html, progress_ring.html, tabbar.html, messages.html
│   ├── accounts/
│   ├── onboarding/
│   ├── planner/
│   ├── 404.html
│   └── 500.html
└── static/
    ├── css/main.css
    ├── js/app.js                # CSRF yardımcısı, toast, görev işaretleme, tema
    ├── js/onboarding.js         # kaydırıcılar, segment kontroller, otomatik kayıt
    └── img/logo.svg
```

---

## 11. Yapılandırma

### 11.1 Ortam değişkenleri (`.env.example`)

```
DJANGO_SECRET_KEY=change-me
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://localhost:8000
# Boş bırakılırsa yerelde SQLite kullanılır
DATABASE_URL=
```

Prod (Vercel):
```
DEBUG=False
ALLOWED_HOSTS=.vercel.app
CSRF_TRUSTED_ORIGINS=https://<proje-adi>.vercel.app
DATABASE_URL=<Supabase transaction pooler bağlantı dizesi>
DJANGO_SECRET_KEY=<uzun rastgele değer>
```

### 11.2 `settings.py` gereklilikleri

- `python-dotenv` ile `.env`; tüm ortama bağlı değerler `os.environ`'dan.
- `DATABASES` → `dj_database_url.parse(DATABASE_URL)`; yoksa SQLite.
- Postgres (Supabase transaction pooler) için: `CONN_MAX_AGE = 0`, `DISABLE_SERVER_SIDE_CURSORS = True`, `OPTIONS = {"prepare_threshold": None}`. **Yazmadan önce Supabase dokümanından güncelliğini doğrula.**
- `LANGUAGE_CODE = "tr"`, `TIME_ZONE = "Europe/Istanbul"`, `USE_TZ = True`. "Bugün" her yerde `timezone.localdate()`.
- `AUTH_USER_MODEL = "accounts.User"`, `LOGIN_URL = "/giris/"`, `LOGIN_REDIRECT_URL = "/bugun/"`, `LOGOUT_REDIRECT_URL = "/"`.
- `STATIC_URL = "/static/"`, `STATICFILES_DIRS = [BASE_DIR / "static"]`, `STATIC_ROOT = BASE_DIR / "staticfiles"`.
- `TEMPLATES.DIRS = [BASE_DIR / "templates"]`.
- `DEBUG=False` iken: `SECURE_PROXY_SSL_HEADER`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_CONTENT_TYPE_NOSNIFF`, `X_FRAME_OPTIONS = "DENY"`, `SECURE_REFERRER_POLICY = "same-origin"`.
- `SESSION_COOKIE_AGE` 30 gün (öğrenci her gün tekrar giriş yapmak zorunda kalmasın).

### 11.3 Supabase güvenlik notu (önemli)

Django tabloları Supabase'in `public` şemasında oluşur ve Supabase bu şemayı otomatik REST API ile dışarı açabilir; RLS kapalıysa kullanıcı ve çalışma verileri `anon` anahtarla okunabilir hale gelebilir.
- Tüm `public` tablolarında **RLS'yi etkinleştir** (politika eklemeden). `core` uygulamasında, `public` şemasındaki tüm tabloları döngüyle kapsayan bir `RunSQL` migration'ı yaz; yeni tablo ekleyen her fazda bu işlemi tekrarlayan yeni bir migration ekle.
- Django `postgres` rolüyle bağlandığından RLS'den etkilenmemeli; **RLS'yi açtıktan sonra uygulamanın okuma/yazma yapabildiğini mutlaka doğrula.**
- Supabase Security Advisor'da "RLS disabled" uyarısı kalmamalı.
- Supabase `anon`/`service_role` anahtarları bu projede kullanılmaz ve hiçbir yere yazılmaz.

---

## 12. Deployment (Vercel)

- Vercel `manage.py`'yi görerek projeyi Django olarak algılar. **Önce `vercel.json` olmadan dene**; algılama başarısız olursa minimum yapılandırma ekle (önce dokümana bak).
- Python sürümü `.python-version`'dan.
- **Migration'lar ve veri yükleme Vercel build'inde çalıştırılmaz.** Deploy'dan önce yerelden Supabase'e karşı:
  ```
  DATABASE_URL=<session pooler bağlantı dizesi> python manage.py migrate
  DATABASE_URL=<session pooler bağlantı dizesi> python manage.py seed_exam_data data/yks_2027.json
  ```
  (Uygulama çalışırken transaction pooler, migration için session pooler.)
- Ortam değişkenleri §11.1'deki prod değerleriyle.
- Cron gerekmez (§2.2).

**Güncel dokümanlar (yapılandırma yazmadan önce oku):**
- Vercel Django: https://vercel.com/docs/frameworks/full-stack/django
- Vercel Python runtime: https://vercel.com/docs/functions/runtimes/python
- Supabase bağlantı yöntemleri: https://supabase.com/docs/guides/database/connecting-to-postgres

---

## 13. Fazlar

Her faz kendi içinde çalışır, test edilebilir ve deploy edilebilir bir durumda biter.

### Faz 0 — İskelet ve ilk deploy

- [x] Git deposu, `.gitignore` (`.env`, `__pycache__/`, `staticfiles/`, `db.sqlite3`, `.venv/`, `.vercel/`)
- [x] `requirements.txt`, `.python-version`, `.env.example`, `README.md`
- [x] `config` projesi; `accounts`, `catalog`, `planner`, `core` uygulamaları
- [x] **Özel `User` modeli** (§5.1) ve ilk migration — başka migration'dan önce
- [x] `settings.py` §11.2'ye göre
- [x] Geçici anasayfa ("rotam yakında") `static/css/main.css` yükleyerek
- [x] RLS migration'ı (§11.3)
- [ ] Supabase'e migration, Vercel'e ilk deploy

**Kabul kriterleri:** Yerelde `runserver` çalışıyor; Vercel URL'sinde sayfa CSS'iyle açılıyor; `/admin/` stilleriyle açılıyor; Supabase'de tablolar var ve RLS açık; Django hâlâ okuyup yazabiliyor.

### Faz 1 — Tasarım sistemi, karşılama ve üyelik

- [x] `main.css`: tüm token'lar, açık/koyu tema, temel bileşenler (§9)
- [x] `base.html`: üst bar (geri sayım çipi için yer), mobil sekme çubuğu, masaüstü kenar menü, toast alanı
- [x] Logo SVG'si (özgün pusula/rota ikonu)
- [x] Karşılama sayfası (`/`): hero, "nasıl çalışır" 3 adım, "Hemen başla"
- [x] Kayıt (ad, e-posta, parola ×2), giriş (`?next=`), çıkış (POST); Türkçe hatalar
- [x] Girişli kullanıcı `/`, `/kayit/`, `/giris/`'e giderse `/bugun/`'e (bu fazda geçici bir "yakında" sayfası) yönlendirilir
- [x] `app.js`: CSRF yardımcı fonksiyonu, toast, tema değiştirici
- [x] Testler: e-posta büyük/küçük harf duyarsız benzersizlik, kayıt → otomatik giriş, giriş/çıkış, `next` yönlendirmesi

**Kabul kriterleri:** Kayıt/giriş/çıkış çalışıyor; tasarım 360px mobilde ve masaüstünde §9'a uygun; koyu tema çalışıyor.

### Faz 2 — Sınav kataloğu ve konu veritabanı

- [x] `catalog` modelleri (§5.2) + migration'lar + RLS migration güncellemesi
- [x] Django admin: tüm modeller; `Topic` için ders filtresi, arama, `list_editable` ile `avg_questions`, `learn_hours`, `difficulty`, `is_estimated`; `prerequisites` için `filter_horizontal`; ders içinde konu sayısı ve toplam soru göstergesi
- [x] `catalog/validation.py` ve `check_exam_data` komutu (§5.2 kuralları)
- [x] `seed_exam_data` komutu (§5.5), tekrar çalıştırılabilir
- [x] `data/yks_2027.json`: §5.3'teki oturumlar, testler, dersler, alanlar ve **tüm derslerin konu listeleri** (§5.4 kurallarıyla)
- [x] `data/KAYNAKLAR.md` ve `data/DOGRULANACAKLAR.md` (ders ders, hangi sayıların tahmini olduğu)
- [x] Admin URL'si `/yonetim/`
- [x] Testler: doğrulama kuralları (toplam uyuşmazlığı, döngülü ön koşul, kendi kendine ön koşul), seed'in iki kez çalıştırılınca kopya oluşturmaması

**Kabul kriterleri:** `check_exam_data` hatasız (uyarılar raporlanmış); admin'den konu verisi rahatça düzenlenebiliyor; DOĞRULANACAKLAR listesi kullanıcıya özetlendi.

### Faz 3 — Tanışma, plan motoru çekirdeği ve gerçekçilik raporu

- [x] `planner` modelleri: `StudentProfile`, `TopicProgress`, `Plan`, `PlanTopic` (+ ileride kullanılacak `MockExam`, `MockScore` bu fazda oluşturulabilir çünkü tanışmada deneme girilir) + RLS migration güncellemesi
- [x] Motor: `config.py`, `types.py`, `phases.py`, `capacity.py`, `needs.py`, `selection.py`, `projection.py` (§6.2–6.6)
- [x] `services.build_plan` (görev üretimi hariç; görevler Faz 4'te)
- [x] Tanışma middleware'i: tamamlanmamışsa kaldığı adıma yönlendir
- [x] Tanışma adımları 1–5 (§7.1–7.5), `onboarding.js` (kaydırıcılar, segment kontrol, ders ders otomatik kayıt)
- [x] Gerçekçilik raporu (`/plan/rapor/`) (§7.6) ve yol haritası (`/plan/`) (§8.4, "ekle" butonu hariç)
- [x] Üst barda geri sayım çipi
- [x] Testler: §6.10'daki 1, 2, 3, 4, 11, 12 numaralı senaryolar; tanışma akışı; tanışmayı bitirmeden `/plan/`'a giden kullanıcının yönlendirilmesi; başka kullanıcının planına erişilememesi

**Kabul kriterleri:** Yeni bir kullanıcı kayıt olup tanışmayı bitirince anlaşılır, dürüst bir rapor görüyor; ön koşul kuralları ve P2 büyük konu kuralı testlerle doğrulanmış.

### Faz 4 — Günlük görevler ve tekrar sistemi

- [ ] `Task`, `ReviewItem` modelleri + RLS migration güncellemesi
- [ ] Motor: `scheduler.py`, `reviews.py`, `adaptation.py`'nin kaçırılan/atlanan görev kısmı (§6.7, §6.8)
- [ ] `services.ensure_daily_state` (§6.9; haftalık değerlendirme ve boost kısmı Faz 5'te) ve `build_plan`'ın pencere üretimi
- [ ] `/bugun/` (§8.3) ve `/hafta/`
- [ ] Görev uç noktaları (§8.1): tamamla, atla, geri al — JSON ve form yedeği
- [ ] `app.js`: görevi işaretleme, D/Y/B alanı, ilerleme halkasının anlık güncellenmesi, gün bitti kutlaması
- [ ] Çalışma serisi hesabı (en az bir görevi `done` olan gün; dinlenme günü seriyi bozmaz)
- [ ] Testler: §6.10'daki 5, 6, 7, 8, 9, 10 numaralı senaryolar; aynı günde iki kez `ensure_daily_state`'in çift görev üretmemesi; başkasının görevine 404; gelecekteki görevin tamamlanamaması

**Kabul kriterleri:** Kullanıcı her gün mantıklı, karışık, kapasitesini aşmayan görevler görüyor; kaçırılan gün yığılmadan yayılıyor; tekrarlar 1/7/30 günde geliyor.

### Faz 5 — Denemeler, uyarlama ve haftalık değerlendirme

- [ ] `MockExam`/`MockScore` sayfaları: liste, ekleme (ders ders D/Y/B + zayıf konular adımı), detay
- [ ] Planlanan deneme göreviyle otomatik eşleştirme
- [ ] Motor: deneme etkisi (boost, tekrar kuyruğu), boost sönümü, düşük pratik başarısı, tempo ve kapsam önerisi dry-run'ı (§6.8)
- [ ] `/plan/kapsam-onerisi/` onay akışı
- [ ] `WeeklyReview` modeli + RLS; `ensure_daily_state`'e haftalık değerlendirme adımı; `planner/messages.py` (§8.6); `/degerlendirme/`
- [ ] `/bugun/` bilgi kartları (en fazla 2 aynı anda, öncelik sırası: kapsam önerisi > faz değişimi > haftalık değerlendirme > kaçırılan gün > tempo uyarısı > tahmini tarih)
- [ ] Projeksiyona deneme kalibrasyonu ve tempo düzeltmesi
- [ ] Testler: §6.10'daki 13 numaralı senaryo; net hesabı; toplamın soru sayısını aşmaması; boost sınırları; haftalık değerlendirmenin haftada bir kez oluşması

**Kabul kriterleri:** Deneme girildiğinde zayıf konular sonraki günlerde görünür biçimde öne geliyor; geride kalan kullanıcıya onaylı kapsam önerisi sunuluyor; pazartesi haftalık değerlendirme kartı çıkıyor.

### Faz 6 — İlerleme paneli, ayarlar ve sağlamlaştırma

- [ ] `/ilerleme/` (§4.8, §8.5): konu haritası, SVG net grafiği, SVG haftalık süre grafiği, seri, tahmini net
- [ ] `/ayarlar/`: vakit, dinlenme günü, verimli saat, tema, alan değişikliği (uyarıyla), konu seviyelerini yeniden düzenleme, konu "yine de ekle / çıkar" (`user_override`); değişiklik → `build_plan(reason="settings_change" | "levels_changed")`
- [ ] Hesap ve tüm verileri silme (parola onayıyla)
- [ ] Basit hız sınırı (Django `DatabaseCache` ile): 15 dakikada 10 başarısız giriş, saatte 10 kayıt denemesi
- [ ] Kayıt formuna gizli honeypot alanı
- [ ] `python manage.py check --deploy` uyarılarını gider
- [ ] Supabase Security Advisor'da uyarı kalmadığını doğrula
- [ ] Sorgu performansı: `/bugun/` sabit sayıda sorguyla (`assertNumQueries`)
- [ ] README'yi son haliyle güncelle (deploy + veri güncelleme adımları)

**Kabul kriterleri:** Öğrenci ilerlemesini tek bakışta görebiliyor; ayar değişiklikleri planı tutarlı şekilde yeniliyor; güvenlik kontrolleri temiz.

---

## 14. Kapsam dışı (ileride)

- KPSS, ALES, DGS, YDS (veri modeli hazır; yeni `data/*.json` ve alanlar eklenecek)
- TYT'de Din Kültürü yerine ek Felsefe soruları seçeneği
- Parola sıfırlama ve e-posta doğrulama (e-posta servisi gerekir — öncelikli sonraki adım)
- E-posta/push bildirimleri ve hatırlatmalar
- Yapay zeka ile kişiselleştirilmiş haftalık değerlendirme metinleri
- Konu bazlı soru bankası, video/kaynak önerileri
- Pomodoro sayacı ve gerçek çalışma süresi ölçümü
- Puan ve sıralama tahmini (katsayılar her yıl değiştiği için bilinçli olarak yok)
- Veli/koç paneli
- Mobil uygulama

---

## 15. Durum

> Claude Code her fazın sonunda burayı günceller.

- [x] Faz 0 — İskelet ve ilk deploy (canlı: https://kocluk-projesi.vercel.app)
- [x] Faz 1 — Tasarım sistemi, karşılama ve üyelik
- [x] Faz 2 — Sınav kataloğu ve konu veritabanı (Supabase'e migration ve seed uygulandı)
- [x] Faz 3 — Tanışma, plan motoru çekirdeği ve gerçekçilik raporu (Supabase'e migration uygulandı)
- [ ] Faz 4 — Günlük görevler ve tekrar sistemi
- [ ] Faz 5 — Denemeler, uyarlama ve haftalık değerlendirme
- [ ] Faz 6 — İlerleme paneli, ayarlar ve sağlamlaştırma

**Notlar / alınan kararlar:**
- Faz 0: Django projesi `config`, uygulamalar `accounts`, `catalog`, `planner`, `core`. Özel `User` modeli ilk migration'da. RLS migration'ı (`core/migrations/0001_enable_rls.py`, `core/rls.py`) yalnızca PostgreSQL'de çalışır (SQLite'ta atlanır); yeni tablo ekleyen her fazda `core.rls.enable_rls` çağıran yeni bir migration eklenecek. `USERNAME_FIELD` kontrolü için `email` alanı `unique=True`, büyük/küçük harf duyarsızlığı `UniqueConstraint(Lower("email"))` ile.
- Faz 0: Vercel dokümanına göre `vercel.json` yazılmadı; `manage.py` + `WSGI_APPLICATION = "config.wsgi.application"` yeterli. `STATIC_ROOT` tanımlı, `collectstatic` Vercel'de otomatik çalışır.
- Faz 0: Supabase dokümanına göre transaction pooler'da prepared statement kapalı (`prepare_threshold=None`); bağlantı dizesine `?sslmode=require` eklenmesi öneriliyor.
- Faz 0 tamamlandı: Vercel deploy çalışıyor, canlı admin girişi (`/yonetim/`) ile Supabase okuma/yazma doğrulandı. `CSRF_TRUSTED_ORIGINS=https://kocluk-projesi.vercel.app`.
- Faz 0: Supabase migration uygulandı, 10 tabloda RLS açık (politikasız; Advisor yalnızca INFO "RLS Enabled No Policy" gösteriyor, bu istenen durum). RLS SQL’inde `format(%I)` Django’nun `%` yer tutucusuyla çakıştığı için `quote_ident` kullanılıyor.
- Faz 1: Tasarım sistemi `static/css/main.css` içinde (açık/koyu tema: `data-theme` + `prefers-color-scheme`, seçim `localStorage`'da). Kayıt/giriş/çıkış `accounts` uygulamasında; giriş `LoginView` + e-posta ile `EmailAuthenticationForm`, e-posta her yerde küçük harfe çevrilir (`User.save`, `get_by_natural_key` büyük/küçük harf duyarsız). `/bugun/` şimdilik geçici "yakında" sayfası; Plan/Deneme/İlerleme/Profil sekmeleri pasif. Kayıttan sonra şimdilik `/bugun/`'e gidilir, Faz 3'te tanışmaya yönlenecek. Logo `static/img/logo.svg`. Honeypot ve hız sınırı Faz 6'da.
- Faz 2: `catalog` modelleri, `validation.py` (soru toplamı uyarısı, test toplamı/ön koşul döngüsü/kendi kendine ön koşul/farklı sınav hataları), `check_exam_data` ve `seed_exam_data` (slug'a göre upsert; doğrulama hata verirse transaction geri alınır). `data/yks_2027.json`: 3 oturum, 9 test, 23 ders, 252 konu, 4 alan; hepsi `is_estimated=true`. Konu başlıkları MEB'in 2026 YKS konu-kazanım PDF'inden, soru ağırlıkları ve süreler tahmini (bkz. `data/KAYNAKLAR.md`, `data/DOGRULANACAKLAR.md`). RLS: `core/migrations/0002_enable_rls_catalog.py`. Veriyi yeniden üretmek için kullanılan tek seferlik betik repoda yok; JSON elle ya da `/yonetim/` ile güncellenir.
- Faz 2: Supabase'de 8 yeni tablo, hepsinde RLS açık; 252 konu, 29 ön koşul, 4 alan yüklendi. Doğrulanacak değerler `data/DOGRULANACAKLAR.md`'de.
- Faz 3: Motor `planner/engine/` (saf Python, Django import etmez): `config`, `types`, `phases`, `capacity` (gün gün kapasite + deneme takvimi), `needs`, `selection` (paket bazlı açgözlü seçim), `projection`; ana giriş `make_plan`. Tüm sabitler `config.py`'de; §6.2'de olmayan birkaç sabit (yuvarlama, son 3 gün deneme yok, ilk 30 gün yalnız TYT, +1 saat senaryosu vb.) dosyanın altına eklendi. `PlanTopic.start_day` (yol haritasındaki kaba hafta için) ve `Plan.budget` JSON'una `fits_all`, `mock_count`, `exam_date` eklendi. `MockExam.task` Faz 4'te Task ile birlikte eklenecek. `big_topic_late`: konu büyük, planda `new_small` bütçesi var ama toplam `new_any` bütçesi konunun öğrenme ihtiyacından küçük. Tanışma: `/baslangic/1-5/`, `OnboardingMiddleware` tamamlanmamış kullanıcıyı kaldığı adıma yönlendirir; adım 4'te ders başına otomatik kayıt (JS) veya "Kaydet" butonu. Adım 4'teki "X / Y konu işaretlendi" sayacı seviyesi 0'dan büyük konuları sayar. Rapor `/plan/rapor/`, yol haritası `/plan/`; "Bunları bırakıyoruz" dersler halinde açılır listedir. Üst barda "Sınava N gün" çipi (`planner.context_processors.countdown`). Testlerde bugün `FrozenTodayMixin` ile 2027-01-04'e sabitlenir.
- Yerel geliştirme Python 3.12 ile (`.venv` 3.12'den yeniden oluşturuldu).
- YKS 2027 tarihleri tahmini (TYT 19 Haziran, AYT/YDT 20 Haziran 2027). ÖSYM takvimi açıklanınca `data/yks_2027.json` güncellenip `seed_exam_data` yeniden çalıştırılacak.

---

## 16. Hazır promptlar

Her fazı ayrı bir Claude Code oturumunda başlatabilirsin.

**Faz 0**
```
CLAUDE.md dosyasını baştan sona oku. Yalnızca "Faz 0 — İskelet ve ilk deploy" bölümünü uygula. Vercel ve Supabase yapılandırması yazmadan önce §12'deki dokümanlara bak. Supabase'e migration ve Vercel'e deploy adımlarında benim yapmam gereken bir şey varsa (bağlantı dizesi, ortam değişkeni, panel ayarı) dur ve adım adım söyle. Bitince §15'i güncelle ve özet ver.
```

**Faz 1**
```
CLAUDE.md'yi oku. Faz 0 tamamlandı. Şimdi yalnızca "Faz 1 — Tasarım sistemi, karşılama ve üyelik" bölümünü uygula. Tasarımda §9'a birebir uy, 360px mobil genişlikte kontrol et. Testleri yaz ve çalıştır, §15'i güncelle, nasıl deneyeceğimi anlat.
```

**Faz 2**
```
CLAUDE.md'yi oku. Faz 0 ve 1 tamamlandı. Şimdi yalnızca "Faz 2 — Sınav kataloğu ve konu veritabanı" bölümünü uygula. Konu listelerini güncel MEB/ÖSYM kaynaklarından çıkar, kaynakları data/KAYNAKLAR.md'ye yaz. Kaynağa dayanmayan hiçbir sayıyı kesinmiş gibi girme; is_estimated işaretle ve data/DOGRULANACAKLAR.md'ye ekle. Bitince bana doğrulamam gereken verilerin kısa bir özetini ver. Testleri çalıştır, §15'i güncelle.
```

**Faz 3**
```
CLAUDE.md'yi oku. Faz 0–2 tamamlandı. Şimdi yalnızca "Faz 3 — Tanışma, plan motoru çekirdeği ve gerçekçilik raporu" bölümünü uygula. Motoru §6'daki gibi saf Python olarak planner/engine/ altında yaz, tüm sabitleri config.py'de tut. Önce motorun testlerini (§6.10'daki ilgili senaryolar) yaz, sonra motoru, sonra arayüzü. Testleri çalıştır, §15'i güncelle ve örnek bir kullanıcı için raporun nasıl göründüğünü özetle.
```

**Faz 4**
```
CLAUDE.md'yi oku. Faz 0–3 tamamlandı. Şimdi yalnızca "Faz 4 — Günlük görevler ve tekrar sistemi" bölümünü uygula. Görev dağıtımında §6.7'deki doldurma sırasına ve karıştırma kurallarına, tembel günlük işlemlerde §6.9'a birebir uy. Önce motor testlerini yaz. Testleri çalıştır, §15'i güncelle.
```

**Faz 5**
```
CLAUDE.md'yi oku. Faz 0–4 tamamlandı. Şimdi yalnızca "Faz 5 — Denemeler, uyarlama ve haftalık değerlendirme" bölümünü uygula. Kapsam daraltmanın kullanıcı onayı olmadan asla uygulanmadığından emin ol. Koç mesajlarında §8.6'daki ton kurallarına uy. Testleri çalıştır, §15'i güncelle.
```

**Faz 6**
```
CLAUDE.md'yi oku. Faz 0–5 tamamlandı. Şimdi yalnızca "Faz 6 — İlerleme paneli, ayarlar ve sağlamlaştırma" bölümünü uygula. Grafikleri kütüphane kullanmadan SVG ile çiz. check --deploy çıktısını ve Supabase güvenlik uyarılarını sıfırla. README'yi güncelle, §15'i güncelle.
```
