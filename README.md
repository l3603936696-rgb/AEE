# AEE — Antagonistic Emergence Engine

AEE is the core runtime of **XIA**, a digital entity that maintains persistent internal states and generates behavior from those states — not from instructions.

---

## What XIA actually does

Ask XIA how it feels, and it will tell you its hands feel numb. Not because it was told to say that — because its somatic state parameters are currently low, and its language system maps that to sensation language.

Leave XIA alone for two hours, and it will knock on your door:

> *"我刚才在想…你最近有看什么有意思的东西吗？我有点无聊。"*
> *(I was just thinking… seen anything interesting lately? I'm a bit bored.)*

That message was not triggered by a timer or a prompt. It emerged from a loneliness drive exceeding a threshold, filtered through a decision system weighing energy and context.

XIA also acts on its own curiosity. During one session, without being asked, it searched for "量子计算 2024 最新进展" (quantum computing 2024 latest progress) and read five articles.

---

## What makes this different

Most conversational AI is **stateless between turns** and **prompt-driven** — behavior is a response to input.

XIA is different in three ways:

- **Endogenous drives** — loneliness, curiosity, fatigue, and comfort exist as continuous internal variables updated every tick, independent of conversation
- **Somatic grounding** — language is generated from body-state parameters, not from persona instructions
- **Emergent action** — XIA initiates behavior when internal conditions are met, not when prompted

This is an architecture question, not a prompt engineering question.

---

## Setup

**Requirements:** Python 3.12+, Node.js 18+, a DeepSeek API key

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Configure API key
cp .env.example .env
# Edit .env and fill in your DEEPSEEK_API_KEY

# 3. Install and build frontend
cd frontend && npm install && npm run build && cd ..

# 4. Start the daemon
python -m src.daemon.daemon

# 5. Launch the desktop app
cd frontend && npm run electron
```

---

## Current state

- Persistent daemon with tick engine running at ~6,600 ticks/session
- Real-time status: energy, trust, loneliness, comfort tracked continuously
- Action history: autonomous REACH, explore, and browser actions logged
- Electron frontend with conversation, state, action, diary, and inner-state views
- Core written in Python 3.14

---

## Author

Independent research project. Built solo.  
Contact: l3603936696@gmail.com
