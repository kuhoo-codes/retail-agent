# Retail Store Agent

## Project overview

Retail Store Agent is an interactive command-line program for operating a small retail store.
It loads the supplied flat CSV exports into SQLite and supports sales, returns, promotions,
restocking, purchase-order receiving, margin reporting, and stockout-risk reporting.

All store math and mutations are deterministic Python code. The language and workflow layer is
model-driven: an OpenAI-compatible model interprets requests, calls tools, inspects their
results, and may call additional tools for multi-step work. It never calculates prices, refunds,
inventory, supplier choices, margins, or stockout risk itself.

This is a terminal application, not a web server.

## Requirements

- Python 3.11 or newer
- No third-party runtime packages
- `OPENAI_API_KEY` for natural-language operation
- Run commands from the repository root

## Setup

No installation is required. Confirm Python and seed the database:

```sh
python3 --version
PYTHONPATH=src python3 -m retail_store.seed
```

The seed command validates every file in `data/` and atomically generates
`var/retail_store.db`. The SQLite database is derived state; the CSV files remain the source
seed data.

## Run

Use this exact command:

```sh
PYTHONPATH=src python3 -m retail_store
```

The database is seeded automatically if it does not exist. Natural-language instructions require
`OPENAI_API_KEY`; without it the CLI remains available for `help`, `reset`, and `exit`, but store
requests return an explicit configuration error.

Interactive commands:

- `help` — show command help
- `reset` — reseed SQLite from the CSV files and clear session memory
- `exit` or `quit` — close the program

To reset without entering the application:

```sh
PYTHONPATH=src python3 -m retail_store.seed
```

## Test

The assignment-facing `unittest` suite:

```sh
python3 -m unittest discover -s tests -v
```

The expanded acceptance suite uses `pytest`:

```sh
pytest -q
```

The unit suite uses scripted model clients, so it does not make network calls.

## Environment variables

- `OPENAI_API_KEY` — required for natural-language store requests.
- `RETAIL_AGENT_MODEL` — optional model override; defaults to `gpt-5.4-nano`.
- `DEBUG=1` — optional; show tracebacks for startup and database errors.
- `OPENAI_BASE_URL` — optional OpenAI-compatible endpoint override.

The CLI automatically loads these values from a project-root `.env` file. Variables already
exported in the shell take precedence. Example:

```dotenv
OPENAI_API_KEY=your-key
RETAIL_AGENT_MODEL=gpt-5.4-nano
DEBUG=0
```

`.env` is ignored by Git and must not be committed.

## Example terminal session

```text
Retail Store Agent ready. Type an instruction, or 'exit' to quit.
> Ring up one Navy Medium hoodie for Sarah Chen.
Order O-1016 completed for C-001: 1 × Pullover Hoodie (HOOD-NVY-M) at $60.00. Total paid: $60.00.
> now refund that
Return R-2002 processed for HOOD-NVY-M. Refund: $60.00. Inventory increased by 1.
> What's about to stock out?
Stockout risk: Canvas Tote (4 on hand, 12.0 days of cover; at_or_below_reorder_point, fewer_than_14_days_of_cover; SKUs at or below reorder point: TOTE).
> exit
Goodbye.
```

## Troubleshooting

- `No module named retail_store`: run from the repository root and include `PYTHONPATH=src`.
- Seed or schema error: run `PYTHONPATH=src python3 -m retail_store.seed` to recreate SQLite.
- LLM/API error: verify `OPENAI_API_KEY`, `RETAIL_AGENT_MODEL`, and `OPENAI_BASE_URL`.
- Unexpected persisted state: enter `reset` or rerun the seed command.
- Need a traceback: rerun with `DEBUG=1`.

## Documentation

- [WRITEUP.md](WRITEUP.md) — concise implementation and design summary
- [docs/DOMAIN_MODEL.md](docs/DOMAIN_MODEL.md) — entities and persistence decisions
- [docs/TOOLS.md](docs/TOOLS.md) — tool/action reference
