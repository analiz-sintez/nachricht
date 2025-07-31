VENV_PATH := venv
PYTHON_BIN := python3

.PHONY: all venv run clean db-init migrate

all: venv db-init run

# Create or recreate virtual environment and install dependencies
venv: 
	@if [ ! -d "$(VENV_PATH)" ]; then \
		$(PYTHON_BIN) -m venv $(VENV_PATH); \
	fi
	. $(VENV_PATH)/bin/activate && pip install --upgrade pip && pip install -r requirements.txt

poetry:
	cat ./requirements.txt | grep -v "@" | xargs poetry add

# Run unit-tests
test:
	. $(VENV_PATH)/bin/activate && pytest

test-verbose:
	. $(VENV_PATH)/bin/activate && pytest -s --log-cli-level=INFO

# Clean the virtual environment and remove the existing database
clean:
	rm -rf $(VENV_PATH)
