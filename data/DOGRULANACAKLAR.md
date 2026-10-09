# Doğrulanacaklar

> Bu dosya, **resmi kaynağa dayanmayan** ya da kaynaklar arasında çelişki olan değerleri listeler.
> Veri tabanındaki **tüm 252 konu `is_estimated = true`** olarak işaretlidir; hiçbir sayı kesinmiş gibi sunulmaz.
> Bir değeri doğruladığında `data/yks_2027.json` içinde ya da `/yonetim/` panelinden düzelt, `is_estimated` işaretini kaldır.

## 1. Sınav tarihleri (tahmini)

- TYT 19 Haziran 2027, AYT ve YDT 20 Haziran 2027 **tahminidir.** ÖSYM 2027 takvimini Kasım 2026 ortasında açıklamadan önce resmi tarih yok.
- Takvim açıklanınca `data/yks_2027.json` içindeki `date` alanlarını güncelle, `date_is_estimated` değerini `false` yap ve `python manage.py seed_exam_data data/yks_2027.json` komutunu yeniden çalıştır.

## 2. Oturum süreleri

- TYT 165 dk, AYT 180 dk, YDT 120 dk olarak girildi (plan dosyasındaki değerler).
- **Çelişki:** Araştırma sırasında bazı kaynaklar TYT için 135 dk, bazıları 165 dk yazıyor. Resmî 2027 kılavuzundan doğrula. Bu değer deneme görevinin süresini belirler.

## 3. Soru sayıları

- Testlerin soru sayıları (TYT 120, AYT 160, YDT 80) ve ders dağılımları 2026 YKS düzenine göredir; 2027 kılavuzu çıkınca kontrol et.
- **Tahmini ayrımlar (`*`):** TYT ve AYT Matematik/Geometri ayrımı (30 + 10) resmî olarak ayrı verilmeyebilir; tahmini işaretlidir.
- AYT Sosyal Bilimler-2 içinde "Felsefe Grubu 12" soru olarak girildi; Felsefe, Mantık, Psikoloji ve Sosyoloji arasındaki dağılım ayrı verilmedi.

## 4. Konu bazlı sayılar (hepsi tahmini)

- **`avg_questions` (ortalama soru sayısı):** Konu bazında yayımlanmış güvenilir bir derleme bulunamadı. Her konuya, dersin resmi soru sayısını paylaştıran **göreli bir ağırlık** verildi; ağırlıklar çıkmış soru dağılımına dair genel bilgiye dayanıyor, kaynaklı değil. Her dersin konu toplamı dersin soru sayısına tam eşit.
- **`learn_hours` (öğrenme süresi):** Tamamı tahmini. Sıfırdan öğrenip temel soru çözebilme süresi konunun kapsamına ve zorluğuna göre kabaca verildi.
- **`difficulty` (zorluk):** Öznel tahmin.
- **`minutes_per_question`:** Dersin soru başına dakikası tahmini (pratik görevlerindeki soru sayısını belirler).
- Bu sayılar planın konu seçimini doğrudan etkiler. Önce **soru sayısı çok, süresi kısa** konular öne alınır; yani en çok bu iki sütunu gözden geçirmek değerli.

## 5. Konu başlıkları ve gruplama

- **MEB'in resmî PDF'inden çıkarılanlar:** Matematik, Fizik, Kimya, Biyoloji (11–12. sınıf konu başlıkları), Din Kültürü, Tarih ve İnkılap Tarihi üniteleri, Coğrafya kazanım blokları, Felsefe üniteleri. Ders başına hangi bölümler olduğu `source_note` alanında yazar.
- **ÖSYM tarzı derleme (resmî belgede bu başlıkla yok):** TYT Türkçe, AYT Türk Dili ve Edebiyatı, YDT İngilizce, TYT/AYT Matematik'in problem alt başlıkları. Başlıklar ÖSYM'nin soru türlerine göre derlendi; resmî bir listeyle eşleştir.
- **Bazı konular birleştirildi** (ör. TYT Tarih 10 başlık, Coğrafya kazanımları bloklara ayrıldı). İstersen admin panelinden böl ya da birleştir.
- **Mantık, Psikoloji, Sosyoloji:** PDF'ten ünite başlıkları otomatik ayrıştırılamadı; her biri tek konu olarak girildi.

## 6. Test ve oturum ataması (tahmini)

- **Tarih-1 / Tarih-2:** Tarih-1'e 9.–10. sınıf, Tarih-2'ye 11. sınıf ve İnkılap Tarihi üniteleri atandı. Gerçek AYT dağılımıyla karşılaştır.
- **Coğrafya-1 / Coğrafya-2:** Doğal sistemler ve nüfus Coğrafya-1'e, ekonomi, bölgeler, çevre, ulaşım ve turizm Coğrafya-2'ye atandı.
- **TYT Din / AYT Din:** TYT'ye 9.–10. sınıf, AYT'ye 11.–12. sınıf üniteleri atandı.
- **TYT Fizik/Kimya/Biyoloji ve AYT:** TYT'ye 9.–10. sınıf, AYT'ye 11.–12. sınıf konuları atandı. TYT Biyoloji'de 10. sınıf konularının hangileri çıktığını doğrula.
- **TYT Felsefe:** 10. sınıf üniteleri alındı; Mantık TYT'de çıkıyorsa eklenmeli.

## 7. Ön koşullar

- Yalnızca bariz olanlar girildi (ör. Köklü Sayılar → Üslü Sayılar, İntegral → Türev → Limit). Emin olunmayan ön koşul girilmedi. Sınavlar arası (TYT → AYT) ön koşul tanımlanmadı.

## 8. Ders özeti

`*` = soru sayısı tahmini. Süre, o dersteki konuların toplam `learn_hours` değeridir.

| Oturum | Ders | Soru | Konu | Toplam süre (saat) |
|---|---|---|---|---|
| TYT | Türkçe | 40 | 13 | 88 |
| TYT | Matematik | 30 * | 27 | 134 |
| TYT | Geometri | 10 * | 9 | 48 |
| TYT | Tarih | 5 | 10 | 38 |
| TYT | Coğrafya | 5 | 10 | 35 |
| TYT | Felsefe | 5 | 4 | 15 |
| TYT | Din Kültürü ve Ahlak Bilgisi | 5 | 10 | 20 |
| TYT | Fizik | 7 | 10 | 59 |
| TYT | Kimya | 7 | 9 | 41 |
| TYT | Biyoloji | 6 | 6 | 33 |
| AYT | Matematik | 30 * | 13 | 122 |
| AYT | Geometri | 10 * | 6 | 42 |
| AYT | Fizik | 14 | 18 | 93 |
| AYT | Kimya | 13 | 10 | 70 |
| AYT | Biyoloji | 13 | 13 | 79 |
| AYT | Türk Dili ve Edebiyatı | 24 | 14 | 103 |
| AYT | Tarih-1 | 10 | 10 | 51 |
| AYT | Coğrafya-1 | 6 | 7 | 37 |
| AYT | Tarih-2 | 11 | 11 | 58 |
| AYT | Coğrafya-2 | 11 | 8 | 51 |
| AYT | Felsefe Grubu | 12 | 11 | 57 |
| AYT | Din Kültürü ve Ahlak Bilgisi | 6 | 10 | 20 |
| YDT | İngilizce | 80 | 13 | 238 |

## 9. 2027 kılavuzu

Tüm yapı **2026 YKS** düzenine göredir. ÖSYM'nin 2027 YKS kılavuzu ve MEB'in 2027 konu–kazanım belgesi yayımlandığında bu dosyadaki her madde yeniden kontrol edilmelidir.
