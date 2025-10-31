# Setup development environment for Kaiagotchi

# Create virtual environment if it doesn't exist
if (-not (Test-Path .venv)) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}

# Activate virtual environment
. .\.venv\Scripts\Activate.ps1

# Install development dependencies
pip install -e ".[dev]"
pip install pytest pytest-asyncio pytest-cov black isort mypy

# Create necessary directories
$dirs = @(
    "handshakes",
    "logs",
    "data"
)

foreach ($dir in $dirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir
        Write-Host "Created directory: $dir"
    }
}

# Run initial tests
pytest tests/ --cov=kaiagotchi