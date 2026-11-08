# 本机运行（key 在 apikey.local，已 gitignore）
powershell: $env:PIX_APERO_API_KEY=(gc apikey.local | % {$_.Split('=')[1]}); python demo_server.py
