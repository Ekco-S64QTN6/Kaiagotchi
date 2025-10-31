#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
The main entry point wrapper for the Kaiagotchi application.

This script imports and runs the main function from the application's
core manager module (kaiagotchi/manager.py). This is the file that 
will be executed by the user.
"""

# The manager.py file is the core engine, containing the main() function 
# responsible for argument parsing, initialization, and starting the loop.
try:
    from kaiagotchi.manager import main
except ImportError:
    # Fallback for when running directly from the directory without a package install
    from manager import main


if __name__ == '__main__':
    main()