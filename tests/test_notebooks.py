import json
from pathlib import Path


NOTEBOOKS = Path(__file__).resolve().parents[1] / "notebooks"


def test_all_python_notebook_cells_compile():
    """Reject syntactically broken source before the slower execution check."""
    paths = sorted(NOTEBOOKS.glob("[0-1][0-9]_*.ipynb"))
    assert [path.name[:2] for path in paths] == [f"{index:02d}" for index in range(14)]

    for path in paths:
        notebook = json.loads(path.read_text(encoding="utf-8"))
        for index, cell in enumerate(notebook["cells"]):
            if cell.get("cell_type") != "code":
                continue
            source = "".join(cell.get("source", ()))
            compile(source, f"{path.name}:cell-{index}", "exec")
