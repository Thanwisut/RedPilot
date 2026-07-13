# REDPILOT Makefile — dev workflow automation
#
# Quick start:
#   make          Show available commands
#   make dev      Start backend (background) + TUI (foreground)
#   make backend  Start Python backend (foreground)
#   make tui      Start TUI (foreground)
#   make test     Run all tests (Python + TUI + typecheck)
#   make test-python  Run Python tests
#   make test-tui     Run TUI tests
#   make typecheck    TypeScript type-check
#   make clean    Remove build artifacts

.PHONY: help dev backend tui test test-python test-tui typecheck clean

# ── Configuration ────────────────────────────────────────────────────

PORT      ?= 8080
TUI_DIR   ?= apps/tui
API_DIR   ?= apps/api
PYTHON    ?= uv run python
# ── Default target ───────────────────────────────────────────────────

help:
	@echo ""
	@echo "REDPILOT — available commands:"
	@echo ""
	@echo "  make dev           Start backend (bg) + TUI (fg)"
	@echo "  make backend       Start Python backend only"
	@echo "  make tui           Start TUI only"
	@echo "  make test          Run all tests"
	@echo "  make test-python   Run Python tests"
	@echo "  make test-tui      Run TUI tests"
	@echo "  make typecheck     TypeScript type-check"
	@echo "  make clean         Remove build artifacts"
	@echo ""
	@echo "  PORT=8081          Override backend port"
	@echo "  ARGS=\"-k test\"    Filter tests (pytest/vitest)"
	@echo ""

.DEFAULT_GOAL := help

# ── Start both services ──────────────────────────────────────────────

dev:
	@echo "── Backend ────────────────────────────────────────"
	@echo "  Starting REDPILOT API server on port $(PORT)..."
	@echo "  WebSocket: ws://localhost:$(PORT)/ws"
	@cd $(PWD) && $(PYTHON) $(API_DIR)/run.py $(PORT) > /tmp/redpilot-backend.log 2>&1 & \
	  echo $$! > /tmp/redpilot-backend.pid
	@sleep 2
	@echo ""
	@echo "── TUI ────────────────────────────────────────────"
	@echo "  Starting REDPILOT TUI..."
	@echo "  Press Ctrl+C to stop both."
	@echo ""
	-cd $(PWD)/$(TUI_DIR) && npx tsx src/index.tsx; \
	  BGPID=$$(cat /tmp/redpilot-backend.pid 2>/dev/null); \
	  echo ""; \
	  echo "── Stopping backend ─────────────────────────────"; \
	  if [ -n "$$BGPID" ]; then kill $$BGPID 2>/dev/null || true; fi; \
	  rm -f /tmp/redpilot-backend.pid; \
	  echo "  Done."

# ── Start Python backend only (foreground) ───────────────────────────

backend:
	@echo "── Backend ────────────────────────────────────────"
	@echo "  Starting REDPILOT API server on port $(PORT)..."
	@echo "  WebSocket: ws://localhost:$(PORT)/ws"
	@echo "  Press Ctrl+C to stop."
	@echo ""
	cd $(PWD) && $(PYTHON) $(API_DIR)/run.py $(PORT)

# ── Start TUI only (foreground) ──────────────────────────────────────

tui:
	@echo "── TUI ────────────────────────────────────────────"
	@echo "  Starting REDPILOT TUI..."
	@echo "  (Connect to existing backend at ws://localhost:$(PORT)/ws)"
	@echo ""
	cd $(PWD)/$(TUI_DIR) && npx tsx src/index.tsx

# ── Tests ────────────────────────────────────────────────────────────

test: test-python test-tui typecheck
	@echo ""
	@echo "── All tests passed ────────────────────────────────"

test-python:
	@echo "── Python tests ──────────────────────────────────"
	@cd $(PWD) && uv run python -m pytest tests/ -v --tb=short \
		--ignore=tests/tools/test_docker_sandbox.py \
		-k "not docker" \
		$(ARGS)
	@echo ""

test-tui:
	@echo "── TUI tests ─────────────────────────────────────"
	@cd $(PWD)/$(TUI_DIR) && npx vitest run $(ARGS)
	@echo ""

# ── TypeScript type-check ────────────────────────────────────────────

typecheck:
	@echo "── TypeScript type-check ────────────────────────"
	@cd $(PWD)/$(TUI_DIR) && npx tsc --noEmit
	@echo "  No type errors."
	@echo ""

# ── Cleanup ──────────────────────────────────────────────────────────

clean:
	@echo "── Clean ─────────────────────────────────────────"
	@rm -rf $(TUI_DIR)/dist $(TUI_DIR)/node_modules/.cache
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name '.pytest_cache' -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name '*.pyc' -delete 2>/dev/null || true
	@echo "  Cleaned caches and build artifacts."
	@echo ""
