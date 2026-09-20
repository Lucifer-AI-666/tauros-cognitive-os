#!/usr/bin/env python3
"""Expose TAUROS on a public HTTPS URL via localtunnel (dev/demo only)."""
import subprocess
import sys

def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "8000"
    print("Starting localtunnel on port", port)
    print("Keep this process running. Open the HTTPS URL, then Install app (PWA).")
    print("WARNING: public exposure — use a strong TAUROS_API_TOKEN.")
    subprocess.check_call(["npx", "--yes", "localtunnel", "--port", port])

if __name__ == "__main__":
    main()
