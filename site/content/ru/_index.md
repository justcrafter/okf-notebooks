---
title: "okf-notebooks"
description: "MCP-сервер, который даёт ИИ-агентам общую долговременную память в виде Markdown-блокнотов под git, а доверие к записям определяет человек."

hero:
  eyebrow: "MCP-сервер · self-hosted · MIT"
  title: "Память агентов, которую можно **прочитать, сравнить и проверить**"
  lead: "okf-notebooks даёт Claude Code, Claude Desktop, opencode и другим MCP-клиентам общую долговременную память в виде **блокнотов**: обычных каталогов Markdown-файлов в формате [OKF](https://okf.md/) под одним git-репозиторием. Человек читает и проверяет написанное агентами во встроенном веб-интерфейсе."
  meta: "Один ASGI-процесс (Streamable HTTP), без внешней БД: поиск идёт по SQLite FTS5."
  cta_install: "Начать"
  cta_github: "Открыть на GitHub"
  image_alt: "Веб-интерфейс ревью: заметка с оглавлением, ссылками, тегами и статусом доверия"

idea:
  title: "Идея"
  lead: "Агенты забывают всё между сессиями, а то, что помнят, лежит в закрытом хранилище вендора. okf-notebooks кладёт эту память туда, где вы её видите и контролируете."
  items:
    - title: "Обычные файлы"
      text: "Каждая заметка — Markdown с YAML-frontmatter. Её можно открыть в любом редакторе, сравнить через git, откатить через `git revert` и сохранить через `git push`."
    - title: "Общая для агентов"
      text: "Claude Code, opencode и внешний harness читают и пишут в одни и те же блокноты, каждый со своим токеном и правами."
    - title: "Доверие определяет человек"
      text: "Всё, что пишет агент, остаётся `draft`. Только человек ставит `verified`, `stable` или `deprecated`, а правка агентом снимает отметку."
    - title: "Безопасность по построению"
      text: "Личность и права определяются только токеном; текст блокнота приходит агенту как данные в маркерах с nonce; похожее на секрет отклоняется при записи."

how:
  title: "Как это работает"
  steps:
    - title: "Агенты пишут"
      text: "Через MCP-инструменты: поиск, чтение, запись и правка заметок с блокировкой по `etag` для параллельных агентов."
    - title: "Git записывает"
      text: "Коммит на каждую запись с актором в сообщении, необязательный фоновый push в приватный remote."
    - title: "У блокнотов есть типы"
      text: "У каждого блокнота свой `scope` и словарь типов заметок (`Decision`, `Playbook`…) с обязательными полями и сроком устаревания."
    - title: "Человек проверяет"
      text: "В веб-интерфейсе или CLI: читает, ставит verified, смотрит diff, отвечает в тредах и одобряет заявки на новые блокноты и типы."

not:
  title: "Чем проект не является"
  text: "Это не векторная база данных, не облачный сервис и не мультитенантная система. Это небольшой сервер для одного человека или одной команды, который хранит знания агентов в файлах, доступных для ревью."

screens:
  title: "Веб-интерфейс ревью"
  lead: "Включается по желанию и работает в том же процессе: заметки со ссылками и обратными ссылками, история ревизий с diff, таблицы и диаграммы Mermaid, треды комментариев, на которые отвечают агенты."
  items:
    - src: "images/ui-notebook.png"
      alt: "Обзор блокнота"
    - src: "images/ui-comments.png"
      alt: "Тред комментариев к фрагменту"
    - src: "images/ui-type-dark.png"
      alt: "Страница типа в тёмной теме"

quickstart:
  title: "Быстрый старт"
  lead: "Нужен Docker с Compose. Можно и Python 3.11+ с `uv`, см. страницу [Установка](/ru/install/)."
  more: "Полная инструкция по установке"
  steps:
    - title: "Настроить"
      code: |
        git clone https://github.com/justcrafter/okf-notebooks.git
        cd okf-notebooks
        mkdir -p data config
        cat > config/config.yaml <<'EOF'
        root: /data
        server:
          host: 0.0.0.0
          allowed_hosts: ["127.0.0.1:8765", "localhost:8765"]
        EOF
    - title: "Запустить"
      text: "Пароль необязателен и включает веб-интерфейс ревью на том же порту."
      code: |
        export OKF_NOTEBOOKS_UI_PASSWORD='длинный-случайный-пароль'
        OKF_NOTEBOOKS_UID=$(id -u) OKF_NOTEBOOKS_GID=$(id -g) docker compose up -d
    - title: "Создать токен и блокнот"
      code: |
        docker exec -it okf-notebooks okf-notebooks token create --actor claude-code --label laptop
        docker exec -it okf-notebooks okf-notebooks notebook create demo \
          --description "Заметки по проекту demo: решения, термины, регламенты" \
          --scope "Устойчивые факты и решения по demo; не писать временные заметки" \
          --preset core
    - title: "Подключить Claude Code"
      code: |
        claude mcp add --transport http notebooks http://127.0.0.1:8765/mcp \
          --header "Authorization: Bearer <токен>"

scenarios:
  title: "Для чего используют"
  more: "Все сценарии"
  items:
    - anchor: "personal-memory"
      title: "Память одного агента"
      text: "Claude Code хранит решения, термины и runbook'и между сессиями, а каждую заметку можно открыть в редакторе."
    - anchor: "project-knowledge"
      title: "База знаний проекта"
      text: "Пресет `dev-project`: глоссарий, ADR, спеки, тикеты, исследования и баги в одном блокноте."
    - anchor: "multi-agent"
      title: "Несколько агентов, одна память"
      text: "Claude Code пишет, opencode дополняет, CI-harness только читает, у каждого свой токен."
    - anchor: "human-review"
      title: "Проверка человеком"
      text: "Агенты пишут черновики, человек их проверяет, а правка агентом снимает отметку."
    - anchor: "adopt-existing"
      title: "Заметки, которые уже есть"
      text: "Существующий OKF-каталог, например docs проекта, можно взять под управление."
    - anchor: "network-and-backup"
      title: "С разных машин и с бэкапом"
      text: "Доступ к серверу по LAN или Tailscale, история уходит в приватный git-remote."
---
