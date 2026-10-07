#!/usr/bin/env bash
# GitHub Actions sarmalayıcı: komutu çalıştırır, çıktının son satırlarını n8n/is_hatalari.json'a kaydeder.
# İş "başarısız" görünmez (e-posta gelmez); hata panelde (Uyarılar) ve saha uyarısında görünür.
#   kullanım: bash is_calistir.sh "<iş adı>" <komut...>
ad="$1"; shift
"$@" > /tmp/is_cikti.txt 2>&1; kod=$?
cat /tmp/is_cikti.txt
python3 is_hata_kaydet.py "$ad" "$kod" /tmp/is_cikti.txt
for i in 1 2 3; do
  git config user.name "aesun-bot"; git config user.email "aesun-bot@users.noreply.github.com"
  git add n8n/is_hatalari.json; git diff --cached --quiet && break
  git commit -qm "İş durumu: $ad ($kod)" && git pull --rebase -q && git push -q && break
  sleep 5
done
exit 0
