"""Write checksums for built ZIP, wheel and sdist artifacts."""
import hashlib
from pathlib import Path


def checksums(directory=Path("dist")):
    artifacts = sorted(p for p in directory.iterdir() if p.is_file() and p.name.endswith((".zip", ".whl", ".tar.gz")))
    if not all(any(p.name.endswith(suffix) for p in artifacts) for suffix in (".zip", ".whl", ".tar.gz")):
        raise ValueError("Build the plugin ZIP, wheel and sdist before generating checksums")
    output = directory / "SHA256SUMS"
    output.write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in artifacts), encoding="utf-8")
    return output


if __name__ == "__main__":
    print(checksums())
