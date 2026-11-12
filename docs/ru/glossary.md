# okf-notebooks

[English version](../en/glossary.md)

MCP-сервер, который даёт ИИ-клиентам общие блокноты заметок под git, где единственный авторитет в вопросе доверия — человек.

Названия терминов оставлены английскими: так они выглядят в коде, CLI и веб-интерфейсе.

## Язык

### Идентичность

**Actor**:
Личность, от имени которой вносится изменение, и профиль прав, который её ограничивает. Один из фиксированного набора; каждый — либо агентский актор, либо человек.
_Не называть_: User, account, role

**Agent actor**:
Actor, определяемый по Token (`claude-code`, `opencode`, `external-harness`).
_Не называть_: Agent (как существительное для личности)

**Human**:
Actor, определяемый доступом к хосту через CLI или Human-сессией в Review UI; токена не имеет и единственный может verify и archive.
_Не называть_: Operator, admin, owner

**Token**:
Учётные данные, привязанные ровно к одному Agent actor; выдаются на машину или клиента и несут метку.
_Не называть_: Key, API key, session

**Client**:
Программа, которая подключается с Token, например Claude Desktop или Claude Code. Не равна Actor: её версия записывается в авторство, но права она не определяет.
_Не называть_: Agent, harness (когда имеется в виду программа вообще)

**Review UI**:
Браузерный интерфейс, который отдаёт тот же процесс, что и MCP-эндпоинт; через него Human читает заметки, меняет статус и смотрит историю. Отключён, пока не задан Human password.
_Не называть_: Admin panel, dashboard, web app

**Human session**:
Вход в Review UI с помощью Human password, держится на cookie. Действует как Human и никогда не принимается MCP-эндпоинтом, так же как Token никогда не принимается Review UI.
_Не называть_: Login token, user session

**Human password**:
Единственный секрет, который открывает Human session; задаётся переменной окружения `OKF_NOTEBOOKS_UI_PASSWORD`. Не Token.
_Не называть_: Admin token, API key

**Revision**:
Один git-коммит, затронувший файл Concept, с его Actor и временем; Review UI показывает историю Concept как набор Revision и diff Revision против родителя.
_Не называть_: Version, change

**Last revised**:
Время последней Revision Concept, независимо от Actor и включая смену статуса Human. Review UI сортирует по нему список заметок типа, новые сверху.
_Не называть_: Updated, modified, recent

**Links to**:
Concept внутри блокнота, на которые указывает Concept ссылками `/type/slug` в теле или frontmatter. Ссылка на несуществующую цель считается битой.
_Не называть_: Relations, connections, outgoing links

**Cited by**:
Concept, у которых данный Concept входит в Links to.
_Не называть_: Backlinks, references, incoming links

**Sources**:
Внешние или внутренние ссылки, которые Concept перечисляет в поле `sources` как подтверждение сказанного. Это не Link to.
_Не называть_: Citations, references

**Tags**:
Свободные метки, которые Concept перечисляет в поле `tags`; Review UI фильтрует по ним заметки типа.
_Не называть_: Labels, categories

### Комментарии

**Thread**:
Обсуждение, привязанное к процитированному фрагменту Concept: первый Comment и ответы на него. Он открыт или решён и живёт вне Concept: не входит в его тело и frontmatter и не создаёт Revision.
_Не называть_: Conversation, annotation, review

**Comment**:
Одно сообщение в Thread, написанное Human или Agent actor.
_Не называть_: Note (Note — это Concept), message, reply (reply — это Comment, не первый в треде)

**Quote**:
Фрагмент текста Concept, на котором начат Thread; хранится вместе с Thread. Review UI подсвечивает его, пока он ещё находится в Concept.
_Не называть_: Selection, anchor, range

**Detached**:
Thread, чей Quote больше не встречается в Concept. Остаётся читаемым вместе с Quote и видимым агентам, но не подсвечивается.
_Не называть_: Orphaned, stale, broken

**Mention**:
`@` с именем Actor в Comment, адресующий этого Agent actor. Mention треда — это Mention всех его Comment.
_Не называть_: Tag (Tag размечает Concept), assignment

**Open / resolved**:
Состояние Thread. Агентам отдаются открытые Thread, если они не запросили решённые; Human или адресованный Agent actor может закрыть и снова открыть тред.
_Не называть_: Closed, done, status (это слово принадлежит Concept)

## Связи

- **Actor** — это либо **Agent actor**, либо **Human**; **Human** ровно один.
- **Token** принадлежит одному **Agent actor**; у **Agent actor** может быть много **Token** (по одному на машину или **Client**).
- **Client** подключается с одним **Token** и потому действует как **Agent actor** этого токена; например, у Claude Desktop нет собственного Actor.
- Права привязаны к **Actor**, никогда не к **Client** и не к **Token**.
- **Human session** привязана к **Human**; она никогда не несёт **Token**, а **Token** никогда её не открывает.
- **Last revised** Concept — это время его последней **Revision**; у Concept без Revision его нет.
- **Cited by** Concept вычисляется из **Links to** других Concept и никогда не хранится в самом Concept.
- **Thread** принадлежит одному Concept, никогда его не меняет и никогда не входит в его **Revisions**.
- **Thread** виден **Agent actor**, когда он открыт и его **Mentions** пусты или включают этого Actor; тогда Agent actor видит весь Thread.
- **Mention** называет **Actor**, никогда не **Token** и не **Client**; адресуются все Token этого Actor.
- **Agent actor** может пользоваться Thread, только если его права включают comments.
- **Review UI** существует только пока задан **Human password**.
