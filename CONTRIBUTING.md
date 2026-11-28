# Contributing to Trailswarm

Trailswarm is a one-person project. Robert Floyd Dugger directs the work and AI coding agents do most of the building. Outside contributions are not expected, but issues are welcome.

## Ways to help

- **Report a bug:** open an issue. Say what you ran, what you saw, and your Python and PyBoy versions.
- **Suggest something:** open an issue and describe it. Please ask before opening a large pull request.
- **Report a security problem:** see [`SECURITY.md`](SECURITY.md).
- **Rights holders:** see [`docs/LEGAL.md`](docs/LEGAL.md).

## Rules for every change

- Never commit a ROM, boot ROM, firmware or decryption key, and never say where a copy of a game came from.
- Follow [`docs/LEGAL.md`](docs/LEGAL.md) for what may and may not be in the repository.
- Work on a branch. Run `uv run pytest -q` before pushing; tests run without a ROM.
- Agents should also read [`AGENTS.md`](AGENTS.md).

## Licence

By contributing you agree that your contribution is licensed under the [MIT License](LICENSE), which covers only the original code and documentation of this project.
