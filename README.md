# Agora Transcript 0.3.0

YouTube bağlantısı veya yerel kayıt dosyasından zaman damgalı Türkçe konuşma dökümü.
Özet/LLM düzeltmesi yapılmaz; sayılar ve koşul ifadeleri kaynakta çözümlendiği gibi saklanır.

## Agora'da kurulum

Kendi kullanıcınızla çalıştırın; bütün scripti `sudo` ile çalıştırmayın.
Repo publictir. Varsayılan HTTPS kurulumu için GitHub hesabı, token veya SSH anahtarı gerekmez.

```bash
if [ ! -d "$HOME/agora-transcript-public/.git" ]; then
  git clone https://github.com/eylemc/agora-transcript.git "$HOME/agora-transcript-public"
fi && bash "$HOME/agora-transcript-public/scripts/install-agora-transcript.sh"
```

Kurucu:

1. Ayrı checkout'u oluşturur veya `main` dalını yalnız fast-forward ile günceller.
2. Eksikse `git`, `curl`, `unzip`, sertifika paketlerini apt/sudo ile kurar.
3. Gerekliyse uv ve Deno'yu uygulamanın `.tools/` klasörüne indirir.
4. Python 3.12 venv ve yerel faster-whisper bağımlılıklarını kurar.
5. CUDA 12 cuBLAS / cuDNN 9 kütüphanelerini venv'e ekler.
6. `large-v3` modelini indirip seçilen aygıtta kısa bir gerçek çözümleme testi yapar.
7. `~/.local/bin/agora-transcript` başlatıcısını oluşturur.

Model ve CUDA paketlerinin ilk indirmesi birkaç GB olabilir. Model indirme süresi
bağlantıya bağlıdır. Mevcut sistem Python'u/CUDA kurulumu ve çalışan
servisler değiştirilmez; başka GPU işleri otomatik durdurulmaz.

Model çalışma testini ertelemek: `bash scripts/install-agora-transcript.sh --skip-model-check`.
CPU kurulumu: `bash scripts/install-agora-transcript.sh --cpu`.
GPU testi başarısızsa VRAM, NVIDIA sürücüsü ve hata çıktısı incelenmelidir.

Tek başına indirilen `scripts/install-agora-transcript.sh` da repoyu klonlayıp kurabilir.
Alternatif hedef: `AGORA_TRANSCRIPT_REPO_DIR=/istenen/yol bash install-agora-transcript.sh`.
Varsayılan adres `https://github.com/eylemc/agora-transcript.git` şeklindedir.
Önceden GitHub anahtarı ayarlı kullanıcılar isterse `AGORA_TRANSCRIPT_REPO_URL` ile
SSH adresini seçebilir. Script token istemez/yazdırmaz, SSH doğrulamasını kapatmaz.

Public repodan tek script ile kurulum:

```bash
curl -fL https://raw.githubusercontent.com/eylemc/agora-transcript/main/scripts/install-agora-transcript.sh -o /tmp/install-agora-transcript.sh && bash /tmp/install-agora-transcript.sh
```

## Web arayüzü

Mevcut CLI kurulumundan sonra Agora'da:

```bash
cd "$HOME/agora-transcript-public"
git pull --ff-only
bash scripts/install-transcript-web.sh
```

Mac'te ayrı bir terminalde (AGORA_ADRESI yerine SSH için kullandığınız adres):

```bash
ssh -N -L 8765:127.0.0.1:8765 eylem@AGORA_ADRESI
```

Tünel açıkken tarayıcıda **http://127.0.0.1:8765** açın.
YouTube bağlantısı, ses/altyazı yöntemi, GPU/CPU ve dil seçilebilir.
İşlem günlüğü otomatik güncellenir; aynı web sunucusu bir defada tek iş çalıştırır.
Mevcut `~/agora-transcripts/` kayıtları da listelenir. Dökümde arama ve
TXT/SRT/JSON/inceleme raporu indirme desteklenir. Yerel dosyalar CLI ile işlenir.

Arayüz yalnız 127.0.0.1 üzerinde dinler; herkese açık barındırma veya çok kullanıcılı
kullanım için tasarlanmamıştır. Tarayıcıyı kapatmak işi durdurmaz; web servisini
durdurmak aktif çözümlemeyi keser. CLI ile ayrıca iş başlatırsanız GPU paylaşılır.
Sunucu kapanırken yarım kalan kayıt `processing` görünebilir; otomatik devam yoktur.

```bash
systemctl --user status agora-transcript-web.service
journalctl --user -u agora-transcript-web.service -n 50 --no-pager
# Yalnız aktif döküm yokken:
systemctl --user restart agora-transcript-web.service
```

Kullanıcı servisi oturum kapanınca durabilir. Oturumdan bağımsız çalışması istenirse
Agora'da `loginctl enable-linger "$USER"` uygulanabilir. Servissiz kullanım:
`bash src/agora-transcript/web.sh` (terminal açık kalmalıdır).

## Çalıştırma

Bu yayının sesini doğrudan çözümlemek:

```bash
"$HOME/.local/bin/agora-transcript" 'https://www.youtube.com/watch?v=cgBmqZE8XCg' --mode audio --device cuda
```

Önce mevcut özgün altyazıyı denemek:

```bash
"$HOME/.local/bin/agora-transcript" 'https://www.youtube.com/watch?v=cgBmqZE8XCg'
```

Yerel OBS/video kaydı:

```bash
"$HOME/.local/bin/agora-transcript" '/path/to/yayin.mkv' --mode audio --device cuda
```

`auto`: insan altyazısı, ardından otomatik özgün altyazı, ardından ses çözümlemesi.
`captions`: yalnız altyazı. Otomatik çeviri altyazıları seçilmez.
`audio`: altyazıdan bağımsız ASR. Varsayılan model multilingual `large-v3`.
NVIDIA'da `int8_float16`, CPU'da `int8` hesaplama kullanılır.
YouTube erişimi başarısızsa yerel kayıt kullanılabilir; indirme garanti edilmez.
İsteğe bağlı `--cookies /yerel/cookies.txt` yalnız kullanıcının sağladığı Netscape
çerez dosyasını kullanır; tarayıcıdan otomatik çerez alınmaz ve dosya çıktılara kopyalanmaz.

## Güncelleme

```bash
bash "$HOME/agora-transcript-public/scripts/install-agora-transcript.sh"
```

Venv yeniden oluşturulmaz. Yerel değişiklik, farklı repo/dal veya ayrışmış Git geçmişi
varsa durulur; reset/force push/stash/silme yapılmaz. Paketlerin çözülen sürümleri
`installed-versions.txt` içinde tutulur; requirements tam kilitlenmiş değildir.

## Çıktılar

Başlatıcı varsayılan olarak `~/agora-transcripts/` altında her çalıştırma için yeni
zaman damgalı klasör açar. `--output /başka/yol` ile değiştirilebilir.

| Dosya | İçerik |
| --- | --- |
| `transcript.txt` | Başlangıç/bitiş zamanlı konuşma segmentleri |
| `transcript.srt` | Altyazı |
| `transcript.json` | Segmentler, varsa sözcük zamanları ve ASR skorları |
| `review.json` | Sayı/fiyat, düşük skor ve çakışma kontrol işaretleri |
| `manifest.json` | Kaynak, yöntem, model/sürümler, SHA-256 ve işlem durumu |
| `segments.raw.jsonl` | Tamamlanan ASR'nin ham segmentleri |
| `segments.partial.jsonl` | Yarıda kalan ASR'nin o ana kadarki segmentleri |
| `source.*` | İndirilen özgün altyazı veya ses/video |

Yerel girdi değiştirilmez. İşler birbirinin üzerine yazılmaz. Başarı çıkış kodu 0;
hata 1; kullanıcı kesintisi 130. Son işlem durumu `manifest.json` ile belirlenir.
Girdi, çerez, modeller ve üretilen dökümler Git'e eklenmez. HTTP/MCP sunucusu,
otomatik kanal takibi veya konsey veritabanına yükleme bu sürümde yoktur.

## Doğruluk ve sınırlar

`completed`, yazılım işlemi tamamlandı demektir; her sözcük doğrulandı demek değildir.
`human_verified` varsayılan false'tur. Finansal seviyeler ve "eğer/olabilir/kesin değil"
ifadeleri ilk yayında sesle karşılaştırılmalıdır. Fiyatlar model ipucuna eklenmez.
Skorlar kalibre edilmiş doğruluk yüzdeleri değildir; kontrol işaretleri hata kanıtı değildir.

VAD sessizliği süzer, müziği güvenilir biçimde sınıflandırmaz. Gürültü/sessizlik/müzik
üzerinde ASR sözcük atlayabilir veya olmayan metin üretebilir. `--no-vad` ikinci geçiş
olanağı verir ancak doğruluk garantisi sağlamaz. Kayan altyazı tekrarları otomatik
silinmez; çakışan segmentler işaretlenir. Görselde olup söylenmeyen seviye metne girmez.
OCR ve konuşmacı ayrımı yoktur. Kesintiden otomatik devam yoktur; yarım iş korunur.

Bu yayında ilk kontrol: 13:00–20:40 ve 36:40–52:20; özellikle fiyatlar ve koşul ifadeleri.
Kaynak medya ve çıktıları saklama/silme kullanıcıya aittir.

## Testler

Repo kökünde:

```bash
(cd src/agora-transcript && python3 -m unittest discover -s tests -v)
python3 -m unittest discover -s scripts/tests -v
```

8 transkript testi ve 5 kurulum testi; Git testleri yerel fixture repolarında çalışır.
Sanal ortam kurulum testi paket indirmelerini taklit eder. Gerçek YouTube/GPU/Türkçe
kalite testi geliştirme oturumunda yapılmadı; kurucunun çalışma testi Agora'da yapılır.

Teknik kaynaklar:
- https://github.com/SYSTRAN/faster-whisper/blob/master/README.md
- https://github.com/yt-dlp/yt-dlp/blob/master/README.md
- https://github.com/yt-dlp/yt-dlp/wiki/EJS
- https://docs.astral.sh/uv/reference/installer/
- https://docs.deno.com/runtime/getting_started/installation/
