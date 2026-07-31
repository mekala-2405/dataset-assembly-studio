import tarfile
import tempfile
import unittest
from pathlib import Path

from backend.archives import create_export_archive


class ArchiveTests(unittest.TestCase):
    def test_archive_has_one_dataset_folder_and_keeps_source_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "combined"
            (source / "meta").mkdir(parents=True)
            (source / "meta" / "info.json").write_text('{"ok": true}')
            destination = root / "downloads" / "job.tar.gz"

            result = create_export_archive(source, destination)

            self.assertEqual(result, destination)
            self.assertTrue((source / "meta" / "info.json").is_file())
            with tarfile.open(destination, "r:gz") as archive:
                names = archive.getnames()
            self.assertTrue(names)
            self.assertTrue(all(name == "combined" or name.startswith("combined/") for name in names))
            self.assertFalse(destination.with_suffix(destination.suffix + ".tmp").exists())

    def test_missing_source_does_not_leave_a_partial_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = root / "downloads" / "job.tar.gz"

            with self.assertRaises(FileNotFoundError):
                create_export_archive(root / "missing", destination)

            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_suffix(destination.suffix + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
