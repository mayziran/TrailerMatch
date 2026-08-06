import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from core.matcher import normalize_name
from core.scanner import scan_movies, scan_trailers
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    print("GUI ok")

    assert normalize_name("Home.Alone.1990.1080p.BluRay.x264-YTS.mkv") == "home alone"
    assert normalize_name("Deadpool.and.Wolverine.Trailer.4K.2024.mp4") == "deadpool and wolverine"
    print("normalize ok")

    with TemporaryDirectory() as td:
        root = Path(td)
        tdir = root / "trailers"
        mdir = root / "movies"
        tdir.mkdir()
        mdir.mkdir()
        (tdir / "Deadpool.sample.mp4").write_bytes(b"x")
        (tdir / "Home.Alone.trailer.mp4").write_bytes(b"x")
        m1 = mdir / "Home Alone (1990)"
        m1.mkdir()
        (m1 / "Home.Alone.1990.mkv").write_bytes(b"x")

        trailers = scan_trailers(tdir, [r"sample\.mp4$"])
        assert [t.name for t in trailers] == ["Deadpool.sample.mp4"], [t.name for t in trailers]
        print("trailers ok:", [t.name for t in trailers])

        movies = scan_movies(mdir)
        assert [m.name for m in movies] == ["Home.Alone.1990"], [m.name for m in movies]
        print("movies ok:", [m.name for m in movies])

    print("ALL OK")


if __name__ == "__main__":
    main()
