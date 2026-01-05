# 🚐 BoTiul - WhatsApp Bot for Trips

AI-powered WhatsApp bot designed to make group trips easier and more organized.

---

## 🎯 Goal

BoTiul is built to be the ultimate **trip companion bot** for WhatsApp groups. Whether you're planning a road trip with friends, organizing a group vacation, or coordinating a hiking adventure — BoTiul helps keep everyone on the same page by:

- **Summarizing conversations** so no one misses important updates
- **Answering questions** based on the group's collective knowledge
- **Tracking shared expenses** like Splitwise, right inside WhatsApp
- **Auto-uploading trip photos** to a shared Google Photos album
- **Detecting spam** to keep the group clean and focused

---

## ✨ Features

### 💬 Smart Conversation Summaries
Ask the bot to catch you up on what you missed. It uses AI to summarize the day's messages, highlighting key decisions and discussions.

### 🧠 Knowledge Base Q&A
The bot learns from your group's chat history. Ask questions like *"What time are we meeting?"* or *"Where are we staying?"* and get instant answers based on past conversations.

### 💰 Expense Tracking (Splitwise-style)
Track shared expenses directly in the chat:
- *"שילמתי 200 שקל על דלק"* → Bot records the expense
- *"כמה כל אחד חייב?"* → Bot shows who owes what
- Supports splitting among everyone or specific tagged members

### 📸 Trip Photo Album
Automatically upload all photos shared in the group to a shared Google Photos album. Set it up once, and every image gets backed up.

### 🛡️ Spam Detection
When someone shares a suspicious WhatsApp group link, the bot alerts the group admin with a spam confidence score.

### 🔕 Opt-Out Privacy
Users can DM the bot to opt-out of being @mentioned in summaries:
- `opt-out` → Your name appears as text, not a mention
- `opt-in` → Re-enable mentions
- `status` → Check your current preference

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend Framework** | [FastAPI](https://fastapi.tiangolo.com/) — async Python web framework |
| **AI/LLM** | [Pydantic AI](https://ai.pydantic.dev/) with OpenAI models |
| **Embeddings** | [Voyage AI](https://www.voyageai.com/) for semantic search |
| **Database** | PostgreSQL with [pgvector](https://github.com/pgvector/pgvector) for vector storage |
| **ORM** | [SQLModel](https://sqlmodel.tiangolo.com/) + [SQLAlchemy](https://www.sqlalchemy.org/) async |
| **WhatsApp Integration** | Custom client for WhatsApp Web API |
| **Photo Storage** | Google Photos API integration |
| **Observability** | [Logfire](https://logfire.pydantic.dev/) for monitoring & tracing |
| **Containerization** | Docker & Docker Compose |
| **Package Manager** | [uv](https://github.com/astral-sh/uv) — fast Python package manager |
| **Code Quality** | [Ruff](https://github.com/astral-sh/ruff) (linting/formatting) + [Pyright](https://github.com/microsoft/pyright) (type checking) |
| **Testing** | [pytest](https://pytest.org/) with async support |

---

## 🏗️ Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   WhatsApp      │────▶│   FastAPI        │────▶│   PostgreSQL    │
│   Web API       │◀────│   Backend        │◀────│   + pgvector    │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │   AI Services        │
                    │  • OpenAI (LLM)      │
                    │  • Voyage (Embeddings)│
                    │  • Google Photos API │
                    └──────────────────────┘
```

**Key Components:**
- **Webhook Handler** — Receives and processes incoming WhatsApp messages
- **Intent Router** — Uses LLM to classify message intent (summarize, question, expense, etc.)
- **Knowledge Base** — Semantic search over group message history using vector embeddings
- **Expense Tracker** — Splitwise-like balance calculation and settlement suggestions
- **Trip Album** — OAuth2 flow for Google Photos integration

---

## 📄 License

[LICENSE](LICENSE)
