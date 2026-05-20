#!/usr/bin/env bash
# exit on error
set -o errexit

# Set CARGO_HOME to a writable directory
export CARGO_HOME=/opt/render/project/.cargo

# Add Rust to the PATH
export PATH=$CARGO_HOME/bin:$PATH

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt
