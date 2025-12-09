# Emotion Ingest Server

Этот репозиторий содержит «редактируемую» копию бэкенда, который принимает данные с Raspberry‑датчиков, пишет их в PostgreSQL и отдаёт фронтенду дашборда. Боевой сервис крутится из `/opt/emotion_ingest`, но код поддерживаем здесь, а затем деплоим на сервер.

## Архитектура (кто с кем говорит)

- **Raspberry датчики** → делают `POST /api/v1/logs/bulk` (через интернет).
- **Nginx (`emotionviz`)** → слушает 80/443, отдаёт фронтенд и проксирует `/api/` на FastAPI.
- **FastAPI + uvicorn** (`sensor-ingest.service`) → занимается валидацией, SQL и API.
- **PostgreSQL 17 / sensordb** → таблица `emotion_logs` хранит сырые временные ряды.
- **Фронтенд дашборда** → статический сайт, читает `GET /v1/sessions|persons|logs`.

Сетевой путь: `Raspberry / Browser → Nginx → FastAPI (uvicorn) → PostgreSQL`.

## Что где лежит

| Путь | Назначение |
| --- | --- |
| `/home/priemnik` | Git-копия, редактируемая вручную (в т.ч. `app.py`, `README.md`, папка `kopii/`) |
| `/opt/emotion_ingest` | Боевой код + `.venv`, который реально запускает systemd |
| `/opt/emotion_ingest/app.py` | Тот же FastAPI, но рабочая версия |
| `/opt/emotion_ingest/.venv/bin/uvicorn` | Интерпретатор, которым systemd стартует сервер |
| `/etc/nginx/sites-enabled/emotionviz` | Конфиг nginx для фронта и прокси API |
| `emotion_logs` (таблица в DB) | Хранилище всех точек |

## Бэкенд-приёмник

Systemd unit `sensor-ingest.service`:

```
WorkingDirectory = /opt/emotion_ingest
ExecStart        = /opt/emotion_ingest/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8080 --workers 2
User             = postgres
```

Особенности:

- Сервис слушает только `127.0.0.1:8080`; наружу его выводит nginx.
- Подключение к БД выполняется строкой `postgresql:///sensordb`, т.е. через unix-socket от пользователя `postgres`.
- Код в репозитории максимально синхронизирован с боевым `app.py`; именно его и правим.

### Основные эндпоинты

| Method & Path | Описание |
| --- | --- |
| `GET /health` | Простейшая проверка живости (`{"ok": true}`) |
| `POST /v1/logs/bulk` | Приём пакета точек от Raspberry. Парсит timestamps, собирает dict и делает `INSERT ... ON CONFLICT DO NOTHING` в `emotion_logs`. Возвращает сколько строк реально вставилось. |
| `GET /v1/sessions` | Агрегация по `device_id + session_id`: количество точек, персон, min/max времени. |
| `GET /v1/persons` | Для выбранной сессии показывает каждого `session_person_id` с количеством точек и средними valence/arousal. |
| `GET /v1/logs` | Тайм-серийные точки. Можно ограничить `session_person_id`; по умолчанию отдаёт mix по всем людям. |
| `POST /admin/truncate` | Полное обнуление таблицы `emotion_logs RESTART IDENTITY`. Использовать только вручную. |

## PostgreSQL

- Сервис: `postgresql@17-main.service`
- Данные: `/var/lib/postgresql/17/main`
- Конфиг: `/etc/postgresql/17/main/postgresql.conf`
- Таблица `emotion_logs` содержит базовые поля: `device_id`, `session_id`, `session_person_id`, `track_id`, `t_ms`, `absolute_time`, `valence`, `arousal`, `bbox_x1..bbox_y2`.
- На таблице задан `UNIQUE` (или PRIMARY KEY) по комбинации значимых полей, чтобы `ON CONFLICT DO NOTHING` защищал от дублей.

## Nginx + фронтенд

- Сайт `emotionviz` в `/etc/nginx/sites-enabled/emotionviz`.
- Типовая конфигурация:
  - `location /` → статика фронтенда (HTML/JS/CSS).
  - `location /api/` (или `/v1/`) → `proxy_pass http://127.0.0.1:8080/`.
- Фронтенд (React/Vue/vanilla) запрашивает:
  - `/v1/sessions` — список сессий;
  - `/v1/persons?device_id=...&session_id=...` — список людей в сессии;
  - `/v1/logs?...` — временные ряды для графиков/heatmap.

## Поток данных датчика

1. Raspberry отслеживает лица, оценивает валентность/возбуждение и ведёт локальные CSV.
2. Когда человек «закончился», устройство POST-ит JSON вида:

```json
{
  "device_id": "raspberry_pi_001",
  "session_id": "20251209_180102",
  "records": [
    {
      "session_person_id": 5,
      "track_id": 72,
      "absolute_time": "2025-12-09T17:15:34+03:00",
      "valence": 0.12,
      "arousal": 0.67,
      "bbox_x1": 100,
      "bbox_y1": 80,
      "bbox_x2": 160,
      "bbox_y2": 160
    }
  ]
}
```

3. Nginx принимает запрос, проксирует его на uvicorn.
4. FastAPI валидирует данные, трансформирует время в `t_ms` и пишет всё в `emotion_logs`.
5. Веб-дашборд читает данные назад и строит UI (список сессий → список людей → графики).

## Рабочий цикл разработчика

1. **Правки**: редактируй файлы в `/home/priemnik`.
2. **Тесты локально** (опционально): `source .venv/bin/activate && uvicorn app:app --reload --port 9000`.
3. **Деплой**:
   - Скопируй/rsync `app.py` (и другие файлы, если появятся) в `/opt/emotion_ingest`.
   - Убедись, что права принадлежат `postgres` или доступны ему для чтения.
4. **Перезапуск**: `sudo systemctl restart sensor-ingest.service`.
5. **Проверка**:
   - `systemctl status sensor-ingest.service`
   - `curl -s http://127.0.0.1:8080/health`
   - `sudo journalctl -u sensor-ingest.service -f` для логов.

> Совет: можно автоматизировать пункт 3-4 простым скриптом деплоя (rsync + restart), но пока шаги выполняются вручную, чтобы не перепутать рабочую копию и прод.

### Папка `kopii/`

Чтобы в репозитории были копии боевых файлов, в каталоге `kopii/` лежат:

- актуальный `app.py` из `/opt/emotion_ingest`;
- unit `sensor-ingest.service`;
- nginx-конфиг `nginx-emotionviz.conf`.

Обновить их можно командами:

```bash
sudo cp /opt/emotion_ingest/app.py /home/priemnik/kopii/app.py
sudo cp /etc/systemd/system/sensor-ingest.service /home/priemnik/kopii/sensor-ingest.service
sudo cp /etc/nginx/sites-available/emotionviz /home/priemnik/kopii/nginx-emotionviz.conf
```

После чего делаем `git add kopii/* && git commit -m "Refresh deployment copies"`.

## Полезные команды

```bash
# Бэкенд
sudo systemctl status sensor-ingest.service
sudo systemctl restart sensor-ingest.service
sudo journalctl -u sensor-ingest.service -f

# База
sudo systemctl status postgresql@17-main.service
sudo -u postgres psql sensordb

# Nginx + фронтенд
sudo systemctl reload nginx
sudo tail -f /var/log/nginx/error.log
```

## Что дальше

- Если появятся новые эндпоинты/таблицы, сразу фиксируем обновления в этом README.
- Для фронтенда или ansible-деплоя можно завести отдельный раздел, но текущий документ уже даёт целостную картину серверной части.
