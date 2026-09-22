# Нефтекод 2.0 — пакет для комиссии

Пакет содержит операторский интерфейс, доказательную базу, презентацию и исходный
код проекта. Для простого просмотра достаточно Python; для запуска расчётов через
API рекомендуется Python 3.11+ и `uv`.

## Состав пакета

- `index.html` — операторский советчик;
- `benchmark.html` — дашборд с бенчмарками и доказательной базой;
- `benchmark_data.json` — исходные показатели дашборда;
- `presentation.pptx` — презентация проекта;
- `app.js`, `styles.css`, `assets/`, `data/` — ресурсы веб-интерфейса;
- `project_code/` — исходный код API, оркестратора, агентов качества и
  надёжности, оптимизатора и интеграционного слоя.

## Быстрый просмотр интерфейсов

Откройте PowerShell в этой папке и выполните:

```powershell
python -m http.server 4173
```

После запуска откройте:

- операторский экран: <http://127.0.0.1:4173/index.html>;
- бенчмарк: <http://127.0.0.1:4173/benchmark.html>.

Бенчмарк работает полностью офлайн. Операторский экран без API показывает
сохранённые демонстрационные сценарии KEEP, REFUSE и RECOMMEND.

## Полный запуск с Integration API

Установите `uv`, если он ещё не установлен:

```powershell
python -m pip install uv
```

В первом окне PowerShell перейдите в исходный код и установите зависимости:

```powershell
cd project_code
uv sync --project integration --extra dev
uv run --project integration neftecode-api --host 127.0.0.1 --port 8000
```

API будет доступен по адресам:

- Swagger UI: <http://127.0.0.1:8000/docs>;
- проверка состояния: <http://127.0.0.1:8000/api/v1/health>.

Во втором окне PowerShell, из корня этого пакета, запустите интерфейсы:

```powershell
python -m http.server 4173
```

Откройте <http://127.0.0.1:4173/index.html>. Экран автоматически подключится к
API на `127.0.0.1:8000` и покажет текущий расчёт.

## Запуск API через Docker

Из корня пакета:

```powershell
docker build -t neftecode-api project_code
docker run --rm -p 8000:8000 neftecode-api
```

Затем отдельно запустите статический сервер командой `python -m http.server 4173`.

## Проверка исходного кода

Из папки `project_code`:

```powershell
uv run --project integration pytest -q
```

Остановить API или статический сервер можно сочетанием `Ctrl+C` в соответствующем
окне PowerShell.
