import importlib.util
import os
import unittest

_path = os.path.join(os.path.dirname(__file__), "..", "..", "re", "compare_noop.py")
_spec = importlib.util.spec_from_file_location("compare_noop", _path)
compare_noop = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare_noop)


class DiffTable(unittest.TestCase):
    def test_reports_each_kind_of_difference_in_numeric_order(self):
        d = compare_noop.diff_table({"10": "A", "9": "B", "1": "C"}, {"1": "D", "2": "E"})
        self.assertEqual(list(d["only_ours"]), ["9", "10"])
        self.assertEqual(d["only_noop"], {"2": "E"})
        self.assertEqual(d["renamed"], {"1": ("C", "D")})


if __name__ == "__main__":
    unittest.main()
