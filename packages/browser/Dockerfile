# Playwright browser sandbox image
# Based on official Playwright image with Chromium pre-installed
FROM mcr.microsoft.com/playwright:v1.51.0-noble

LABEL description="REDPILOT browser sandbox — Playwright Python + Chromium"

# Install Python 3 and pip (the base image has Node.js but not Python)
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Install the Playwright Python package
RUN pip3 install playwright==1.51.0

# Install the @playwright/mcp Node.js server for MCP-compatible clients
RUN npm install -g @playwright/mcp@latest

# Create directory for browser state persistence
RUN mkdir -p /browser-state && chmod 777 /browser-state

# Copy the browser CLI script
COPY src/redpilot_browser/cli.py /usr/local/bin/redpilot-browser
RUN chmod +x /usr/local/bin/redpilot-browser

# Set the output directory environment variable
ENV BROWSER_OUTPUT_DIR=/scratch

# Default command: show help
CMD ["python3", "/usr/local/bin/redpilot-browser", "--help"]

# Switch back to the non-root user for security (playwright user from base image)
USER pwuser
