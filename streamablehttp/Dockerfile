# Use the official Python 3.12 slim image as the base image.
FROM python:3.12-slim

# Install uv
RUN pip install uv

# Set the working directory in the container to /app
WORKDIR /app

# Copy the dependency configuration file (PEP 621/Poetry-style) into the container
COPY pyproject.toml uv.lock ./

# Copy server code
COPY research_server.py .

# Install dependencies
RUN uv sync --frozen

# create papers directory
RUN mkdir -p papers

# Run the server using uv
CMD ["uv", "run", "research_server.py"]