<?php
// Aksaray Enerji · iletişim formu -> bilgi@aksarayenerji.com.tr
declare(strict_types=1);
$ALICI = 'bilgi@aksarayenerji.com.tr';
$GONDEREN = 'web@aksarayenerji.com.tr'; // alan adına ait bir adres olmalı (SPF)

function geri(string $d): void { header('Location: iletisim.html?durum=' . $d, true, 303); exit; }
function al(string $k, int $max): string {
  $v = isset($_POST[$k]) && is_string($_POST[$k]) ? trim($_POST[$k]) : '';
  $v = str_replace(["\r", "\0"], '', $v);
  return mb_substr($v, 0, $max, 'UTF-8');
}
if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') geri('hata');
if (al('web', 200) !== '') geri('ok');            // bal küpü: bot
if (al('kvkk', 2) !== '1') geri('hata');

$ad = str_replace("\n", ' ', al('ad', 120));
$firma = str_replace("\n", ' ', al('firma', 160));
$tel = str_replace("\n", ' ', al('tel', 40));
$ep = str_replace("\n", '', al('eposta', 160));
$konu = str_replace("\n", ' ', al('konu', 60));
$kap = str_replace("\n", ' ', al('kapasite', 60));
$mesaj = al('mesaj', 4000);
if ($ad === '' || $mesaj === '' || !filter_var($ep, FILTER_VALIDATE_EMAIL)) geri('hata');

// basit hız sınırı: aynı IP'den 2 dakikada 1 ileti
$ip = preg_replace('/[^0-9a-fA-F:.]/', '', $_SERVER['REMOTE_ADDR'] ?? '');
$kilit = sys_get_temp_dir() . '/ae_form_' . md5($ip);
if (is_file($kilit) && time() - filemtime($kilit) < 120) geri('hata');
@touch($kilit);

$govde = "Web sitesi teklif / bilgi formu\n\n"
  . "Ad soyad : $ad\nFirma    : $firma\nTelefon  : $tel\nE-posta  : $ep\n"
  . "Konu     : $konu\nKapasite : $kap\n\nMesaj:\n$mesaj\n\n"
  . "KVKK onayı: evet · " . date('Y-m-d H:i') . " · IP $ip\n";
$basliklar = "From: Aksaray Enerji Web <$GONDEREN>\r\n"
  . "Reply-To: $ep\r\n"
  . "MIME-Version: 1.0\r\nContent-Type: text/plain; charset=UTF-8\r\nContent-Transfer-Encoding: 8bit\r\n";
$baslik = '=?UTF-8?B?' . base64_encode("Web formu: $konu · $ad") . '?=';
$ok = mail($ALICI, $baslik, $govde, $basliklar, '-f' . $GONDEREN);
geri($ok ? 'ok' : 'hata');
