# Gas Station Locator

## Install uv

Install uv once on your computer. On macOS or Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart your terminal if needed, then verify the installation:

```bash
uv --version
```

## Development setup

This project uses [uv](https://docs.astral.sh/uv/) to manage its Python environment and dependencies.

```bash
uv sync
source .venv/bin/activate
```

Run tests with:

```bash
uv run pytest
```

Create a local environment file for API keys when needed. Never commit `.env`:

```bash
cp .env.example .env
```
