#!/usr/bin/env bash
#
# REDPILOT — Autonomous Penetration Testing Framework
# One-command installer
#
# Usage: curl -fsSL https://raw.githubusercontent.com/Thanwisut/RedPilot/main/apps/tui/scripts/install.sh | bash
#
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${RED}"
echo "  ██████  ███████ ██████  ██████  ██ ██      ██████  ████████"
echo "  ██   ██ ██      ██   ██ ██   ██ ██ ██      ██   ██    ██"
echo "  ██████  █████   ██████  ██████  ██ ██      ██████     ██"
echo "  ██   ██ ██      ██      ██   ██ ██ ██      ██   ██    ██"
echo "  ██   ██ ███████ ██      ██   ██ ██ ███████ ██████     ██"
echo -e "${NC}"
echo -e "${CYAN}Autonomous Penetration Testing Framework${NC}"
echo ""

# ── Prerequisites ──────────────────────────────────────────────────────────

echo -e "${YELLOW}[1/5] Checking prerequisites...${NC}"

if command -v node &>/dev/null; then
  NODE_VERSION=$(node -v | sed 's/v//' | cut -d. -f1)
  if [ "$NODE_VERSION" -lt 18 ]; then
    echo -e "${RED}✗ Node.js 18+ required (found v$(node -v | sed 's/v//'))${NC}"
    echo "  Install via: https://nodejs.org/"
    exit 1
  fi
  echo -e "${GREEN}✓ Node.js $(node -v)${NC}"
else
  echo -e "${RED}✗ Node.js not found${NC}"
  echo "  Install via: https://nodejs.org/"
  exit 1
fi

if command -v npm &>/dev/null; then
  echo -e "${GREEN}✓ npm $(npm -v)${NC}"
else
  echo -e "${RED}✗ npm not found${NC}"
  exit 1
fi

if command -v git &>/dev/null; then
  echo -e "${GREEN}✓ git $(git --version | cut -d' ' -f3)${NC}"
else
  echo -e "${RED}✗ git not found${NC}"
  exit 1
fi

if command -v python3 &>/dev/null; then
  echo -e "${GREEN}✓ Python $(python3 --version | cut -d' ' -f2)${NC}"
else
  echo -e "${YELLOW}⚠ Python 3 not found (required for backend penetration tools)${NC}"
fi

# ── Installation directory ────────────────────────────────────────────────

INSTALL_DIR="${HOME}/.redpilot"
REPO_DIR="${INSTALL_DIR}/redpilot"
BIN_DIR="${HOME}/.local/bin"

echo ""
echo -e "${YELLOW}[2/5] Creating directories...${NC}"
mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"
echo -e "${GREEN}✓ ${INSTALL_DIR}${NC}"
echo -e "${GREEN}✓ ${BIN_DIR}${NC}"

# ── Clone or update repository ────────────────────────────────────────────

echo ""
echo -e "${YELLOW}[3/5] Installing REDPILOT TUI...${NC}"

REPO_URL="https://github.com/Thanwisut/RedPilot"

if [ -d "$REPO_DIR/.git" ]; then
  echo "Repository exists — pulling latest changes..."
  git -C "$REPO_DIR" pull --ff-only
  echo -e "${GREEN}✓ Repository updated${NC}"
else
  echo "Cloning repository..."
  git clone "$REPO_URL" "$REPO_DIR"
  echo -e "${GREEN}✓ Repository cloned to ${REPO_DIR}${NC}"
fi

# ── Install dependencies and build ────────────────────────────────────────

echo ""
echo -e "${YELLOW}[4/5] Installing dependencies...${NC}"

cd "$REPO_DIR/apps/tui"
npm install --silent --no-fund --no-audit 2>&1 | tail -1
echo -e "${GREEN}✓ Dependencies installed${NC}"

echo ""
echo "Building..."
npx tsc --noEmit 2>&1 || true
echo -e "${GREEN}✓ TypeScript build complete${NC}"

# ── Create executable wrapper ─────────────────────────────────────────────

echo ""
echo -e "${YELLOW}[5/5] Creating redplt command...${NC}"

cat > "$BIN_DIR/redplt" << 'EXEC'
#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="${HOME}/.redpilot/redpilot"
cd "$REPO_DIR/apps/tui"
exec npx tsx src/index.tsx "$@"
EXEC

chmod +x "$BIN_DIR/redplt"
echo -e "${GREEN}✓ Created ${BIN_DIR}/redplt${NC}"

# ── PATH setup ───────────────────────────────────────────────────────────

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  SHELL_CONFIG=""
  if [ -n "${BASH_VERSION:-}" ] && [ -f "$HOME/.bashrc" ]; then
    SHELL_CONFIG="$HOME/.bashrc"
  elif [ -n "${ZSH_VERSION:-}" ] && [ -f "$HOME/.zshrc" ]; then
    SHELL_CONFIG="$HOME/.zshrc"
  fi

  if [ -n "$SHELL_CONFIG" ]; then
    echo "" >> "$SHELL_CONFIG"
    echo "# REDPILOT" >> "$SHELL_CONFIG"
    echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> "$SHELL_CONFIG"
    echo -e "${YELLOW}⚠ Added ${BIN_DIR} to PATH in ${SHELL_CONFIG}${NC}"
    echo "  Restart your terminal or run: source $SHELL_CONFIG"
  else
    echo -e "${YELLOW}⚠ ${BIN_DIR} is not in PATH${NC}"
    echo "  Add it manually: export PATH=\"\$HOME/.local/bin:\$PATH\""
  fi
fi

# ── Success ───────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  ✓ REDPILOT installed successfully${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  Run:  ${CYAN}redplt${NC}"
echo ""
echo -e "  ${YELLOW}Note: The mock backend server is included for development.${NC}"
echo -e "  ${YELLOW}Start it alongside the TUI in a separate terminal:${NC}"
echo -e "  ${CYAN}cd ~/.redpilot/redpilot/apps/tui && npx tsx mock-server/index.ts${NC}"
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
