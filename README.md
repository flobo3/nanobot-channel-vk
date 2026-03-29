## nanobot-channel-vk: [VK (VKontakte)](https://vk.com) Channel Plugin for [nanobot](https://github.com/HKUDS/nanobot)

[На русском языке](#русский-язык)

A plugin for [nanobot](https://github.com/HKUDS/nanobot) that connects your AI agent to VK (VKontakte) communities via the Bots Long Poll API. The bot can receive and reply to messages in private dialogs and group chats.

## Features
- **Long Poll API**: Real-time message processing using `vkbottle`.
- **Attachments**: Extracts photos (highest resolution) and documents from incoming messages.
- **Reply Context**: Understands when a user replies to a specific message.
- **Typing Status**: Automatically sets the "typing" status while the LLM is generating a response.
- **Reactions**: Automatically reacts to incoming messages (configurable, defaults to 👌).

---

## Quick Start

### 1. Prepare your VK Community

1. **Create a community** (group or public page) if you don't have one.
2. Go to **Manage (Управление) → Messages (Сообщения)** and enable them.
3. Go to **Manage → Additional (Дополнительно) → API Usage (Работа с API) → Access Tokens (Ключи доступа)**, click *Create token* and select the following permissions:
   - **Community messages (Сообщения сообщества)**
   - **Community management (Управление сообществом)** (required for Bots Long Poll API)
4. Go to **Manage → Additional → API Usage → Long Poll API**:
   - Enable Long Poll API.
   - On the **Event types (Типы событий)** tab, check **Incoming messages (Входящие сообщения)**.
5. *(Optional, for group chats)* Go to **Manage → Messages → Bot settings (Настройки для бота)** and enable *Allow adding community to chats*.

### 2. Installation

Install the plugin into the same Python environment where your `nanobot` is running:

```bash
uv pip install nanobot-channel-vk
```
*(Or use `pip install nanobot-channel-vk` if you are not using `uv`)*

### 3. Configuration

Add the `vk` channel to your `~/.nanobot/config.json`:

```json
{
  "channels": {
    "vk": {
      "enabled": true,
      "token": "vk1.a.YOUR_VK_COMMUNITY_TOKEN",
      "allowFrom": ["*"],
      "reactionId": 10
    }
  }
}
```

#### Configuration Parameters

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `enabled` | boolean | `false` | Enable or disable the VK channel. |
| `token` | string | `""` | Your VK community access token. |
| `allowFrom` | list[str] | `[]` | List of allowed user IDs. Use `["*"]` to allow everyone. If empty, all users are blocked. |
| `reactionId` | int | `10` | ID of the reaction to set on incoming messages (1-16). Examples: `1`=❤️, `2`=🔥, `3`=😂, `4`=👍, `8`=😡, `10`=👌, `16`=🎉. Set to `0` to disable reactions. |

### 4. Run

Restart your nanobot. It will automatically discover the plugin via Python `entry_points` and start polling VK!

---

<a id="русский-язык"></a>
## nanobot-channel-vk

Плагин для [nanobot](https://github.com/HKUDS/nanobot), который подключает вашего ИИ-агента к сообществам VK (ВКонтакте) через Bots Long Poll API. Бот может принимать и отвечать на сообщения в личных диалогах и беседах.

## Возможности
- **Long Poll API**: Обработка сообщений в реальном времени с использованием `vkbottle`.
- **Вложения**: Извлекает фотографии (в максимальном разрешении) и документы из входящих сообщений.
- **Контекст ответов**: Понимает, когда пользователь отвечает на конкретное сообщение (reply).
- **Статус "печатает"**: Автоматически устанавливает статус "печатает", пока LLM генерирует ответ.
- **Реакции**: Автоматически ставит реакцию на входящие сообщения (настраивается, по умолчанию 👌).

---

## Быстрый старт

### 1. Подготовка сообщества ВКонтакте

1. **Создайте сообщество** (группу или паблик), если его ещё нет.
2. Откройте **Управление → Сообщения** и включите их.
3. Откройте **Управление → Дополнительно → Работа с API → Ключи доступа**, нажмите *Создать ключ* и выберите права:
   - **Сообщения сообщества**
   - **Управление сообществом** (необходимо для работы Bots Long Poll API)
4. Откройте **Управление → Дополнительно → Работа с API → Long Poll API**:
   - Включите Long Poll API (переключатель "Включен").
   - На вкладке **Типы событий** обязательно отметьте **Входящие сообщения**.
5. *(Для работы в беседах)* Откройте **Управление → Сообщения → Настройки для бота** и включите *Разрешать добавлять сообщество в чаты*.

### 2. Установка плагина

Установите плагин в то же виртуальное окружение Python, где запущен ваш `nanobot`:

```bash
uv pip install nanobot-channel-vk
```
*(Или используйте `pip install nanobot-channel-vk`, если вы не используете `uv`)*

### 3. Настройка

Добавьте канал `vk` в ваш конфигурационный файл `~/.nanobot/config.json`:

```json
{
  "channels": {
    "vk": {
      "enabled": true,
      "token": "vk1.a.ВАШ_ТОКЕН_СООБЩЕСТВА",
      "allowFrom": ["*"],
      "reactionId": 10
    }
  }
}
```

#### Параметры конфигурации

| Параметр | Тип | По умолчанию | Описание |
| :--- | :--- | :--- | :--- |
| `enabled` | boolean | `false` | Включить или выключить канал VK. |
| `token` | string | `""` | Ключ доступа вашего сообщества ВКонтакте. |
| `allowFrom` | list[str] | `[]` | Список ID разрешенных пользователей. Используйте `["*"]`, чтобы разрешить всем. Если список пуст, бот будет игнорировать всех. |
| `reactionId` | int | `10` | ID реакции на входящие сообщения (от 1 до 16). Примеры: `1`=❤️, `2`=🔥, `3`=😂, `4`=👍, `8`=😡, `10`=👌, `16`=🎉. Установите `0`, чтобы отключить реакции. |

### 4. Запуск

Перезапустите nanobot. Он автоматически найдет плагин через механизм `entry_points` Python и запустит опрос ВКонтакте!