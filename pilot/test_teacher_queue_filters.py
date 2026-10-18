"""Runs the Node UI checks for the teacher review-queue filters."""
import shutil
import subprocess
import unittest
from pathlib import Path


class TeacherQueueFiltersUiTest(unittest.TestCase):
    def test_queue_filters_ui(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node недоступен для JS UI-проверок')
        script = Path(__file__).with_name('test_teacher_queue_filters_ui.js')
        result = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == '__main__':
    unittest.main()
