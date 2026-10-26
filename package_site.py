"""Copy site/ to dist/ with a full HTML document wrapper, ready for GitHub Pages or any static host."""
import shutil, sys
from pathlib import Path

SRC, DST = Path("site"), Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
shutil.rmtree(DST, ignore_errors=True)
shutil.copytree(SRC, DST)
body = (SRC / "index.html").read_text(encoding="utf-8").replace('<meta charset="utf-8">\n', "", 1)
(DST / "index.html").write_text(
    '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
    '<style>body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>\n'
    + body.replace("</style>", "</style>\n</head>\n<body>", 1) + "\n</body>\n</html>\n",
    encoding="utf-8")
print(f"packaged {DST}/")
