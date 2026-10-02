# Qashqadaryo viloyat pedagogik mahorat markazi tekshiruv boti

Markaz boti PDF, DOCX va TXT hujjatlardan matn ajratadi, Quetext DeepSearch API
orqali ochiq internet va akademik veb manbalar bilan tekshiradi, shu bilan birga
oldin markaz bazasiga yuborilgan hujjatlar bilan ichki o‘xshashlikni hisoblaydi.
Internet va ichki baza dalillari ustma-ust tushsa bir marta hisoblanib, yakuniy
professional PDF hisobot va QR-verifikatsiyali sertifikat yaratiladi.

Bot interfeysi, PDF hisobot, QR-verifikatsiya sahifasi va sertifikat
“Qashqadaryo viloyat pedagogik mahorat markazi” nomi hamda rasmiy logotipi
bilan bir xil brendingda ishlaydi.

## Telegram profilini yangilash

Deploy vaqtida bot `Qashqadaryo viloyat pedagogik mahorat markazi` nomi,
tavsifi va qisqa tavsifini Telegram API orqali avtomatik yangilaydi. Telegram
bot profil rasmini API orqali almashtirib bo‘lmagani uchun uni bir marta
`@BotFather` ichida `/setuserpic` buyrug‘i bilan o‘rnating. Tanlanadigan rasm:
`app/assets/qashqadaryo_pmm_logo.png`.

## Asosiy imkoniyatlar

- PDF, DOCX va TXT fayllardan matn ajratish;
- Quetext DeepSearch orqali real plagiat tekshiruvi;
- Quetext qaytargan barcha matchlar, URL, input offset va mos fragmentlar;
- markazning ichki hujjatlar bazasi bilan real so‘z-fragment solishtiruvi;
- O‘zbek lotin/kirill yozuvini bir xil taqqoslash alifbosiga normalizatsiya qilish;
- bir parcha bir nechta manbada topilsa uni yakuniy foizda bir marta hisoblash;
- Internet %, ichki baza %, umumiy o‘xshashlik % va umumiy originallik %;
- inglizcha matnda Quetext AI Detector va gaplar kesimidagi ehtimollar;
- o‘zbekcha matnda ehtiyotkor, past ishonchli uslubiy-statistik indikator;
- mualliflikni tekshirish savollari;
- faqat yakunlangan ko‘p manbali skandan keyin professional PDF va sertifikat;
- webhook o‘rniga polling - Railway domeni va webhook secret kerak emas;
- Railway qayta ishga tushsa, tugallanmagan vazifalarni bazadan davom ettirish;
- PostgreSQL, Railway va Docker bilan ishlash.
- bank tanlashsiz qo‘lda to‘lov: paket, rekvizit, chek rasmi va admin tasdig‘i;
- so‘z balansi, takroriy tasdiqdan himoya va xatoda avtomatik balans qaytarish.

> AI indikatori mualliflikni isbotlamaydi. O‘zbekcha indikator ayniqsa ehtiyotkor
> talqin qilinishi kerak. Yakuniy akademik qarorni inson eksperti qabul qiladi.

## Railway Variables

| O‘zgaruvchi | Qiymat |
|---|---|
| `BOT_TOKEN` | BotFather bergan token |
| `DATABASE_URL` | Railway PostgreSQL `DATABASE_URL` reference |
| `ADMIN_IDS` | Raqamli Telegram ID |
| `PAYMENT_CARD_NUMBER` | Foydalanuvchiga ko‘rsatiladigan karta raqami |
| `PAYMENT_CARD_OWNER` | Karta egasining ism-familiyasi |
| `PAYMENT_REQUIRED` | `true` — balanssiz tekshiruvni bloklaydi |
| `ADMIN_WEB_USERNAME` | Web-admin uchun asosiy Owner login |
| `ADMIN_WEB_PASSWORD` | Kamida kuchli va noyob web-admin paroli |
| `ADMIN_WEB_SECRET` | Sessiyani imzolash uchun kamida 32 belgili maxfiy qator |
| `ADMIN_SESSION_HOURS` | Admin sessiyasi muddati, standart `12` soat |
| `MAX_FILE_MB` | `20` |
| `MAX_TEXT_CHARS` | `200000` |
| `QUETEXT_API_KEY` | Quetext `Account > API Keys` bo‘limidagi kalit |
| `QUETEXT_POLL_SECONDS` | Ixtiyoriy, standart `3` |
| `QUETEXT_TIMEOUT_SECONDS` | Ixtiyoriy, standart `900` (15 daqiqa) |
| `PUBLIC_BASE_URL` | Ixtiyoriy, sertifikat QR/verifikatsiya domeni |
| `RAILWAY_PUBLIC_DOMAIN` | Railway avtomatik domeni; QR uchun fallback |

`PORT`ni Railway avtomatik beradi. Oldingi `COPYLEAKS_*` va `WEBHOOK_SECRET`
qiymatlari ishlatilmaydi. `PUBLIC_BASE_URL` esa V6 sertifikat QR-verifikatsiyasi
uchun foydali va mavjud bo‘lsa saqlanishi kerak.

## Qo‘lda to‘lov oqimi

1. Foydalanuvchi `💳 To‘lov qilish` tugmasini bosadi.
2. Bank tanlash oynasisiz so‘z paketlaridan birini tanlaydi.
3. Bot karta raqami, qabul qiluvchi va aniq summani ko‘rsatadi.
4. Foydalanuvchi chek rasmini yuboradi.
5. Administratorga rasm bilan `✅ Tasdiqlash` va `❌ Rad etish` tugmalari boradi.
6. Tasdiqlansa so‘zlar balansga faqat bir marta qo‘shiladi; rad etilsa foydalanuvchi
   xabardor qilinadi.
7. Tekshiruv boshlanganda hujjatdagi so‘zlar balansdan yechiladi. Quetext texnik
   xato bilan tugasa, sarflangan so‘zlar avtomatik qaytariladi.

Standart paketlar: 10 000 so‘z — 10 000 so‘m; 25 000 — 22 000 so‘m;
50 000 — 40 000 so‘m; 100 000 — 75 000 so‘m.

## Professional web-admin panel

Deploydan keyin panel `https://SIZNING-DOMEN/admin/login` manzilida ochiladi.
Oddiy foydalanuvchiga admin panel havolasi ko‘rsatilmaydi.

Panel imkoniyatlari:

- real vaqtga yaqin dashboard va asosiy moliyaviy ko‘rsatkichlar;
- foydalanuvchini ism, username yoki Telegram ID orqali qidirish;
- balans qo‘shish/ayirish, sabab va majburiy tasdiq;
- foydalanuvchini bloklash yoki blokdan chiqarish;
- chek rasmini ko‘rish, to‘lovni tasdiqlash yoki sabab bilan rad etish;
- tariflarni yaratish, narx/so‘z miqdorini o‘zgartirish va o‘chirish;
- tekshiruvlarni filtrlash va xatoli tekshiruvni qayta boshlash;
- sertifikatni bekor qilish yoki qayta faollashtirish;
- ommaviy xabarni oldindan ko‘rish va ikkinchi tasdiq bilan yuborish;
- foydalanuvchi, to‘lov, tekshiruv va audit CSV hisobotlari;
- Owner, Moliya, Operator, Support va Auditor rollari;
- barcha muhim amallar uchun vaqt, admin, obyekt, tafsilot va IP audit jurnali.

Web-admin sessiyasi imzolangan, cookie `HttpOnly` va `SameSite=Lax`; barcha
o‘zgartiruvchi formalar CSRF token bilan himoyalangan.

## Quetext API kaliti

1. `https://www.quetext.com/` saytida hisob oching.
2. Account ichidagi `API Keys` bo‘limiga kiring.
3. Yangi API key yarating.
4. Kalitni Railway bot servisidagi `QUETEXT_API_KEY` variable’iga kiriting.
5. Deploy tugagach botga kamida 20 so‘zli hujjat yuboring.

Quetext amaldagi developer hujjatida yangi API hisobiga 5 000 bepul so‘z
ko‘rsatilgan. API wallet oddiy Quetext obunasidan alohida. Har bir plagiat POST
so‘rovi 1 000 so‘z uchun $0.10, AI POST so‘rovi ham 1 000 so‘z uchun $0.10
turadi. Inglizcha hujjatda ikkalasi ishlatilsa, umumiy narx 1 000 hujjat so‘zi
uchun taxminan $0.20 bo‘ladi.

## Tekshiruv oqimi

1. Bot hujjatdan matn ajratadi, UTF-8 xavfsizlaydi va bazaga saqlaydi.
2. Matn Quetext’ga internet/akademik plagiat so‘rovi sifatida yuboriladi.
3. Quetext ishlayotgan paytda hujjat V6 ichki taqqoslashga tayyor turadi.
4. Inglizcha matnda alohida AI so‘rovi ham yuboriladi.
5. Bot har 3 soniyada progress va yakuniy Quetext endpointlarini tekshiradi.
6. Quetext tugagach oldingi barcha markaz hujjatlari bilan ichki skan bajariladi.
7. Kamida 8 so‘zli normalizatsiyalangan aniq fragmentlar manba va pozitsiya bilan qayd etiladi.
8. Internet va ichki fragmentlar ustma-ust joylarda de-dup qilinadi.
9. Umumiy o‘xshashlik/originallik saqlanadi va PDF + sertifikat yuboriladi.
10. Tashqi yoki ichki majburiy skan xato bersa tekshirilmagan yakuniy hujjat berilmaydi.

V6 progress yozuvi kechiksa ham tayyor natijani bevosita hisobot endpointidan
oladi. Standart kutish muddati 15 daqiqa; ko‘p hollarda natija ancha tez keladi.

## V6 ichki baza qanday ishlaydi

Ichki taqqoslash V6.1 da dalilga asoslangan aniq/normalizatsiyalangan matn
o‘xshashligini topadi. Registr, tinish belgisi va O‘zbek lotin/kirill yozuvidagi
farqlar normalizatsiya qilinadi. Har bir topilgan parcha joriy hujjatdagi
pozitsiyasi bilan saqlanadi. Bir parcha bir nechta eski hujjatda uchrasa yakuniy
foizga faqat bir marta kiradi.

Boshqa foydalanuvchining shaxsiy ma’lumoti hisobotga chiqarilmaydi; manba
`Qashqadaryo PMM ichki hujjati #ID` ko‘rinishida anonimlanadi. Foydalanuvchining o‘z oldingi
hujjati bo‘lsa uning fayl nomi ko‘rsatilishi mumkin.

## Til bo‘yicha izoh

Quetext rasmiy til ro‘yxatida o‘zbek va rus tillari ko‘rsatilmagan. Bot bunday
matnni plagiat endpointiga yuboradi, ammo natijaning tilga xos aniqligini
kafolatlamaydi. O‘zbekcha AI bo‘limida Quetext o‘rniga past ishonchli mahalliy
stilometrik indikator ishlatiladi. Tashqi Quetext AI tekshiruvi hozir inglizcha
matn uchun yoqilgan.

## Lokal ishga tushirish

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

Brauzerda `http://localhost:8080/health` manzilida `provider: Quetext` chiqishi
kerak.
