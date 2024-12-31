# Use an official Python 3.12 slim image
FROM python:3.12-slim

# Set working directory inside the container
WORKDIR /app

# Install dependencies
RUN apt-get update && \
    apt-get install -y curl && \
    rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -

# Copy pyproject.toml and poetry.lock for dependency installation
COPY pyproject.toml poetry.lock ./

# NOTE: Use this if you need to access private codeartifact shared python libraries
# ARG CODEARTIFACT_TOKEN
# ENV CODEARTIFACT_TOKEN=${CODEARTIFACT_TOKEN}
# RUN ~/.local/bin/poetry config http-basic.mycompany aws ${CODEARTIFACT_TOKEN}

# Install dependencies using Poetry (only production dependencies)
RUN ~/.local/bin/poetry install --only main --no-dev

# Locate Poetry's virtual environment and copy dependencies to the Lambda path
RUN VENV_PATH=$(~/.local/bin/poetry env info --path) && \
    cp -r ${VENV_PATH}/lib/python3.12/site-packages/* ./

# Copy function code
COPY app ./app/

##############################################################################################################
# UN-COMMENT ONE OF THE SECTIONS BELOW
##############################################################################################################


##############################################################################################################
# Basic Task
##############################################################################################################
CMD ["python", "app/main.py"]

##############################################################################################################
# FastAPI App Service
##############################################################################################################

## Expose the port the app will run on
#EXPOSE 8080
#
## Command to run the application using Uvicorn
#CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "4", "--loop", "uvloop", "--http", "httptools", "--log-config", "logging_config.json"]
