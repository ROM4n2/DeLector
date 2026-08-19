from pathlib import Path


def test_android_uses_fastapi_version_without_pydantic_v2_build_dependency():
    build_gradle = Path("android/app/build.gradle").read_text(encoding="utf-8")
    assert 'install "fastapi==0.95.2"' in build_gradle
