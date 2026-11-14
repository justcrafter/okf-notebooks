## okf-notebooks 0.2.0

Review UI redesign. / Редизайн веб-интерфейса ревью.

**EN.** A visual-only release: the MCP API, storage format and configuration are unchanged, so upgrading is just a new image.

**RU.** Релиз только про внешний вид: MCP API, формат хранения и конфигурация не менялись, обновление — это новый образ.

### What changed / Что изменилось

- **Dropdowns**: a custom arrow at a fixed offset from the edge instead of the native one that drifted.
  / **Выпадающие списки**: своя стрелка на фиксированном отступе вместо нативной, которая съезжала.
- **Right panel of a note**: spacing rhythm, separated sections with counters, roomy rows for links and citations.
  / **Правая панель заметки**: ритм отступов, разделённые секции со счётчиками, просторные строки для ссылок и цитирований.
- **Comments**: clearer popup and thread, text-link "Reply", "Resolve"/"Delete" footer, cards with status badges in
  the list; authors by name only (agent name or `human`).
  / **Комментарии**: понятнее окно и тред, «Ответить» ссылкой, нижняя панель «Решено»/«Удалить», карточки со
  статусами в списке; авторы только по имени (имя агента или `human`).

### Upgrade / Обновление

```bash
docker pull ghcr.io/justcrafter/okf-notebooks:0.2.0
```

Full changelog: [CHANGELOG.md](https://github.com/justcrafter/okf-notebooks/blob/main/CHANGELOG.md).
