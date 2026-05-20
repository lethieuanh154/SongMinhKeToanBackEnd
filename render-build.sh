#!/usr/bin/env bash
# exit on error
set -o errexit

# Force Cargo to use a writable directory
export CARGO_HOME=/tmp/cargo
export PATH=$CARGO_HOME/bin:$PATH

# Install Python dependencies
# Use --only-binary for Rust-dependent packages to avoid maturin build issues
pip install --upgrade pip
pip install --only-binary=bcrypt,google-crc32c -r requirements.txt
