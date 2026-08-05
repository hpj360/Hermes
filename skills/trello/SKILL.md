---
name: trello
description: Manage Trello boards, lists, and cards via the Trello REST API.
homepage: https://developer.atlassian.com/cloud/trello/rest/
metadata: {"clawdbot":{"emoji":"📋","requires":{"bins":["jq"],"env":["TRELLO_API_KEY","TRELLO_TOKEN"]}}}
---

# Trello Skill

Manage Trello boards, lists, and cards directly from Clawdbot.

## Setup

1. Get your API key: https://trello.com/app-key
2. Generate a token (click "Token" link on that page)
3. Set environment variables:
   ```bash
   export TRELLO_API_KEY="your-api-key"
   export TRELLO_TOKEN="your-token"
   ```

## Usage

All commands use curl to hit the Trello REST API.

### List boards
```bash
curl -s "https://api.trello.com/1/members/me/boards?key=$TRELLO_API_KEY&token=$TRELLO_TOKEN" | jq '.[] | {name, id}'
```

### List lists in a board
```bash
curl -s "https://api.trello.com/1/boards/{boardId}/lists?key=$TRELLO_API_KEY&token=$TRELLO_TOKEN" | jq '.[] | {name, id}'
```

### List cards in a list
```bash
curl -s "https://api.trello.com/1/lists/{listId}/cards?key=$TRELLO_API_KEY&token=$TRELLO_TOKEN" | jq '.[] | {name, id, desc}'
```

### Create a card
```bash
curl -s -X POST "https://api.trello.com/1/cards?key=$TRELLO_API_KEY&token=$TRELLO_TOKEN" \
  -d "idList={listId}" \
  -d "name=Card Title" \
  -d "desc=Card description"
```

### Move a card to another list
```bash
curl -s -X PUT "https://api.trello.com/1/cards/{cardId}?key=$TRELLO_API_KEY&token=$TRELLO_TOKEN" \
  -d "idList={newListId}"
```

### Add a comment to a card
```bash
curl -s -X POST "https://api.trello.com/1/cards/{cardId}/actions/comments?key=$TRELLO_API_KEY&token=$TRELLO_TOKEN" \
  -d "text=Your comment here"
```

### Archive a card
```bash
curl -s -X PUT "https://api.trello.com/1/cards/{cardId}?key=$TRELLO_API_KEY&token=$TRELLO_TOKEN" \
  -d "closed=true"
```

## Notes

- Board/List/Card IDs can be found in the Trello URL or via the list commands
- The API key and token provide full access to your Trello account - keep them secret!
- Rate limits: 300 requests per 10 seconds per API key; 100 requests per 10 seconds per token; `/1/members` endpoints are limited to 100 requests per 900 seconds

## Examples

```bash
# Get all boards
curl -s "https://api.trello.com/1/members/me/boards?key=$TRELLO_API_KEY&token=$TRELLO_TOKEN&fields=name,id" | jq

# Find a specific board by name
curl -s "https://api.trello.com/1/members/me/boards?key=$TRELLO_API_KEY&token=$TRELLO_TOKEN" | jq '.[] | select(.name | contains("Work"))'

# Get all cards on a board
curl -s "https://api.trello.com/1/boards/{boardId}/cards?key=$TRELLO_API_KEY&token=$TRELLO_TOKEN" | jq '.[] | {name, list: .idList}'
```

---

## Related skills（边界声明）

- **github**: GitHub Issue / PR 管理。本 skill 是 Trello 看板管理，github 是 GitHub issue tracker。**不重叠**：根据团队实际使用的工具选择其一。
- **notion**: Notion 数据库（可做看板视图）。本 skill 是专用看板工具，notion 是通用文档+数据库。功能上 notion 也可做看板，但本 skill 专注 Trello 平台。
- **triage**: Issue 状态机分诊。本 skill 关注 Trello card CRUD（list/create/move），triage 关注 issue 业务逻辑（state machine）。组合：triage 决定"打什么 label/走什么状态" → 本 skill 执行 Trello board 操作。
