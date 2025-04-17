# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build Commands
- Run on desktop: `python main.py`
- Run tests: None defined
- Setup development environment: `pip install -r requirements.txt`
- Setup CircuitPython stubs: `circuitpython_setboard adafruit_feather_esp32s2_reverse_tft`

## Code Style Guidelines
- **Imports**: Group imports by standard library, CircuitPython, and third-party packages, contained in .wsl-venv virtual environment
- **Error Handling**: Use try/except with specific exceptions, using traceback.print_exception(e) and informative error messages
- **Naming**: Use snake_case for variables and functions, PascalCase for classes
- **Types**: Use appropriate type hints where helpful
- **Formatting**: Four-space indentation, max 100 characters per line
- **CircuitPython Compatibility**: Check platform with `is_circuitpython` flag and use appropriate conditionals for platform-specific code
- **Desktop Compatibility**: Use stubs for any unusable CircuitPython modules when running on desktop (e.g. sensors), but attempt IO requests
- **Configuration**: Use environment variables from settings.toml with sensible defaults
- **State Management**: Save and load state using JSON files