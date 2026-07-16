# 2026 July 17th talk by Murali Jayaraman about "using AI"


## Talk title: From Workflows to multi-agent automation: The logical progression of AI in biology research

## Speaker: Muralidharan (Murali) Jayaraman, PhD, MBA. 
Assistant Director for Shared Resources, Stephenson Cancer Center, University of Oklahoma Health, Oklahoma City OK 73104.



## Abstract:

Artificial intelligence is reshaping how research gets done — but "using AI" is not a single skill. It is a spectrum of autonomy, and knowing where a given task belongs on that spectrum is what separates useful automation from wasted effort and avoidable risk. 

This presentation provides a practical map of that spectrum through four stages of increasing autonomy. We begin with AI as an assistant, where the model accelerates individual tasks — summarizing literature, drafting protocols, debugging analysis code — while you stay in control of every step. We then move to workflow automation, using no-code tools such as n8n and Power Automate to let fixed, repeatable pipelines run themselves. From there we cross a crucial threshold into agentic AI, where the model is given a goal rather than a script and decides its own steps. Finally, we reach multi-agent systems, in which specialized agents coordinate as a team to tackle larger research tasks such as automated literature reviews.


## Flyer:

![Here is the Flyer](https://github.com/Oklahoma-Data-Science-Workshop/2026-jayaraman/blob/main/images/2026July17SeminarFlyer.jpg)

---

## Code from the talk

Three real, running projects I built for my own work at the Stephenson Cancer
Center. Each one lives higher up the autonomy spectrum from the abstract above, so
together they trace the progression from **workflow automation → agentic →
multi-agent**. All are MIT licensed — read them, run them, adapt them.

| Project | Spectrum stage | What it does |
|---|---|---|
| [`email-assistant/`](email-assistant/) | **Workflow automation** | A no-code [n8n](https://n8n.io) pipeline fetches external email, has Claude classify it (topic, urgency, action items), and posts to a Flask triage dashboard. The included, sanitized workflow export is importable into your own n8n. |
| [`ilab-monitor/`](ilab-monitor/) | **Agentic** | An always-on service that turns the clunky iLab equipment-reservation API into an instant query service, so a chat agent can answer "who's using the Axioscan right now?" from your phone. |
| [`travel-assistant/`](travel-assistant/) | **Multi-agent** | The "TripMind" planner — a chain of Claude Sonnet agents (interview → route → itinerary) plus an orchestrator that fans out four parallel agents for hotels, transport, and destination intel, streaming results live. |

Each folder has its own README with an architecture diagram and setup steps.

### Running any of them

Every app is a small Python/Flask project:

```bash
cd <project-folder>
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # add your own API keys
python run.py
```

**No secrets are in this repository.** Each app reads its API keys and passwords
from a local `.env` file (git-ignored); the included `.env.example` files show
which variables to supply. You'll need your own [Anthropic API key](https://console.anthropic.com/),
and for the travel planner a [SerpAPI](https://serpapi.com/) and
[Google Maps](https://developers.google.com/maps) key.
