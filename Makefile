# Makefile for the Picklock Python package

# Variables
PACKAGE_NAME = picklock
PYTHON = python3
PIP = pip3
BUILD_DIR = build
DIST_DIR = dist
EGG_INFO = $(PACKAGE_NAME).egg-info
VENV_DIR = venv
TEST_DIR = tests

# Colors for output
GREEN = \033[0;32m
YELLOW = \033[0;33m
RED = \033[0;31m
BLUE = \033[0;34m
NC = \033[0m # No Color

# Default target
.PHONY: help
help:
	@echo "$(GREEN)Picklock Python package Makefile$(NC)"
	@echo ""
	@echo "Available targets:"
	@echo "  $(YELLOW)install$(NC)          - Install package in development mode"
	@echo "  $(YELLOW)install-deps$(NC)     - Install runtime dependencies"
	@echo "  $(YELLOW)install-dev$(NC)      - Install development dependencies"
	@echo "  $(YELLOW)install-speed$(NC)    - Install with the NumPy scan accelerator"
	@echo "  $(YELLOW)run$(NC)              - Launch the Picklock shell"
	@echo "  $(YELLOW)test$(NC)             - Run tests"
	@echo "  $(YELLOW)test-verbose$(NC)     - Run tests with verbose output"
	@echo "  $(YELLOW)test-coverage$(NC)    - Run tests with coverage report"
	@echo "  $(YELLOW)lint$(NC)             - Run linter (flake8)"
	@echo "  $(YELLOW)type-check$(NC)       - Run type checker (mypy)"
	@echo "  $(YELLOW)smoke$(NC)            - Check the installed console script starts"
	@echo "  $(YELLOW)screenshot$(NC)       - Regenerate the README terminal capture"
	@echo "  $(YELLOW)docs$(NC)             - Build the documentation site"
	@echo "  $(YELLOW)docs-serve$(NC)       - Build the docs and open them in a browser"
	@echo "  $(YELLOW)clean$(NC)            - Clean build artifacts"
	@echo "  $(YELLOW)build$(NC)            - Build package"
	@echo "  $(YELLOW)build-wheel$(NC)      - Build wheel package"
	@echo "  $(YELLOW)build-sdist$(NC)      - Build source distribution"
	@echo "  $(YELLOW)validate$(NC)         - Validate package"
	@echo "  $(YELLOW)publish$(NC)          - Publish to PyPI"
	@echo "  $(YELLOW)publish-test$(NC)     - Publish to Test PyPI"
	@echo "  $(YELLOW)version$(NC)          - Show current version"
	@echo "  $(YELLOW)check-deps$(NC)       - Check for outdated dependencies"
	@echo "  $(YELLOW)update-deps$(NC)      - Update dependencies"
	@echo "  $(YELLOW)security$(NC)         - Run security audit"
	@echo "  $(YELLOW)venv$(NC)             - Create virtual environment"
	@echo "  $(YELLOW)venv-activate$(NC)    - Show command to activate venv"
	@echo "  $(YELLOW)all$(NC)              - Run full pipeline (install, lint, test, build)"

# Create virtual environment
.PHONY: venv
venv:
	@echo "$(GREEN)Creating virtual environment...$(NC)"
	$(PYTHON) -m venv $(VENV_DIR)
	@echo "$(GREEN)Virtual environment created in $(VENV_DIR)$(NC)"
	@echo "$(YELLOW)To activate: source $(VENV_DIR)/bin/activate$(NC)"

# Show activation command
.PHONY: venv-activate
venv-activate:
	@echo "$(YELLOW)To activate virtual environment run:$(NC)"
	@echo "source $(VENV_DIR)/bin/activate"

# Install runtime dependencies (just PyMemoryEditor — see pyproject.toml)
.PHONY: install-deps
install-deps:
	@echo "$(GREEN)Installing runtime dependencies...$(NC)"
	$(PIP) install -e .
	@echo "$(GREEN)Dependencies installed successfully!$(NC)"

# Install development dependencies
.PHONY: install-dev
install-dev:
	@echo "$(GREEN)Installing development dependencies...$(NC)"
	$(PIP) install -e ".[dev]"
	@echo "$(GREEN)Development dependencies installed successfully!$(NC)"

# Install with the NumPy-accelerated scan path
.PHONY: install-speed
install-speed:
	@echo "$(GREEN)Installing with the NumPy scan accelerator...$(NC)"
	$(PIP) install -e ".[speed]"
	@echo "$(GREEN)Speed extra installed successfully!$(NC)"

# Install package in development mode
.PHONY: install
install:
	@echo "$(GREEN)Installing package in development mode...$(NC)"
	$(PIP) install -e .
	@echo "$(GREEN)Package installed successfully!$(NC)"

# Launch the shell straight from the working tree
.PHONY: run
run:
	@echo "$(GREEN)Starting the Picklock shell...$(NC)"
	$(PYTHON) -m $(PACKAGE_NAME)

# Run tests
.PHONY: test
test:
	@echo "$(GREEN)Running tests...$(NC)"
	$(PYTHON) -m pytest $(TEST_DIR) -v
	@echo "$(GREEN)Tests completed!$(NC)"

# Run tests with verbose output
.PHONY: test-verbose
test-verbose:
	@echo "$(GREEN)Running tests with verbose output...$(NC)"
	$(PYTHON) -m pytest $(TEST_DIR) -v -s
	@echo "$(GREEN)Verbose tests completed!$(NC)"

# Run tests with coverage
.PHONY: test-coverage
test-coverage:
	@echo "$(GREEN)Running tests with coverage...$(NC)"
	$(PYTHON) -m pytest $(TEST_DIR) --cov=$(PACKAGE_NAME) --cov-report=html --cov-report=term
	@echo "$(GREEN)Coverage report generated!$(NC)"
	@echo "$(YELLOW)HTML report available at htmlcov/index.html$(NC)"

# Run linter
.PHONY: lint
lint:
	@echo "$(GREEN)Running linter (flake8)...$(NC)"
	$(PYTHON) -m flake8 $(PACKAGE_NAME) $(TEST_DIR)
	@echo "$(GREEN)Linting completed!$(NC)"

# Run type checker (config in pyproject.toml)
.PHONY: type-check
type-check:
	@echo "$(GREEN)Running type checker (mypy)...$(NC)"
	$(PYTHON) -m mypy $(PACKAGE_NAME)
	@echo "$(GREEN)Type checking completed!$(NC)"

# Check that the CLI starts and dispatches end to end. The test suite calls
# main() in-process; this drives it as a real process, so argv parsing, batch
# mode and the exit status are all exercised. CI additionally runs the
# installed `picklock` console script to prove the entry point resolves.
.PHONY: smoke
smoke:
	@echo "$(GREEN)Checking the console script...$(NC)"
	$(PYTHON) -m $(PACKAGE_NAME) --version
	$(PYTHON) -m $(PACKAGE_NAME) -e "version" > /dev/null
	$(PYTHON) -m $(PACKAGE_NAME) -e "help scan" > /dev/null
	$(PYTHON) -m $(PACKAGE_NAME) ps:help > /dev/null
	$(PYTHON) -m $(PACKAGE_NAME) ps:list --limit 5 > /dev/null
	@echo "$(GREEN)Console script works!$(NC)"

# Regenerate the terminal capture in the README. Runs the real commands
# against a real process and screenshots the transcript, so it needs a
# Chrome/Chromium/Edge on the machine (set BROWSER to point at a specific one).
.PHONY: screenshot
screenshot:
	@echo "$(GREEN)Regenerating the README terminal capture...$(NC)"
	$(PYTHON) scripts/generate_terminal_image.py
	@echo "$(GREEN)Screenshot written to assets/screenshots/terminal.png$(NC)"

# Build the documentation. conf.py regenerates the command reference from the
# registry first, so the built site always matches the code in the tree.
.PHONY: docs
docs:
	@echo "$(GREEN)Building the documentation...$(NC)"
	$(PIP) install -q -r docs/requirements.txt
	$(PYTHON) -m sphinx -b html docs docs/_build/html
	@echo "$(GREEN)Docs built at docs/_build/html/index.html$(NC)"

.PHONY: docs-serve
docs-serve: docs
	$(PYTHON) -c "import webbrowser, pathlib; webbrowser.open(pathlib.Path('docs/_build/html/index.html').resolve().as_uri())"

# Clean build artifacts
.PHONY: clean
clean:
	@echo "$(GREEN)Cleaning build artifacts...$(NC)"
	rm -rf $(BUILD_DIR)
	rm -rf $(DIST_DIR)
	rm -rf $(EGG_INFO)
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage
	rm -rf coverage.xml
	rm -rf .mypy_cache
	rm -rf docs/_build
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.pyd" -delete
	find . -type f -name ".coverage" -delete
	@echo "$(GREEN)Cleanup completed!$(NC)"

# Build package
.PHONY: build
build: clean
	@echo "$(GREEN)Building package...$(NC)"
	$(PYTHON) -m build
	@echo "$(GREEN)Package built successfully!$(NC)"

# Build wheel package only
.PHONY: build-wheel
build-wheel: clean
	@echo "$(GREEN)Building wheel package...$(NC)"
	$(PYTHON) -m build --wheel
	@echo "$(GREEN)Wheel package built successfully!$(NC)"

# Build source distribution only
.PHONY: build-sdist
build-sdist: clean
	@echo "$(GREEN)Building source distribution...$(NC)"
	$(PYTHON) -m build --sdist
	@echo "$(GREEN)Source distribution built successfully!$(NC)"

# Validate package
.PHONY: validate
validate: build
	@echo "$(GREEN)Validating package...$(NC)"
	$(PYTHON) -m twine check $(DIST_DIR)/*
	@echo "$(GREEN)Package validation completed!$(NC)"

# Publish to PyPI
.PHONY: publish
publish: validate
	@echo "$(YELLOW)Are you sure you want to publish to PyPI? [y/N]$(NC)" && read ans && [ $${ans:-N} = y ]
	@echo "$(GREEN)Publishing to PyPI...$(NC)"
	$(PYTHON) -m twine upload $(DIST_DIR)/*
	@echo "$(GREEN)Package published successfully to PyPI!$(NC)"

# Publish to Test PyPI
.PHONY: publish-test
publish-test: validate
	@echo "$(GREEN)Publishing to Test PyPI...$(NC)"
	$(PYTHON) -m twine upload --repository testpypi $(DIST_DIR)/*
	@echo "$(GREEN)Package published successfully to Test PyPI!$(NC)"

# Show current version
.PHONY: version
version:
	@echo "$(GREEN)Current package version:$(NC)"
	@$(PYTHON) -c "import $(PACKAGE_NAME); print($(PACKAGE_NAME).__version__)"

# Check for outdated dependencies
.PHONY: check-deps
check-deps:
	@echo "$(GREEN)Checking for outdated dependencies...$(NC)"
	$(PIP) list --outdated

# Update dependencies
.PHONY: update-deps
update-deps:
	@echo "$(GREEN)Updating dependencies...$(NC)"
	$(PIP) install --upgrade -e ".[dev]"
	@echo "$(GREEN)Dependencies updated!$(NC)"

# Security audit — uses pip-audit (PyPA-maintained) which works without a
# paid account, unlike the older `safety` tool.
.PHONY: security
security:
	@echo "$(GREEN)Running security audit (pip-audit)...$(NC)"
	$(PIP) install pip-audit
	pip-audit
	@echo "$(GREEN)Security audit completed!$(NC)"

# Full development pipeline
.PHONY: all
all: install lint type-check test build validate
	@echo "$(GREEN)Full pipeline completed successfully!$(NC)"

# Development workflow targets
.PHONY: dev-setup
dev-setup: venv install-dev install
	@echo "$(GREEN)Development environment setup completed!$(NC)"
	@echo "$(YELLOW)Don't forget to activate the virtual environment:$(NC)"
	@echo "source $(VENV_DIR)/bin/activate"

.PHONY: pre-commit
pre-commit: lint type-check test
	@echo "$(GREEN)Pre-commit checks passed!$(NC)"

.PHONY: pre-publish
pre-publish: all security
	@echo "$(GREEN)Pre-publish checks completed!$(NC)"

# CI/CD targets
.PHONY: ci
ci: install-dev install lint type-check test smoke build validate
	@echo "$(GREEN)CI pipeline completed!$(NC)"

# Show package info
.PHONY: info
info:
	@echo "$(GREEN)Package Information:$(NC)"
	@echo "Name: $(PACKAGE_NAME)"
	@$(PYTHON) -c "import $(PACKAGE_NAME); print('Version:', $(PACKAGE_NAME).__version__)" 2>/dev/null || echo "Version: Not installed"
	@$(PYTHON) -c "import PyMemoryEditor; print('PyMemoryEditor:', PyMemoryEditor.__version__)" 2>/dev/null || echo "PyMemoryEditor: Not installed"
	@echo "Python: $(shell $(PYTHON) --version)"
	@echo "Pip: $(shell $(PIP) --version)"
	@echo ""
	@echo "$(GREEN)Installed packages:$(NC)"
	@$(PIP) list | grep -E "($(PACKAGE_NAME)|PyMemoryEditor|pytest|flake8|mypy|twine|build)"

# Quick release workflow
.PHONY: release
release: pre-publish publish
	@echo "$(GREEN)Release completed!$(NC)"

.PHONY: release-test
release-test: pre-publish publish-test
	@echo "$(GREEN)Test release completed!$(NC)"

# Install from PyPI (for testing)
.PHONY: install-from-pypi
install-from-pypi:
	@echo "$(GREEN)Installing from PyPI...$(NC)"
	$(PIP) install $(PACKAGE_NAME)
	@echo "$(GREEN)Package installed from PyPI!$(NC)"

# Install from Test PyPI (for testing)
.PHONY: install-from-test-pypi
install-from-test-pypi:
	@echo "$(GREEN)Installing from Test PyPI...$(NC)"
	$(PIP) install --index-url https://test.pypi.org/simple/ $(PACKAGE_NAME)
	@echo "$(GREEN)Package installed from Test PyPI!$(NC)"

# Uninstall package
.PHONY: uninstall
uninstall:
	@echo "$(GREEN)Uninstalling package...$(NC)"
	$(PIP) uninstall $(PACKAGE_NAME) -y
	@echo "$(GREEN)Package uninstalled!$(NC)"
