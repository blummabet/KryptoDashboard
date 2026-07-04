import pathlib
import sys

# Repo-Root importierbar machen (Tests laufen ohne Installation).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
