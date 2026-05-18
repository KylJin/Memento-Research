# AutoResearch — OMC Research Lab

## Prerequisites

- **OneManCompany** cloned at `~/projects/OneManCompany` with `.venv` set up
- API keys configured in `.onemancompany/.env`

## Quick Start

```bash
# Pull latest and restart
git pull && bash start.sh restart

# Open in browser
open http://localhost:8000
```

## Commands

```bash
# Start the backend in the current terminal
bash start.sh

# Stop the backend on port 8000
bash start.sh stop

# Restart the backend on port 8000
bash start.sh restart

# Re-run the setup wizard only
bash start.sh init

# Check whether the backend is listening
bash start.sh status
```

## Logs

```bash
# Detached mode
nohup bash start.sh restart > /tmp/omc-backend.log 2>&1 &

# Live logs
tail -f /tmp/omc-backend.log
```
