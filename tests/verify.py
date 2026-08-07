import os
import sys
import unittest

# Ensure the root project path is in sys.path
sys.path.append(os.path.abspath(os.path.dirname(os.path.dirname(__file__))))


from tests.test_pipeline import TestPipeline  # noqa: F401

if __name__ == "__main__":
    unittest.main()
