from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_root_has_no_generated_lfs_hook_directory():
    assert not (ROOT / "dev" / "null").exists(), (
        "remove generated dev/null Git LFS hooks"
    )
