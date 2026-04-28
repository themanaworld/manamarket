"""Expose every module's doctests as a unittest suite for `unittest discover`."""
import doctest
import os
import sys

# Make the repo root importable when running `python -m unittest discover tests`
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import being
import tradey
import utils


def load_tests(loader, tests, ignore):
    for module in (utils, being, tradey):
        tests.addTests(doctest.DocTestSuite(module))
    return tests
