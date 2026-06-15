import traceback

from next_agent.desktop import main
from next_agent.gui_server import app_data_dir


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        path = app_data_dir() / "desktop_error.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(traceback.format_exc(), encoding="utf-8")
        raise
