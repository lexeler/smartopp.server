# Папка `kopii`

Здесь лежат копии файлов, которые реально используются на продовом сервере. Их стоит держать в репозитории, чтобы при переносе на другой хост можно было быстро восстановить службу, nginx и приложение.

## Что тут есть

- `app.py` — такой же код FastAPI, который лежит в `/opt/emotion_ingest/app.py`.
- `sensor-ingest.service` — unit-файл systemd (ложится в `/etc/systemd/system/sensor-ingest.service`).
- `nginx-emotionviz.conf` — конфиг сайта `emotionviz` (копируется в `/etc/nginx/sites-available/emotionviz` и линком в `sites-enabled`).

## Как обновлять копии из боевых путей

```bash
# 1. заберите рабочий app.py
sudo cp /opt/emotion_ingest/app.py /home/priemnik/kopii/app.py

# 2. скопируйте systemd-unit
sudo cp /etc/systemd/system/sensor-ingest.service /home/priemnik/kopii/sensor-ingest.service

# 3. заберите nginx-конфиг
sudo cp /etc/nginx/sites-available/emotionviz /home/priemnik/kopii/nginx-emotionviz.conf
```

После обновления не забудьте зафиксировать изменения:

```bash
cd /home/priemnik
git add kopii/*
git commit -m "Refresh deployment copies"
```

## Как использовать при развёртывании

1. Скопируйте `app.py` и остальные файлы на новый сервер (см. README в корне для структуры каталогов).
2. Положите `sensor-ingest.service` в `/etc/systemd/system/`, выполните `sudo systemctl daemon-reload && sudo systemctl enable --now sensor-ingest.service`.
3. Положите `nginx-emotionviz.conf` в `/etc/nginx/sites-available/`, сделайте симлинк в `sites-enabled` и перезапустите nginx.

Так в репозитории всегда есть последняя проверенная конфигурация продового окружения.
